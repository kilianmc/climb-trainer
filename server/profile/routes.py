"""The `/api/profile` endpoints: read the whole profile, patch any part of it.

## The write endpoint takes a PARTIAL profile, and that is load-bearing

Onboarding is five steps and **each one persists as it completes**, so an abandoned
onboarding resumes rather than restarting (the plan's Zeigarnik point). The row is
therefore created on step 1, not step 5, and every later step is an update to a row that
already exists. One endpoint does both: `PATCH` upserts, and any field left out of the
body is left alone.

**`None` means "not in this request" for every scalar field**, and there is deliberately
no way to clear one back to nothing: no screen offers it, and a second meaning for `null`
would be a second code path nothing exercises. The three collection fields
(`equipment_ids`, `aspect_ratings`, `injuries`) are different — a list **replaces** the
set it names, and `[]` is a real answer.

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
`0005`, so a row created on step 1 had to carry invented values for questions steps 2 and 4
had not asked yet. `sessions_per_week = 3` is a perfectly plausible answer, so the
completion bar credited work nobody had done and the plan generator would have read a
number the user never chose. Now:

- **The endpoint writes only the columns the body carried.** An empty body writes nothing
  at all — not even a row — because there is nothing to record.
- **`primary_discipline` is DERIVED from the target grade**, never sent by the client. The
  grade ladder is banded per discipline (`server/domain/grades.py`), so a French 7a target
  *is* a rope goal; accepting a separate field would let the two disagree, and the
  disagreement would only surface in the plan generator.
- **`equipment_reviewed_at` and `injuries_reviewed_at` are stamped whenever their step is
  submitted**, with or without rows. **A step needs a `*_reviewed_at` column exactly when
  zero rows is a legitimate answer** — "I own none of this" and "nothing is hurting" both
  write no child rows, so an empty table cannot distinguish "asked, nothing" from "never
  asked". The other three steps must not get one: the aspect step always writes eight rows,
  and the target grade and availability are scalar columns whose NULL carries it.

## Every id is resolved BEFORE anything is written

Not for tidiness: `_upsert_profile` runs first, so a bad equipment id rejected later would
leave a row behind in any transaction that is not rolled back. Validation of every
reference in the body happens up front, so a 422 means nothing was written.

## Every query is scoped by the token's `user_id`

Never a path parameter, never a body field. IDOR is the realistic extraction risk in this
product (`server/auth/deps.py`), and a profile row is keyed by exactly the id an attacker
would want to substitute.
"""

from datetime import date, datetime
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from server.auth.deps import CurrentUser, RequestSession
from server.domain.grades import Discipline
from server.domain.vocabulary import CLIMBING_ASPECTS, EQUIPMENT, INJURY_AREAS
from server.fields import (
    AspectScore,
    AvailableWeekdays,
    InjuryNote,
    LookupId,
    SessionsPerWeek,
)
from server.models import (
    ClimbingAspect,
    Equipment,
    Grade,
    GradeSystem,
    InjuryArea,
    UserAspectRating,
    UserEquipment,
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
_UNKNOWN_EQUIPMENT: Final = "That equipment is not in the catalogue."
_UNKNOWN_ASPECT: Final = "That climbing aspect does not exist."
_UNKNOWN_INJURY_AREA: Final = "That injury area does not exist."


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

    The two `*_reviewed_at` fields are how their steps report themselves finished: an empty
    `equipment_ids` or `injuries` list means "nothing to record" or "never asked" depending
    only on them. Every completion test the client makes reads one of these or a scalar,
    which is what keeps the progress bar server truth.
    """

    target_grade_id: int | None
    primary_discipline: Discipline | None
    sessions_per_week: int | None
    available_weekdays: int | None
    show_body_metrics: bool
    equipment_reviewed_at: datetime | None
    injuries_reviewed_at: datetime | None
    equipment_ids: list[int]
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
    """

    model_config = ConfigDict(extra="forbid")

    target_grade_id: LookupId | None = None
    sessions_per_week: SessionsPerWeek | None = None
    available_weekdays: AvailableWeekdays | None = None
    show_body_metrics: bool | None = None

    # Each list REPLACES the set it names, and is bounded by the size of the vocabulary it
    # draws from — an unbounded list is a resource-exhaustion vector even when every id
    # in it is valid.
    equipment_ids: Annotated[list[LookupId], Field(max_length=len(EQUIPMENT))] | None = None
    aspect_ratings: (
        Annotated[list[AspectRatingIn], Field(max_length=len(CLIMBING_ASPECTS))] | None
    ) = None
    injuries: Annotated[list[InjuryIn], Field(max_length=len(INJURY_AREAS))] | None = None

    @field_validator("equipment_ids")
    @classmethod
    def _equipment_ids_are_unique(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("equipment ids must be unique")
        return value

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

    def is_empty(self) -> bool:
        """Nothing to write. A body like `{}` must not materialise a row (it used to).

        Checked against the declared fields rather than `model_fields_set`, so a client
        that spells out `{"target_grade_id": null}` — which means "no change" here — is
        treated the same as one that omits it.
        """
        return all(getattr(self, name) is None for name in type(self).model_fields)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _discipline_of_grade(session: Session, grade_id: int) -> Discipline:
    """The discipline a target grade implies, and the check that the grade exists.

    One statement. The client sends a `grade_id` and never an ordinal or a label, so this
    is also where a made-up id is turned into a 422 instead of a foreign-key error in the
    middle of the upsert.
    """
    discipline = session.scalar(
        select(GradeSystem.discipline)
        .join(Grade, Grade.grade_system_id == GradeSystem.id)
        .where(Grade.id == grade_id)
    )
    if discipline is None:
        raise _unprocessable(_UNKNOWN_GRADE)
    return discipline


_LookupTable = type[ClimbingAspect] | type[Equipment] | type[InjuryArea]


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


def _validate_references(session: Session, payload: ProfilePatchRequest) -> Discipline | None:
    """Every lookup id in the body, resolved before the first write. See the docstring.

    Returns the discipline the target grade implies, or `None` when the body carried no
    target grade.
    """
    if payload.equipment_ids is not None:
        _require_known_ids(
            session, Equipment, set(payload.equipment_ids), detail=_UNKNOWN_EQUIPMENT
        )
    if payload.aspect_ratings is not None:
        _require_known_ids(
            session,
            ClimbingAspect,
            {entry.climbing_aspect_id for entry in payload.aspect_ratings},
            detail=_UNKNOWN_ASPECT,
        )
    if payload.injuries is not None:
        _require_known_ids(
            session,
            InjuryArea,
            {entry.injury_area_id for entry in payload.injuries},
            detail=_UNKNOWN_INJURY_AREA,
        )
    if payload.target_grade_id is None:
        return None
    return _discipline_of_grade(session, payload.target_grade_id)


def _upsert_profile(
    session: Session,
    user_id: int,
    payload: ProfilePatchRequest,
    discipline: Discipline | None,
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
    if discipline is not None:
        columns["primary_discipline"] = discipline
    if payload.sessions_per_week is not None:
        columns["sessions_per_week"] = payload.sessions_per_week
    if payload.available_weekdays is not None:
        columns["available_weekdays"] = payload.available_weekdays
    if payload.show_body_metrics is not None:
        columns["show_body_metrics"] = payload.show_body_metrics
    # Stamped for a list with rows AND for an empty one — the step was answered either
    # way, and these columns are the only record that it was.
    if payload.equipment_ids is not None:
        columns["equipment_reviewed_at"] = func.now()
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


def _replace_equipment(session: Session, user_id: int, equipment_ids: list[int]) -> None:
    ids = set(equipment_ids)

    stale = delete(UserEquipment).where(UserEquipment.user_id == user_id)
    if ids:
        stale = stale.where(UserEquipment.equipment_id.not_in(ids))
    session.execute(stale)

    if ids:
        session.execute(
            pg_insert(UserEquipment)
            .values([{"user_id": user_id, "equipment_id": row_id} for row_id in sorted(ids)])
            .on_conflict_do_nothing(index_elements=["user_id", "equipment_id"])
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
            UserProfile.target_grade_id,
            UserProfile.primary_discipline,
            UserProfile.sessions_per_week,
            UserProfile.available_weekdays,
            UserProfile.show_body_metrics,
            UserProfile.equipment_reviewed_at,
            UserProfile.injuries_reviewed_at,
        ).where(UserProfile.user_id == user_id)
    ).one_or_none()
    equipment_ids = list(
        session.scalars(
            select(UserEquipment.equipment_id)
            .where(UserEquipment.user_id == user_id)
            .order_by(UserEquipment.equipment_id)
        )
    )
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
        target_grade_id=None if row is None else row.target_grade_id,
        primary_discipline=None if row is None else row.primary_discipline,
        sessions_per_week=None if row is None else row.sessions_per_week,
        available_weekdays=None if row is None else row.available_weekdays,
        # The one non-null field: `show_body_metrics` has a server default of TRUE and is
        # a setting rather than an answer, so a missing row reports the default it would
        # be created with.
        show_body_metrics=True if row is None else row.show_body_metrics,
        equipment_reviewed_at=None if row is None else row.equipment_reviewed_at,
        injuries_reviewed_at=None if row is None else row.injuries_reviewed_at,
        equipment_ids=equipment_ids,
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

    discipline = _validate_references(session, payload)

    _upsert_profile(session, user_id, payload, discipline)
    if payload.equipment_ids is not None:
        _replace_equipment(session, user_id, payload.equipment_ids)
    if payload.aspect_ratings is not None:
        _replace_aspect_ratings(session, user_id, payload.aspect_ratings)
    if payload.injuries is not None:
        _flag_open_injuries(session, user_id, payload.injuries)

    # Read inside the transaction that wrote, then commit: the response is what the
    # database now holds, and it costs no second connection.
    profile = _read_profile(session, user_id)
    session.commit()
    return profile
