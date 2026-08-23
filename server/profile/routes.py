"""The `/api/profile` endpoints: read the whole profile, patch any part of it, reset it.

## The write endpoint takes a PARTIAL profile, and that is load-bearing

Onboarding is four steps and **each one persists as it completes**, so an abandoned
onboarding resumes rather than restarting (the plan's Zeigarnik point). The row is
therefore created on step 1, not step 4, and every later step is an update to a row that
already exists. One endpoint does both: `PATCH` upserts, and any field left out of the
body is left alone.

**`None` means "not in this request" for every scalar field**, and **that contract is now
load-bearing in a second way**: issue #54 needed a way to un-answer the steps, and teaching
`null` to mean "clear" was considered and rejected precisely because it would give every
omission a destructive second meaning. `POST /api/profile/reset` does that job instead. The
two collection fields (`aspect_ratings`, `injuries`) are different — a list **replaces** the
set it names, and `[]` is a real answer.

⚠️ **There were five steps and an `equipment_ids` field until issue #54.** The equipment step
is gone from onboarding and `equipment_ids` is gone from both models here; `user_equipment`
and every `exercise_equipment` requirement are untouched, because the owned-vs-lacked
question the issue raises is deliberately deferred to PR #10 (see `ProfilePatchRequest`).

⚠️ **`InjuryIn.note` is the one exception, and it is deliberate.** Omitting it *preserves*
the existing note; sending an explicit `null` *clears* it. `{"injuries": [{"injury_area_id":
3}]}` is the natural "keep this flagged" body for anything driving this API by hand, and
treating omitted as null would silently wipe the one piece of free text in the product. The
two are told apart with Pydantic's `model_fields_set`, which is the only thing that can:
after validation the value is `None` either way.

**No caller in this repo relies on the preserve half today** — the web client renders the
note input as part of the step, so it owns the whole field and always states the value
(`web/src/profile/draft.ts`). The distinction is kept because it is the correct semantics
for a partial patch and because the alternative is a silent data loss the moment any client
sends the shorter body; `tests/test_profile_api.py` covers all three cases.

## Unanswered is NULL — revision 0005, and it replaced placeholders

`primary_discipline`, `sessions_per_week` and `available_weekdays` were `NOT NULL` until
`0005`, so a row created on step 1 had to carry invented values for questions the later
steps had not asked yet. `sessions_per_week = 3` is a perfectly plausible answer, so the
completion bar credited work nobody had done and the plan generator would have read a
number the user never chose. Now:

- **The endpoint writes only the columns the body carried.** An empty body writes nothing
  at all — not even a row — because there is nothing to record.
- **`primary_discipline` is DERIVED from the target grade**, never sent by the client. The
  grade ladder is banded per discipline (`server/domain/grades.py`), so a French 7a target
  *is* a rope goal; accepting a separate field would let the two disagree, and the
  disagreement would only surface in the plan generator.
- **`injuries_reviewed_at` is stamped whenever its step is submitted**, with or without
  rows. **A step needs a `*_reviewed_at` column exactly when zero rows is a legitimate
  answer** — "nothing is hurting" writes no child rows, so an empty table cannot distinguish
  "asked, nothing" from "never asked". No other step needs one: the aspect step always
  writes eight rows, and the grades and availability are scalar columns whose NULL carries
  it. `equipment_reviewed_at` was the second one and is **retired** with its step (`0006`);
  the column stays until a later contract revision, and nothing reads it.

## The two grade columns must agree, and one of them can be cleared for you

`target_grade_id` and `current_grade_id` have to sit on the same **discipline**: the ordinal
ladders are disjoint and `domain.grades.convert` raises rather than compare across them. An
incoming current grade that disagrees is a 422; an incoming TARGET that disagrees with the
STORED current grade **clears it**, because refusing would make changing your goal
impossible. `_decide_grades` carries the full reasoning.

## Every id is resolved BEFORE anything is written

Not for tidiness: `_upsert_profile` runs first, so a bad aspect id rejected later would
leave a row behind in any transaction that is not rolled back. Validation of every
reference in the body happens up front, so a 422 means nothing was written.

## Every query is scoped by the token's `user_id`

Never a path parameter, never a body field. IDOR is the realistic extraction risk in this
product (`server/auth/deps.py`), and a profile row is keyed by exactly the id an attacker
would want to substitute.
"""

from datetime import date, datetime
from typing import Annotated, Final, NamedTuple

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from server.auth.deps import CurrentUser, RequestSession
from server.domain.grades import Discipline
from server.domain.vocabulary import CLIMBING_ASPECTS, INJURY_AREAS
from server.fields import (
    AspectScore,
    AvailableWeekdays,
    DisplayName,
    InjuryNote,
    LookupId,
    SessionsPerWeek,
)
from server.models import (
    AppUser,
    ClimbingAspect,
    Grade,
    GradeSystem,
    InjuryArea,
    UserAspectRating,
    UserInjury,
    UserProfile,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])

# The predicate of `uq_user_injury_open_area`. `ON CONFLICT` has to name a partial index's
# predicate in order to infer it, and this must stay identical to the index in
# `server/models.py` and in revision `0005` or the inference silently fails to match.
#
# A LITERAL passed to `text()`, with no interpolation and nothing client-supplied anywhere
# near it — the same shape as the one `SET LOCAL` in `server/auth/deps.py`. ⚠️ Note
# `func.text(...)` is NOT the same thing and compiles to a nonsense `WHERE text($1)`; it
# type-checks, lints and passes every local test, and fails only against real Postgres.
_OPEN_INJURY = text("resolved_on IS NULL")

# Fixed strings, on purpose: a 422 must never echo the request back, and that includes
# naming which id the caller sent (CLAUDE.md, "Validate at the edge with Pydantic").
_UNKNOWN_GRADE: Final = "That grade is not on the ladder."
_UNKNOWN_ASPECT: Final = "That climbing aspect does not exist."
_UNKNOWN_INJURY_AREA: Final = "That injury area does not exist."
# ⚠️ The ordinal ladders are disjoint per discipline and `domain.grades.convert` raises
# rather than compare across them, so a current grade on the other ladder is not a value the
# generator can do anything with. See `_decide_grades`.
_CROSS_DISCIPLINE_GRADES: Final = (
    "Your current grade and your goal must be on the same kind of climbing."
)
_SAME_ASPECT_TWICE: Final = "One aspect cannot be both your strength and your weakness."


class AspectRatingOut(BaseModel):
    """One self-rated aspect. `rated_at` is what lets a stale rating be shown as stale."""

    climbing_aspect_id: int
    score: int
    rated_at: datetime


class InjuryOut(BaseModel):
    """A currently-open injury. Resolved ones are history and are not returned here.

    `note` is user free text and is escaped on output by React — never
    `dangerouslySetInnerHTML` (CLAUDE.md, "Notes are untrusted on OUTPUT too").
    """

    injury_area_id: int
    note: str | None
    started_on: date


class ProfileResponse(BaseModel):
    """The whole profile, and everything the client needs to compute completion.

    ⚠️ **Every null here means "not answered yet", never "zero" or "none".** That is the
    whole point of revision `0005`, and it binds anything that reads this — the completion
    bar, and the plan generator in PR #11, which must refuse to generate rather than
    substitute a default for a question the user has not been asked.

    `injuries_reviewed_at` is how its step reports itself finished: an empty `injuries` list
    means "nothing to record" or "never asked" depending only on it. Every completion test
    the client makes reads that column or a scalar, which is what keeps the progress bar
    server truth.

    ⚠️ **`equipment_ids` and `equipment_reviewed_at` are gone** (issue #54). The step is not
    part of onboarding any more, nothing in the client read either field, and dropping them
    from the response also drops a `SELECT` from every profile read — Neon bills awake time.
    The table and its rows are untouched, waiting for PR #10.

    ⚠️ **`email` is the ONE null here that does not mean "not answered yet".** It is read
    from `app_user`, not from the profile, and it is `NOT NULL` there — so it can only be
    null if the row behind an authenticated principal has gone, which is not a state this
    endpoint invents a 404 for. It is read-only: the client displays it and has no way to
    change it, which is why it is not in `ProfilePatchRequest`. Added because the client had
    no way to learn its own account's address at all — `GET /api/auth/me` returns
    `{user_id, scope}` and its docstring defers exactly this to the profile endpoint.
    """

    email: str | None
    display_name: str | None
    target_grade_id: int | None
    current_grade_id: int | None
    primary_discipline: Discipline | None
    sessions_per_week: int | None
    available_weekdays: int | None
    strength_aspect_id: int | None
    weakness_aspect_id: int | None
    show_body_metrics: bool
    injuries_reviewed_at: datetime | None
    aspect_ratings: list[AspectRatingOut]
    injuries: list[InjuryOut]


class AspectRatingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    climbing_aspect_id: LookupId
    score: AspectScore


class InjuryIn(BaseModel):
    """One flagged injury area, and optionally a note about it.

    See the module docstring: **omitting `note` preserves whatever is stored; sending an
    explicit `null` clears it.** `note_was_sent` is the only way to tell, and it must be
    asked before the value — `None` is the post-validation value in both cases.
    """

    model_config = ConfigDict(extra="forbid")

    injury_area_id: LookupId
    note: InjuryNote | None = None

    @property
    def note_was_sent(self) -> bool:
        return "note" in self.model_fields_set


class ProfilePatchRequest(BaseModel):
    """Any subset of the profile. Everything omitted is left as it is.

    `extra="forbid"`, so a camelCase key or a typo is a 422 rather than a silently
    ignored field — and `primary_discipline` is **not** accepted at all: it is derived
    from `target_grade_id`.

    ⚠️ **`null` means "no change", for every field, and that contract is deliberate.**
    Issue #54 wanted a way to un-answer the four steps; making `null` mean "clear" here was
    considered and rejected, because it would turn every "I am not touching this" into a
    destructive spelling one typo away. `POST /api/profile/reset` does that job instead,
    explicitly and in one transaction.

    ⚠️ **`equipment_ids` is gone from this model** (issue #54). The equipment step is no
    longer part of onboarding, and the owned-vs-lacked question the issue raises is
    deliberately deferred to PR #10, where the exercise library's alternatives lookup is what
    gives a "I do not have this" flag its meaning. `user_equipment` and every
    `exercise_equipment` row are untouched; what is gone is a write path whose semantics are
    undecided. Re-adding it is PR #10's job, with the decision attached.
    """

    model_config = ConfigDict(extra="forbid")

    target_grade_id: LookupId | None = None
    current_grade_id: LookupId | None = None
    sessions_per_week: SessionsPerWeek | None = None
    available_weekdays: AvailableWeekdays | None = None
    strength_aspect_id: LookupId | None = None
    weakness_aspect_id: LookupId | None = None
    display_name: DisplayName | None = None
    show_body_metrics: bool | None = None

    # Each list REPLACES the set it names, and is bounded by the size of the vocabulary it
    # draws from — an unbounded list is a resource-exhaustion vector even when every id
    # in it is valid.
    aspect_ratings: (
        Annotated[list[AspectRatingIn], Field(max_length=len(CLIMBING_ASPECTS))] | None
    ) = None
    injuries: Annotated[list[InjuryIn], Field(max_length=len(INJURY_AREAS))] | None = None

    @field_validator("aspect_ratings")
    @classmethod
    def _one_rating_per_aspect(
        cls, value: list[AspectRatingIn] | None
    ) -> list[AspectRatingIn] | None:
        if value is not None and len({entry.climbing_aspect_id for entry in value}) != len(value):
            raise ValueError("one rating per aspect")
        return value

    @field_validator("injuries")
    @classmethod
    def _one_flag_per_area(cls, value: list[InjuryIn] | None) -> list[InjuryIn] | None:
        if value is not None and len({entry.injury_area_id for entry in value}) != len(value):
            raise ValueError("one flag per injury area")
        return value

    @model_validator(mode="after")
    def _strength_and_weakness_differ(self) -> "ProfilePatchRequest":
        """The same aspect cannot be both, and this is the edge half of the CHECK.

        Only when BOTH are in this body: one of them arriving alone is checked against the
        stored row in `_validate_references`, which is the only place that can see it.
        """
        if (
            self.strength_aspect_id is not None
            and self.strength_aspect_id == self.weakness_aspect_id
        ):
            raise ValueError(_SAME_ASPECT_TWICE)
        return self

    def is_empty(self) -> bool:
        """Nothing to write. A body like `{}` must not materialise a row (it used to).

        Checked against the declared fields rather than `model_fields_set`, so a client
        that spells out `{"target_grade_id": null}` — which means "no change" here — is
        treated the same as one that omits it.
        """
        return all(getattr(self, name) is None for name in type(self).model_fields)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _disciplines_of_grades(session: Session, grade_ids: set[int]) -> dict[int, Discipline]:
    """Every id's discipline in ONE statement, and the check that each id exists.

    The client sends `grade_id`s and never an ordinal or a label, so this is also where a
    made-up id becomes a 422 instead of a foreign-key error in the middle of the upsert.

    One statement for the whole set rather than one per id: `_decide_grades` needs up to
    three (the incoming target, the incoming current grade, and the stored current grade),
    and three round trips is three helpings of Neon awake time for one question.
    """
    if not grade_ids:
        return {}
    rows = session.execute(
        select(Grade.id, GradeSystem.discipline)
        .join(GradeSystem, Grade.grade_system_id == GradeSystem.id)
        .where(Grade.id.in_(grade_ids))
    ).all()
    found = {row.id: row.discipline for row in rows}
    if set(found) != grade_ids:
        raise _unprocessable(_UNKNOWN_GRADE)
    return found


class _GradeDecision(NamedTuple):
    """What the two grade columns imply for this write.

    `discipline` is `primary_discipline`'s new value, or `None` to leave it alone — it is
    derived from the target grade and is never accepted from a client.

    `clear_current_grade` is the one place this endpoint writes a NULL that the body did not
    ask for, and it is the alternative to a dead end. See `_decide_grades`.
    """

    discipline: Discipline | None
    clear_current_grade: bool


def _decide_grades(session: Session, user_id: int, payload: ProfilePatchRequest) -> _GradeDecision:
    """The target/current grade pair, resolved against each other before anything is written.

    ⚠️ **They must sit on the same DISCIPLINE.** `server/domain/grades.py` bands the ordinal
    ladders per discipline and `convert` raises `CrossDisciplineError` rather than compare
    across them, so "French 7a target, Font 7A current" is a row the plan generator can do
    nothing with. The schema cannot express this — a CHECK cannot follow two foreign keys
    into `grade` — so it is enforced here, at the edge, like every other closed input.
    Two rules, and the asymmetry between them is the point:

    - **an incoming current grade that disagrees is a 422.** The client locks both pickers to
      one scale, so this is a malformed request rather than a user's mistake.
    - **an incoming TARGET grade that disagrees with the STORED current grade clears it.** A
      422 here would be a dead end: a climber who switches from sport to bouldering could
      never change their goal, because the old current grade would refuse every new target.
      Clearing is also exactly what the client does to its own pickers when the scale
      changes, so the two halves agree.

    Costs one extra statement, and only on a body that carries a grade — the wizard's step 1
    and step 3. `None`/`False` short-circuits everything else.
    """
    if payload.target_grade_id is None and payload.current_grade_id is None:
        return _GradeDecision(None, False)

    stored = session.execute(
        select(UserProfile.target_grade_id, UserProfile.current_grade_id).where(
            UserProfile.user_id == user_id
        )
    ).one_or_none()
    stored_target = None if stored is None else stored.target_grade_id
    stored_current = None if stored is None else stored.current_grade_id

    # Whichever target will be in force after this write.
    target_id = payload.target_grade_id if payload.target_grade_id is not None else stored_target
    wanted = {
        grade_id
        for grade_id in (target_id, payload.current_grade_id, stored_current)
        if grade_id is not None
    }
    disciplines = _disciplines_of_grades(session, wanted)
    target_discipline = None if target_id is None else disciplines[target_id]

    if payload.current_grade_id is not None:
        if (
            target_discipline is not None
            and disciplines[payload.current_grade_id] != target_discipline
        ):
            raise _unprocessable(_CROSS_DISCIPLINE_GRADES)
        # `primary_discipline` is only rewritten when the TARGET moved; a current grade says
        # nothing about it.
        return _GradeDecision(
            target_discipline if payload.target_grade_id is not None else None, False
        )

    clear = (
        stored_current is not None
        and target_discipline is not None
        and disciplines[stored_current] != target_discipline
    )
    return _GradeDecision(target_discipline, clear)


_LookupTable = type[ClimbingAspect] | type[InjuryArea]


def _require_known_ids(
    session: Session, table: _LookupTable, ids: set[int], *, detail: str
) -> None:
    """Resolve client-supplied ids against the seeded table before writing anything.

    The foreign keys would catch an unknown id too, but as an `IntegrityError` mid-handler
    — a 500 for what is a client mistake, and one that aborts the transaction so nothing
    else in the request can report a better message. One `SELECT` per collection buys a
    422 that names the vocabulary.
    """
    if not ids:
        return
    known = set(session.scalars(select(table.id).where(table.id.in_(ids))))
    if known != ids:
        raise _unprocessable(detail)


def _validate_references(
    session: Session, user_id: int, payload: ProfilePatchRequest
) -> _GradeDecision:
    """Every lookup id in the body, resolved before the first write. See the docstring.

    Returns what the grade pair implies — the discipline to write, and whether a stored
    current grade has to be cleared because the target moved to the other ladder.
    """
    aspect_ids = {
        aspect_id
        for aspect_id in (payload.strength_aspect_id, payload.weakness_aspect_id)
        if aspect_id is not None
    }
    if payload.aspect_ratings is not None:
        aspect_ids |= {entry.climbing_aspect_id for entry in payload.aspect_ratings}
    _require_known_ids(session, ClimbingAspect, aspect_ids, detail=_UNKNOWN_ASPECT)

    if payload.injuries is not None:
        _require_known_ids(
            session,
            InjuryArea,
            {entry.injury_area_id for entry in payload.injuries},
            detail=_UNKNOWN_INJURY_AREA,
        )

    _require_aspects_differ(session, user_id, payload)
    return _decide_grades(session, user_id, payload)


def _require_aspects_differ(session: Session, user_id: int, payload: ProfilePatchRequest) -> None:
    """The half of "a strength is not a weakness" that the request alone cannot see.

    `ProfilePatchRequest` catches a body carrying both. One arriving alone has to be checked
    against the row, or a two-step client could set strength = Power and then weakness =
    Power and land an `IntegrityError` on the CHECK — a 500 for what is a client mistake.

    Costs one statement, and only when exactly one of the two is in the body.
    """
    incoming = (payload.strength_aspect_id, payload.weakness_aspect_id)
    if incoming.count(None) != 1:
        return
    stored = session.execute(
        select(UserProfile.strength_aspect_id, UserProfile.weakness_aspect_id).where(
            UserProfile.user_id == user_id
        )
    ).one_or_none()
    if stored is None:
        return
    other = (
        stored.weakness_aspect_id
        if payload.strength_aspect_id is not None
        else stored.strength_aspect_id
    )
    if other is not None and other == (payload.strength_aspect_id or payload.weakness_aspect_id):
        raise _unprocessable(_SAME_ASPECT_TWICE)


def _upsert_profile(
    session: Session,
    user_id: int,
    payload: ProfilePatchRequest,
    grades_decision: _GradeDecision,
) -> None:
    """At most ONE statement, writing only the columns the body carried.

    No placeholders: since `0005` the three formerly-`NOT NULL` columns are nullable, so a
    row can exist with only the answers that have actually been given. A body that touches
    none of them writes nothing here — the child tables do not reference `user_profile`, so
    there is no row that needs to exist for their sake.
    """
    columns: dict[str, object] = {}
    if payload.target_grade_id is not None:
        columns["target_grade_id"] = payload.target_grade_id
    if grades_decision.discipline is not None:
        columns["primary_discipline"] = grades_decision.discipline
    if payload.current_grade_id is not None:
        columns["current_grade_id"] = payload.current_grade_id
    # ⚠️ The one NULL this endpoint writes that the body did not ask for: the stored current
    # grade is on the ladder the new target just left. `_decide_grades` explains why this is
    # a clear rather than a 422.
    #
    # `elif`, not `if`: `_decide_grades` only ever asks for this when the body carried no
    # current grade, but writing the two as independent statements would make the outcome
    # depend on dict-insertion order if that ever changed. Same key, one decision.
    elif grades_decision.clear_current_grade:
        columns["current_grade_id"] = None
    if payload.sessions_per_week is not None:
        columns["sessions_per_week"] = payload.sessions_per_week
    if payload.available_weekdays is not None:
        columns["available_weekdays"] = payload.available_weekdays
    if payload.strength_aspect_id is not None:
        columns["strength_aspect_id"] = payload.strength_aspect_id
    if payload.weakness_aspect_id is not None:
        columns["weakness_aspect_id"] = payload.weakness_aspect_id
    if payload.display_name is not None:
        columns["display_name"] = payload.display_name
    if payload.show_body_metrics is not None:
        columns["show_body_metrics"] = payload.show_body_metrics
    # Stamped for a list with rows AND for an empty one — the step was answered either
    # way, and this column is the only record that it was.
    if payload.injuries is not None:
        columns["injuries_reviewed_at"] = func.now()

    if not columns:
        return

    # ONE dict, not `values(user_id=…, **columns)`: keyword-splatting an overlapping key is
    # a `TypeError` at call time, i.e. a 500 on every request that sends one.
    statement = pg_insert(UserProfile).values({"user_id": user_id, **columns})
    # `updated_at` has a server default but no `onupdate`, so it is set here.
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id"], set_={**columns, "updated_at": func.now()}
        )
    )


def _replace_aspect_ratings(session: Session, user_id: int, ratings: list[AspectRatingIn]) -> None:
    by_aspect = {entry.climbing_aspect_id: entry.score for entry in ratings}

    stale = delete(UserAspectRating).where(UserAspectRating.user_id == user_id)
    if by_aspect:
        stale = stale.where(UserAspectRating.climbing_aspect_id.not_in(by_aspect))
    session.execute(stale)

    if by_aspect:
        statement = pg_insert(UserAspectRating).values(
            [
                {"user_id": user_id, "climbing_aspect_id": aspect_id, "score": score}
                for aspect_id, score in sorted(by_aspect.items())
            ]
        )
        # `rated_at` moves on every submission, including a re-submission of the same
        # score: the question it answers is "how old is this self-assessment?".
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "climbing_aspect_id"],
                set_={"score": statement.excluded.score, "rated_at": func.now()},
            )
        )


def _flag_open_injuries(session: Session, user_id: int, injuries: list[InjuryIn]) -> None:
    """The submitted list becomes the set of OPEN injuries. Nothing is deleted.

    An area that drops off the list is **resolved**, not removed: "resolved in March" is
    information the plan generator uses to reintroduce the exercises it was withholding,
    and a flag that gets flipped back loses it (`UserInjury`'s docstring).

    **One to three statements, whatever the list length** — one for `{"injuries": []}`,
    which is the commonest body there is. `ON CONFLICT` can infer the partial unique index
    added in `0005`, so inserting a new flag and updating an existing one are the same
    statement — which is also what makes two concurrent requests safe: the
    loser of the race updates instead of inserting a second open row. The split into two
    inserts is the omitted-vs-null note rule: the group that sent a note may overwrite one,
    the group that did not must not.
    """
    submitted = {entry.injury_area_id: entry for entry in injuries}

    # One statement, unconditional: resolving nothing is a no-op, and checking first would
    # cost a round trip to save a cheap UPDATE. `current_date` is the DATABASE's clock —
    # a serverless function's is not the one every other timestamp here comes from.
    resolve = update(UserInjury).where(
        UserInjury.user_id == user_id, UserInjury.resolved_on.is_(None)
    )
    if submitted:
        resolve = resolve.where(UserInjury.injury_area_id.not_in(submitted))
    session.execute(resolve.values(resolved_on=func.current_date()))

    for note_was_sent in (True, False):
        rows = [
            {
                "user_id": user_id,
                "injury_area_id": entry.injury_area_id,
                "note": entry.note,
                "started_on": func.current_date(),
            }
            for entry in sorted(submitted.values(), key=lambda item: item.injury_area_id)
            if entry.note_was_sent is note_was_sent
        ]
        if not rows:
            continue
        statement = pg_insert(UserInjury).values(rows)
        # `started_on` is deliberately NOT in either `set_`: re-submitting a flag must not
        # restart the clock on an injury the user has had for three weeks.
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "injury_area_id"],
                index_where=_OPEN_INJURY,
                set_={"note": statement.excluded.note},
            )
            if note_was_sent
            else statement.on_conflict_do_nothing(
                index_elements=["user_id", "injury_area_id"],
                index_where=_OPEN_INJURY,
            )
        )


def _read_profile(session: Session, user_id: int) -> ProfileResponse:
    """Four statements, no lazy loading, and no write on the read path.

    A missing row is reported as all-nulls rather than as a 404 or a null object: every
    caller wants "what is set so far", and there is no difference between a profile that
    does not exist and one that has answered nothing.

    ⚠️ A `select`, not `session.get`. `_upsert_profile` writes through Core, which does not
    update the ORM's identity map — so `get` may answer a read that follows an upsert in the
    same transaction with the row as it was BEFORE the write. Every read here is a Core
    select for the same reason.
    """
    row = session.execute(
        select(
            UserProfile.display_name,
            UserProfile.target_grade_id,
            UserProfile.current_grade_id,
            UserProfile.primary_discipline,
            UserProfile.sessions_per_week,
            UserProfile.available_weekdays,
            UserProfile.strength_aspect_id,
            UserProfile.weakness_aspect_id,
            UserProfile.show_body_metrics,
            UserProfile.injuries_reviewed_at,
        ).where(UserProfile.user_id == user_id)
    ).one_or_none()
    # Deliberately a separate statement rather than a join. Selecting `app_user` LEFT JOIN
    # `user_profile` would make `row` never None, and `row is None` is what ten lines below
    # read to mean "nothing answered yet" — a shape worth more than one round trip on a
    # connection that is already awake for the other three. It replaced the `user_equipment`
    # select that issue #54 retired, so the count is unchanged.
    email = session.scalar(select(AppUser.email).where(AppUser.id == user_id))
    ratings = session.execute(
        select(
            UserAspectRating.climbing_aspect_id,
            UserAspectRating.score,
            UserAspectRating.rated_at,
        )
        .where(UserAspectRating.user_id == user_id)
        .order_by(UserAspectRating.climbing_aspect_id)
    ).all()
    injuries = session.execute(
        select(UserInjury.injury_area_id, UserInjury.note, UserInjury.started_on)
        .where(UserInjury.user_id == user_id, UserInjury.resolved_on.is_(None))
        .order_by(UserInjury.injury_area_id)
    ).all()

    return ProfileResponse(
        email=email,
        display_name=None if row is None else row.display_name,
        target_grade_id=None if row is None else row.target_grade_id,
        current_grade_id=None if row is None else row.current_grade_id,
        primary_discipline=None if row is None else row.primary_discipline,
        sessions_per_week=None if row is None else row.sessions_per_week,
        available_weekdays=None if row is None else row.available_weekdays,
        strength_aspect_id=None if row is None else row.strength_aspect_id,
        weakness_aspect_id=None if row is None else row.weakness_aspect_id,
        # The one non-null field: `show_body_metrics` has a server default of TRUE and is
        # a setting rather than an answer, so a missing row reports the default it would
        # be created with.
        show_body_metrics=True if row is None else row.show_body_metrics,
        injuries_reviewed_at=None if row is None else row.injuries_reviewed_at,
        aspect_ratings=[
            AspectRatingOut(
                climbing_aspect_id=entry.climbing_aspect_id,
                score=entry.score,
                rated_at=entry.rated_at,
            )
            for entry in ratings
        ],
        injuries=[
            InjuryOut(
                injury_area_id=entry.injury_area_id,
                note=entry.note,
                started_on=entry.started_on,
            )
            for entry in injuries
        ],
    )


@router.get("")
def read_profile(principal: CurrentUser, session: RequestSession) -> ProfileResponse:
    """The authenticated user's profile. Reads only — nothing is created on a GET.

    A touch-on-read write is the classic accident that defeats every other compute rule
    in CLAUDE.md, and "create the row when it is first read" is exactly that.
    """
    return _read_profile(session, principal.user_id)


@router.patch("")
def patch_profile(
    payload: ProfilePatchRequest, principal: CurrentUser, session: RequestSession
) -> ProfileResponse:
    """Upsert any subset of the profile and return the whole of it.

    A **Tier-1 write** (CLAUDE.md, "Two write tiers"): a profile change is deliberate and
    low-frequency, so it goes through immediately rather than into the outbox.

    Order matters and is not incidental: **every reference in the body is resolved before
    the first write**, so a 422 leaves nothing behind. The full profile comes back so the
    caller never needs a follow-up GET to redraw the completion bar, and so the bar can
    never disagree with the database about what is set.
    """
    user_id = principal.user_id

    if payload.is_empty():
        # Nothing was sent, so nothing is written — not even an empty row. This is a read
        # in PATCH's clothing, and it must not be the thing that creates a profile.
        return _read_profile(session, user_id)

    grades_decision = _validate_references(session, user_id, payload)

    _upsert_profile(session, user_id, payload, grades_decision)
    if payload.aspect_ratings is not None:
        _replace_aspect_ratings(session, user_id, payload.aspect_ratings)
    if payload.injuries is not None:
        _flag_open_injuries(session, user_id, payload.injuries)

    # Read inside the transaction that wrote, then commit: the response is what the
    # database now holds, and it costs no second connection.
    profile = _read_profile(session, user_id)
    session.commit()
    return profile


# Every column the four onboarding steps own, and nothing else. Named rather than inlined so
# the endpoint's docstring and the statement cannot drift apart.
#
# ⚠️ `display_name` and `show_body_metrics` are NOT here: neither is one of the four steps.
# A reset walks the setup flow again; it is not an account wipe. `equipment_reviewed_at` is
# not here either — it is retired (see `server/models.py`), and writing to a column nothing
# reads would be the reset pretending to do something.
_RESET_COLUMNS: Final = (
    "target_grade_id",
    "current_grade_id",
    "primary_discipline",
    "sessions_per_week",
    "available_weekdays",
    "strength_aspect_id",
    "weakness_aspect_id",
    "injuries_reviewed_at",
)


@router.post("/reset")
def reset_profile(principal: CurrentUser, session: RequestSession) -> ProfileResponse:
    """Un-answer the four onboarding steps, in one transaction, and return the profile.

    ## Why this exists instead of teaching `PATCH` to clear

    Issue #54 needs a way back to a from-scratch wizard. The obvious alternative was to make
    `null` mean "clear" in `ProfilePatchRequest` — and that was **considered and rejected**
    (Kilian's call): `null` there means "not in this request" for every field, which is what
    lets onboarding send one step at a time, and flipping it would turn every omission into a
    destructive spelling one typo away. A named endpoint says what it does.

    ## What it clears, and what it deliberately does not

    - **Every column the four steps own** (`_RESET_COLUMNS`), back to NULL — including
      `primary_discipline`, which is derived from the target grade and has to go with it.
    - **Every `user_aspect_rating` row**, because the aspect step's answer *is* those rows.
    - **Open `user_injury` rows only.** ⚠️ Resolved rows are HISTORY and are not touched:
      flag -> resolve -> re-flag is what that table exists for (`0005`'s partial unique
      index), and a reset is not a claim about a past injury. An open flag, by contrast, is
      the step's current answer and has to go or the step would not read as unanswered.
    - **Not** `display_name`, `show_body_metrics`, or anything in `user_equipment` — see
      `_RESET_COLUMNS`.

    ## Shape

    A **Tier-1 write**, like `PATCH`: deliberate, low-frequency, and the user is waiting for
    it. It returns the whole profile for the same reason `PATCH` does — the caller redraws
    the completion bar from the response rather than from a follow-up GET, so the bar can
    never disagree with the database about what is set.

    **Idempotent**, and it does not create a row: `UPDATE` touches nothing when no profile
    exists, and a profile that has answered nothing is what a reset is trying to produce
    anyway. A demo token never reaches here — `POST` is a mutating method, so
    `server/auth/deps.py` refuses it twice over (403 at the edge, read-only transaction
    underneath).
    """
    user_id = principal.user_id

    # ⚠️ ONE dict, not a dict plus `updated_at=…`: SQLAlchemy raises
    # `ArgumentError: Can't pass positional and kwargs to values() simultaneously`, which
    # would be a 500 on every call. Verified against the installed
    # `sqlalchemy/sql/dml.py::values` rather than assumed.
    session.execute(
        update(UserProfile)
        .where(UserProfile.user_id == user_id)
        .values({**{column: None for column in _RESET_COLUMNS}, "updated_at": func.now()})
    )
    session.execute(delete(UserAspectRating).where(UserAspectRating.user_id == user_id))
    session.execute(
        delete(UserInjury).where(UserInjury.user_id == user_id, UserInjury.resolved_on.is_(None))
    )

    profile = _read_profile(session, user_id)
    session.commit()
    return profile
