"""`/api/plans` — preview a generated plan, persist it, read it back, stand it down.

## Four routes, and the split between them

`POST /preview` builds the plan the generator would build and **writes nothing** (PR #11a).
`POST ""` (PR #11b) regenerates the same tree from the same profile and **persists it,
activated, standing the previously active plan down in the same transaction**. `GET /active`
reads it back — without which a persisted plan is invisible after a reload — and
`POST /{plan_id}/abandon` stands one down.

⚠️ **`/preview` is the ONLY one of the four in `DEMO_WRITE_EXEMPT_ROUTES`**, because it is
the only one that writes nothing. The other three are ordinary mutating routes and are
refused for a demo principal twice over: `enforce_auth` 403s a demo-scope token on every
`POST`, and `get_request_session` has additionally issued `SET LOCAL transaction_read_only`.
Neither needed a line of code here, and adding an exemption entry would remove both.

## Why a POST for a read

`GET` is the honest verb and it is the wrong one here. A per-user body on a cacheable verb
is exactly the `/api/library` CDN trap read backwards: that endpoint is `public, immutable`
*because* its body is identical for everyone, and this one is assembled from one climber's
grades, availability, declared weakness and open injuries. `POST` is not cached by default,
so the safe thing is the default thing. The cost is one `DEMO_WRITE_EXEMPT_ROUTES` entry,
justified at that constant (Kilian's decision 7, 2026-08-24).

## Where the inputs come from

Exactly one field is the client's: `start_date`. The client knows the timezone and the
domain has no clock, so the choice of "which Monday" is the caller's — and it is the ONLY
thing the caller may choose. Everything else is read here, scoped by the user id **from the
token**: `server/auth/deps.py` exposes the principal and there is deliberately no way to
name a user in a path, a body or a query, because a single unscoped read hands over
somebody's training history.

## Four refusals are raised HERE, and two are raised by the domain

An unanswered profile column has no representation in a plannable `PlannerInput`, and
CLAUDE.md forbids substituting a default for one (`sessions_per_week = 3` is a perfectly
plausible reply, which is what makes an invented one dangerous). So the four NULL cases are
detected where the row is read, and the two that are properties of the *values* —
cross-ladder grades, an empty weekday mask — are raised inside the domain. All six live in
one `RefusalReason`, so the HTTP mapping is one `except CannotPlanError` at one call site,
and every sentence comes from `REFUSAL_MESSAGES`: the wording a user sees when the app
declines to do its main job is written once and quoted, never re-inlined.

## Pydantic here, dataclasses in the domain

A hand-written mapper per node, the same stitching `server/library/routes.py` does. The
domain gains no dependency on FastAPI, and the wire shape stays in one file a reviewer can
read whole. The return-type annotation IS the response model — `response_model=` is used
nowhere in this repo.

## ONE set of response models, two mappers

`PlanOut` and its children serve all four routes. A previewed plan and a persisted plan are
the same tree with the same field names and the same meanings; what differs is that a
preview is not a row, so every `id` (plus a block's `exercise_id`, a session's `status` and
the plan's `activated_at`) is `null`. There are two mapper families because there are two
sources — `_*_out` from the domain's blueprint, `_persisted_*` from the ORM rows — and one
model family because there is one client renderer. Round 1 of #11b had two of each; the
second renderer is where the two would have drifted.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from server.auth.deps import CurrentUser, RequestSession
from server.domain.grades import Discipline
from server.domain.planner import (
    GENERATOR_VERSION,
    BlockBlueprint,
    CannotPlanError,
    MesocycleBlueprint,
    MicrocycleBlueprint,
    NoteKind,
    PlanBlueprint,
    PlannerInput,
    RefusalReason,
    ScheduleNote,
    SessionBlueprint,
    SetBlueprint,
    Shortfall,
    generate,
    generator_input,
)
from server.domain.planner.schedule import week_start_on_or_after
from server.domain.vocabulary import (
    EQUIPMENT,
    ActivityKind,
    Phase,
    ProtocolKind,
    SessionStatus,
)
from server.models import (
    ClimbingAspect,
    Exercise,
    Grade,
    InjuryArea,
    Mesocycle,
    Microcycle,
    Plan,
    PlannedSession,
    PrescribedSet,
    SessionBlock,
    UserInjury,
    UserProfile,
)

router = APIRouter(prefix="/api/plans", tags=["plans"])

# ⚠️ Nothing user-supplied is ever an argument to this logger. See `create_plan`'s
# `IntegrityError` branch for the rule and for the incident behind it.
_logger = logging.getLogger(__name__)

# ⚠️ `private, no-store`. The never-cached sibling `server/library/routes.py` anticipated,
# and the reason the two rules differ is the whole point of having both.
#
# `/api/library` is `public, s-maxage=31536000, immutable` because its body is identical for
# every user. This body is assembled from ONE climber's grades, availability, declared
# weakness and **open injuries** — so a shared-cache entry would hand a stranger a picture
# of somebody's injuries, and no behavioural test could see it happen. `private` forbids the
# CDN; `no-store` also keeps it off the browser's disk, the same argument that keeps
# `runtimeCaching` off `/api` in the service worker (authenticated JSON in Cache Storage is
# not scoped to a session and survives logout).
#
# `POST` is already uncached by default, so this header is defence in depth rather than the
# mechanism — written down because the verb was chosen FOR that property, and a later "make
# it a GET so it caches" would remove the property while this header quietly kept working.
_CACHE_CONTROL: Final = "private, no-store"

# How far either side of today's UTC date a client may place a start.
#
# ⚠️ Deliberately NOT in `server/fields.py`. That file holds one bounded type per persisted
# CHECK, and this mirrors none: `plan.start_date` has no CHECK at all. It has exactly one
# caller, and it is a request-sanity bound rather than a schema fact — a plan starting in
# 2075 is a client bug, and a plan starting in 2019 is a client bug. Promoting it would put
# a rule with no database behind it in the file whose whole discipline is that every entry
# has one.
#
# A week behind, because a client in UTC-11 legitimately calls this on what the server still
# calls yesterday, and because "start the plan from last Monday" is a real thing to ask for.
_START_DATE_BACKDATE_DAYS: Final = 7
_START_DATE_HORIZON_DAYS: Final = 365

# ⚠️ The full 17-row vocabulary, and this is Kilian's decision 3 (2026-08-24), not an
# oversight.
#
# Every real user has **zero** `user_equipment` rows: issue #54 deleted the onboarding step
# that wrote them, and CLAUDE.md's replacement model is "assume access to everything" —
# somebody with gym access has most of the list, and enumerating gear was the wrong
# question. Reading `user_equipment` here would therefore hand the generator an empty set
# for everyone and thin every plan to its bodyweight options, which is precisely the
# outcome decision 1 exists to prevent.
#
# The DOMAIN still takes the set as a parameter and is tested against `()`, so the
# gearless-shortfall machinery is real and lights up the day the "I don't have access to
# this" flag lands. **When it does, this constant is the ONE line that changes** — it
# becomes the vocabulary minus what the user flagged. It is behind a name for exactly that
# reason.
_ASSUMED_EQUIPMENT_KEYS: Final[tuple[str, ...]] = tuple(sorted(spec.key for spec in EQUIPMENT))


# The partial unique index from `0008`. Named here so the 409 branch below matches on a
# constant rather than on a substring of a driver message.
_ONE_ACTIVE_INDEX: Final = "uq_plan_one_active_per_user"


def _today_utc() -> date:
    """The server's own date. The domain may not ask this question; this module may."""
    return datetime.now(UTC).date()


def _now_utc() -> datetime:
    """One instant per request, used for every timestamp the request writes.

    ⚠️ A Python value rather than `func.now()`, deliberately, and it is not the house
    default — `server/profile/routes.py::patch_profile` writes `updated_at=func.now()`. It
    can, because it re-reads the row it wrote before committing. This module's `POST` builds
    its response from the ORM objects it just inserted, and a column set to a SQL function
    is not readable from those objects without a per-row refresh — 200+ extra round trips
    against a metered database, to learn a timestamp we already know.

    Called once and passed down, so the plan being stood down and the plan being activated
    carry the same instant and the handover has no gap and no overlap.
    """
    return datetime.now(UTC)


class PlanPreviewRequest(BaseModel):
    """One field, and `extra="forbid"` so a probing or typo'd field is a 422, never silence.

    `start_date` is optional: omitted means "the Monday on or after today, UTC". The server
    normalises whatever it is given the same way, so the two paths cannot disagree — which
    also means a Monday is returned unchanged and today counts as "on or after today".
    """

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None

    @field_validator("start_date")
    @classmethod
    def _a_bounded_monday(cls, value: date | None) -> date | None:
        """Bound what was asked for, then normalise it forward to a Monday.

        The order matters and is deliberate: the bound is a judgement about the client's
        request, so it is applied to the client's value. Normalising then moves the start up
        to six days later, which can carry it past the horizon — that is the server's own
        doing and is not a request to refuse.

        `week_start_on_or_after` is the domain's, so the edge and the generator's own date
        maths cannot drift apart; `PlannerInput` re-asserts the Monday because an off-by-one
        here would move every session in the plan.
        """
        if value is None:
            return None
        today = _today_utc()
        if not (
            today - timedelta(days=_START_DATE_BACKDATE_DAYS)
            <= value
            <= today + timedelta(days=_START_DATE_HORIZON_DAYS)
        ):
            raise ValueError(
                f"start_date must be no more than {_START_DATE_BACKDATE_DAYS} days in the "
                f"past and no more than {_START_DATE_HORIZON_DAYS} days ahead"
            )
        return week_start_on_or_after(value)


# ---------------------------------------------------------------------------------
# ONE wire shape for a plan, previewed or persisted
# ---------------------------------------------------------------------------------
#
# ⚠️ These models serve BOTH `/preview` and the persisted routes, and that is the point:
# `web/src/routes/_authed/plan.lazy.tsx` renders one tree with one renderer. Round 1 of
# #11b shipped a parallel `Persisted*Out` hierarchy and it is gone — see the banner above
# `_StoredCaveats` for what each of the four missing fields turned out to be reachable from.
#
# What differs between a preview and a persisted plan is **which nullable fields are
# filled, and that is a single rule**: a preview is not a row, so everything only a row has
# is `null` — every `id`, a block's `exercise_id`, a session's `status`, the plan's
# `activated_at`. A persisted plan fills all of them. Nothing else differs; every other
# field has the same name and the same meaning on both paths.
#
# A nullable `id` rather than two model families is a real trade — it lets a client forget
# to check — and it is the cheaper one: the alternative was a second renderer for the same
# tree, and a second renderer is where the two drift.


class SetOut(BaseModel):
    """One prescribed set, straight off the `(exercise, phase)` prescription template.

    `target_load_kg` and `target_grade_id` are present and always `null` in v1.0.0, so the
    wire shape is stable when they are filled. Deriving a load is the one place a bodyweight
    figure could creep into a plan, which CLAUDE.md's weight rule forbids outright.

    The id is the point of the persisted response: the session player logs a `logged_set`
    against `prescribed_set.id`, so a client that had to re-fetch to learn it would need a
    second round trip before the user could start.
    """

    id: int | None = None
    set_index: int
    target_reps: int | None
    target_work_seconds: int | None
    target_rest_seconds: int | None
    target_intensity_pct: int | None
    target_rpe: int | None
    target_load_kg: Decimal | None
    target_grade_id: int | None


class ShortfallOut(BaseModel):
    """An aspect this phase cannot train with the gear assumed, and what would unlock it.

    `options` is an OR of AND sets: each inner list is a combination that would fill the
    cell. Never a gate — the plan is complete and nothing is disabled.
    """

    phase: Phase
    aspect_key: str
    options: list[list[str]]
    message: str


class BlockOut(BaseModel):
    """One block of a session.

    ⚠️ **`exercise_key` AND `exercise_id`, not one or the other.** The domain is DB-free and
    speaks keys, so a preview has the key and no id; a persisted block holds the id, and the
    key is derived from it (`_exercise_reference`). Carrying both means the client's library
    lookup is written once for both paths — dropping the key on the persisted path was what
    forced round 1 towards a second renderer.

    `aspect_key` is the aspect of the exercise that actually landed here, derived on the
    persisted path from `exercise.climbing_aspect_id`. ⚠️ It is **not** the same aspect as
    `shortfall.aspect_key`, which names the aspect the generator *wanted* and could not
    fill — that is precisely why a block's shortfall cannot be derived and has to be stored.
    """

    id: int | None = None
    order_index: int
    exercise_key: str
    exercise_id: int | None = None
    aspect_key: str
    protocol_kind: ProtocolKind
    rest_after_seconds: int | None
    rest_between_sets_seconds: int | None
    sets: list[SetOut]
    shortfall: ShortfallOut | None


class SessionOut(BaseModel):
    """One planned session. `estimated_minutes` is `null` for a session with no blocks.

    `status` is `null` on a preview and real on a persisted session: a preview has no
    lifecycle, and inventing `planned` for it would make "not a row yet" and "a row nobody
    has started" the same answer.

    `shortfalls` here are the slots that produced **no block at all** — the terminal
    injury/gear case. They are stored, not derived: nothing in the tree records a slot that
    was never filled.
    """

    id: int | None = None
    weekday: int
    scheduled_on: date
    activity_kind: ActivityKind
    status: SessionStatus | None = None
    title: str
    estimated_minutes: int | None
    blocks: list[BlockOut]
    shortfalls: list[ShortfallOut]


class MicrocycleOut(BaseModel):
    """One week. `is_deload` is exactly `phase is Phase.DELOAD`; a taper is known by `phase`.

    `phase` is carried even though `microcycle` has no phase column: it is read off the
    parent mesocycle, which the serialiser is walking anyway.
    """

    id: int | None = None
    week_no: int
    start_date: date
    is_deload: bool
    phase: Phase
    sessions: list[SessionOut]


class MesocycleOut(BaseModel):
    """One phase block, `start_week`..`end_week` inclusive and 1-based.

    Not in the plan document's list of nested models, which named only the microcycle and
    below while listing `mesocycles[]` on the response — `mesocycle_spans` has to arrive as
    something, and flattening the tree would drop the phase spans the `/plan` timeline draws.
    """

    id: int | None = None
    phase: Phase
    start_week: int
    end_week: int
    microcycles: list[MicrocycleOut]


class NoteOut(BaseModel):
    """One honest caveat about the plan as a whole. `kind` is the contract, `message` is copy."""

    kind: NoteKind
    message: str


class PlanOut(BaseModel):
    """A whole plan — previewed or persisted — plus what would be needed to reproduce it.

    `generator_input` is the canonical JSON of the `PlannerInput` actually used, plus
    `generator_version` and `library_digest`. That digest is load-bearing:
    `server/models.py::Plan` promises that re-running a version on the same input reproduces
    the tree, and **the library is a third input** — without it the promise is false the
    first time content is edited, and the failure is silent.

    ⚠️ `target_grade_id` and `current_grade_id` are set by this MODULE and are always `None`
    on the blueprint: `PlannerInput` carries ordinals, so the domain never sees a `grade.id`.
    Both are real columns on `plan`, so both survive a reload (`0008`) — the profile's
    current grade drifts as the climber improves and nothing else recovers what the plan was
    built from.

    `grade_gap` is derived on the persisted path rather than stored; see `_grade_gap`.

    ⚠️ **The measured PERSISTED worst case** (re-measured 2026-08-26; boulder, 12-ordinal
    gap, 7 sessions/week, full weekday mask, all 17 equipment, weakness `technique`): 32
    weeks / 224 sessions / 672 blocks / **2,472 sets / 640.7 KiB compact raw / 33.3 KiB
    gzip -6**. Raw size is the *same* as the preview's for the same tree — every filled `id`
    replaces a `null`, which costs about the same four bytes — but **gzipped it is ~1.9x**
    (17.6 KiB previewed), because 2,472 repeated `null`s compress away and 2,472 distinct
    integers do not. So the persisted response is the one to size against. One request
    rather than create-then-fetch is the point; if it ever bites, the lever is trimming sets
    beyond the first N weeks, not splitting the endpoint.
    """

    id: int | None = None
    generator_version: str
    generator_input: dict[str, Any]
    name: str
    discipline: Discipline
    target_grade_id: int | None
    current_grade_id: int | None
    start_date: date
    week_count: int
    grade_gap: int
    activated_at: datetime | None = None
    mesocycles: list[MesocycleOut]
    shortfalls: list[ShortfallOut]
    notes: list[NoteOut]


def _unprocessable(detail: str) -> HTTPException:
    """A well-formed request against stored state no plan can be built from.

    Matches `server/profile/routes.py::_unprocessable`. The client holds the profile and
    decides whether to ask at all, so this is defence in depth — and it invents no error-code
    vocabulary, because the sentence is already the whole answer.
    """
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _planner_input(session: Session, user_id: int, start_date: date) -> PlannerInput:
    """The profile, resolved into the generator's input. Two statements, no writes.

    The four NULL refusals are raised here — see the module docstring for why they cannot
    live in the domain. `CannotPlanError` is raised rather than an `HTTPException` so that
    the route has one mapping site for all six reasons.

    ⚠️ `user_id` comes from the token and from nowhere else. There is no path parameter, no
    body field and no query parameter naming a user anywhere in this module.

    The four grade/aspect lookups are outer JOINs rather than follow-up selects: they are
    primary-key reads of tiny seeded tables, and every extra round trip is Neon awake time.
    """
    target_grade = aliased(Grade)
    current_grade = aliased(Grade)
    strength = aliased(ClimbingAspect)
    weakness = aliased(ClimbingAspect)

    row = session.execute(
        select(
            UserProfile.primary_discipline,
            UserProfile.sessions_per_week,
            UserProfile.available_weekdays,
            target_grade.id.label("target_grade_id"),
            target_grade.ordinal.label("target_ordinal"),
            current_grade.id.label("current_grade_id"),
            current_grade.ordinal.label("current_ordinal"),
            strength.key.label("strength_aspect_key"),
            weakness.key.label("weakness_aspect_key"),
        )
        .select_from(UserProfile)
        .outerjoin(target_grade, target_grade.id == UserProfile.target_grade_id)
        .outerjoin(current_grade, current_grade.id == UserProfile.current_grade_id)
        .outerjoin(strength, strength.id == UserProfile.strength_aspect_id)
        .outerjoin(weakness, weakness.id == UserProfile.weakness_aspect_id)
        .where(UserProfile.user_id == user_id)
    ).one_or_none()

    # No row at all is the same answer as a row that has answered nothing: onboarding has
    # not reached the grade step, and the target grade is the first thing a plan needs.
    if row is None or row.primary_discipline is None or row.target_ordinal is None:
        raise CannotPlanError(RefusalReason.NO_TARGET_GRADE)
    if row.current_ordinal is None:
        raise CannotPlanError(RefusalReason.NO_CURRENT_GRADE)
    if row.sessions_per_week is None:
        raise CannotPlanError(RefusalReason.SESSIONS_PER_WEEK_UNANSWERED)
    # ⚠️ `0` is a legal ANSWER (answered, no days available) and gets its own refusal from
    # the domain. Only NULL is unanswered, so this is `is None` and must never be falsy.
    if row.available_weekdays is None:
        raise CannotPlanError(RefusalReason.AVAILABLE_WEEKDAYS_UNANSWERED)

    # Only the OPEN rows. A resolved injury is history (`flag -> resolve -> re-flag` is what
    # that table exists for) and withholding an exercise for one would be wrong.
    open_injury_keys = tuple(
        session.scalars(
            select(InjuryArea.key)
            .join(UserInjury, UserInjury.injury_area_id == InjuryArea.id)
            .where(UserInjury.user_id == user_id, UserInjury.resolved_on.is_(None))
            .order_by(InjuryArea.key)
        ).all()
    )

    return PlannerInput(
        discipline=row.primary_discipline,
        current_ordinal=row.current_ordinal,
        target_ordinal=row.target_ordinal,
        sessions_per_week=row.sessions_per_week,
        available_weekdays=row.available_weekdays,
        strength_aspect_key=row.strength_aspect_key,
        weakness_aspect_key=row.weakness_aspect_key,
        open_injury_keys=open_injury_keys,
        equipment_keys=_ASSUMED_EQUIPMENT_KEYS,
        start_date=start_date,
    )


def _grade_ids(session: Session, user_id: int) -> tuple[int | None, int | None]:
    """The two `grade.id`s, for the response only.

    `PlannerInput` carries ordinals, so `generate()` cannot fill these and leaves both
    `None` on the blueprint. The route sets them instead of `dataclasses.replace`-ing the
    blueprint, because adding ids to the input would give the domain a column it has no use
    for and would put them in `generator_input`, i.e. in the reproducibility digest.
    """
    row = session.execute(
        select(UserProfile.target_grade_id, UserProfile.current_grade_id).where(
            UserProfile.user_id == user_id
        )
    ).one_or_none()
    if row is None:
        return None, None
    return row.target_grade_id, row.current_grade_id


def _shortfall_out(shortfall: Shortfall) -> ShortfallOut:
    return ShortfallOut(
        phase=shortfall.phase,
        aspect_key=shortfall.aspect_key,
        options=[list(option) for option in shortfall.options],
        message=shortfall.message,
    )


def _set_out(prescribed: SetBlueprint) -> SetOut:
    return SetOut(
        set_index=prescribed.set_index,
        target_reps=prescribed.target_reps,
        target_work_seconds=prescribed.target_work_seconds,
        target_rest_seconds=prescribed.target_rest_seconds,
        target_intensity_pct=prescribed.target_intensity_pct,
        target_rpe=prescribed.target_rpe,
        target_load_kg=prescribed.target_load_kg,
        target_grade_id=prescribed.target_grade_id,
    )


def _block_out(block: BlockBlueprint) -> BlockOut:
    """A previewed block. `exercise_id` is left `None`: resolving it would cost a SELECT."""
    return BlockOut(
        order_index=block.order_index,
        exercise_key=block.exercise_key,
        aspect_key=block.aspect_key,
        protocol_kind=block.protocol_kind,
        rest_after_seconds=block.rest_after_seconds,
        rest_between_sets_seconds=block.rest_between_sets_seconds,
        sets=[_set_out(prescribed) for prescribed in block.sets],
        shortfall=None if block.shortfall is None else _shortfall_out(block.shortfall),
    )


def _session_out(planned: SessionBlueprint) -> SessionOut:
    return SessionOut(
        weekday=planned.weekday,
        scheduled_on=planned.scheduled_on,
        activity_kind=planned.activity_kind,
        title=planned.title,
        estimated_minutes=planned.estimated_minutes,
        blocks=[_block_out(block) for block in planned.blocks],
        shortfalls=[_shortfall_out(shortfall) for shortfall in planned.shortfalls],
    )


def _microcycle_out(microcycle: MicrocycleBlueprint) -> MicrocycleOut:
    return MicrocycleOut(
        week_no=microcycle.week_no,
        start_date=microcycle.start_date,
        is_deload=microcycle.is_deload,
        phase=microcycle.phase,
        sessions=[_session_out(planned) for planned in microcycle.sessions],
    )


def _mesocycle_out(mesocycle: MesocycleBlueprint) -> MesocycleOut:
    return MesocycleOut(
        phase=mesocycle.phase,
        start_week=mesocycle.start_week,
        end_week=mesocycle.end_week,
        microcycles=[_microcycle_out(microcycle) for microcycle in mesocycle.microcycles],
    )


def _note_out(note: ScheduleNote) -> NoteOut:
    return NoteOut(kind=note.kind, message=note.message)


def _response(
    blueprint: PlanBlueprint,
    planner_input: PlannerInput,
    *,
    target_grade_id: int | None,
    current_grade_id: int | None,
) -> PlanOut:
    """A preview, in the one shape a plan has. Every `id` stays `None` — see `PlanOut`."""
    return PlanOut(
        generator_version=GENERATOR_VERSION,
        generator_input=generator_input(planner_input),
        name=blueprint.name,
        discipline=blueprint.discipline,
        target_grade_id=target_grade_id,
        current_grade_id=current_grade_id,
        start_date=blueprint.start_date,
        week_count=blueprint.week_count,
        grade_gap=blueprint.grade_gap,
        mesocycles=[_mesocycle_out(mesocycle) for mesocycle in blueprint.mesocycles],
        shortfalls=[_shortfall_out(shortfall) for shortfall in blueprint.shortfalls],
        notes=[_note_out(note) for note in blueprint.notes],
    )


@router.post("/preview")
def preview_plan(
    payload: PlanPreviewRequest,
    principal: CurrentUser,
    session: RequestSession,
    response: Response,
) -> PlanOut:
    """Build the plan this user's profile implies, and return it. **Writes nothing.**

    "Writes nothing" is enforced three ways rather than asserted: the generator is pure
    (ruff `TID251` in `server/domain/.ruff.toml`), this handler issues only `SELECT`s, and
    for a demo principal `get_request_session` has already issued
    `SET LOCAL transaction_read_only`, so Postgres itself would refuse. The behavioural
    proof is in `tests/test_plans_api.py`, which counts `plan`, `mesocycle` and
    `planned_session` rows after a successful preview.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    start_date = (
        payload.start_date
        if payload.start_date is not None
        else week_start_on_or_after(_today_utc())
    )
    try:
        planner_input = _planner_input(session, principal.user_id, start_date)
        blueprint = generate(planner_input)
    except CannotPlanError as error:
        raise _unprocessable(error.message) from error

    target_grade_id, current_grade_id = _grade_ids(session, principal.user_id)
    return _response(
        blueprint,
        planner_input,
        target_grade_id=target_grade_id,
        current_grade_id=current_grade_id,
    )


# ---------------------------------------------------------------------------------
# The PERSISTED plan — the same models, with the nullable fields filled in
# ---------------------------------------------------------------------------------
#
# Round 1 of #11b left four fields off the persisted response because "nothing stores them".
# Three of the four were reachable and the fourth is now a column, so the persisted response
# is the preview's shape exactly:
#
# - the plan's `shortfalls` and `notes`, a session's `shortfalls`, a block's `shortfall` —
#   **stored**, as `plan.generator_caveats` (`0008`). Kilian's call, 2026-08-26. Without
#   them the `/plan` screen loses every equipment-gap banner on reload: the plan is still
#   complete (a shortfall is never a gate), but a plan that silently stops explaining itself
#   is worse than one that never explained itself at all.
# - `grade_gap` — **derived** from `generator_input`'s two ordinals (`_grade_gap`).
# - a block's `aspect_key` — **derived** from `exercise.climbing_aspect_id`
#   (`_exercise_reference`).
# - `exercise_key` — **derived** from the same map, and carried next to `exercise_id` rather
#   than replaced by it.
#
# ⚠️ One column for all four caveat kinds rather than four columns, and rather than one
# each on `plan`, `planned_session` and `session_block`. They are ONE fact — what the
# generator said about the plan it built, at the moment it built it — written by one
# statement, read by one screen, and **never queried inside**, which is the same argument
# `plan.generator_input` is `jsonb` for. Per-row columns would have spread a schemaless
# value across three tables and put ~2,400 mostly-NULL jsonb values in `session_block`
# to record the handful of blocks that have a caveat. `generator_caveats` sits next to
# `generator_version` and `generator_input`: the three columns are the generation record.


def _session_key(week_no: int, weekday: int) -> str:
    return f"{week_no}.{weekday}"


def _block_key(week_no: int, weekday: int, order_index: int) -> str:
    return f"{week_no}.{weekday}.{order_index}"


# ⚠️ **A coordinate, not a row id, and not a position.** A caveat is attached to a node that
# does not exist yet when it is written: the blueprint is serialised into
# `plan.generator_caveats` by the same INSERT that creates the plan row, long before any
# `session_block.id` does. So the key is the node's natural key within the plan — and all
# three levels of it are already enforced UNIQUE by the schema, which is what makes it a key
# rather than a convention: `microcycle (plan_id, week_no)`,
# `planned_session (microcycle_id, weekday)`, `session_block (planned_session_id,
# order_index)`. A list index would have been the cheap version and would mis-attach
# silently the day an `order_by` changed.
#
# Bumped when this module changes what it WRITES. Deliberately never branched on when
# reading: a version number tells you a blob is old, not whether it parses, and the read
# path validates the blob itself. It is stored so a support query can tell one generation's
# output from another's without re-deriving it.
_CAVEATS_SHAPE_VERSION: Final = 1


class _StoredCaveats(BaseModel):
    """`plan.generator_caveats`, in both directions. **Private to this module.**

    ⚠️ **The read path degrades and never 500s.** Every field has a default, the whole blob
    is validated in one `model_validate`, and anything this module does not recognise — a
    `Shortfall` that has gained a required field, a `Phase` that no longer exists, a
    hand-edited row, a `null`, a list where a dict belongs — is treated as **"no
    caveats"**. `plan.generator_version` is what tells a reader which generator wrote the
    row; the point of the degrade is that an old plan stays OPENABLE. A plan somebody is
    halfway through must not become unreadable because a dataclass in
    `server/domain/planner/blueprint.py` changed shape.

    Unknown keys are IGNORED rather than rejected (Pydantic's default, left alone on
    purpose), so a newer writer's blob still parses for an older reader — the other half of
    the same property.
    """

    shape_version: int = 0
    shortfalls: list[ShortfallOut] = Field(default_factory=list)
    notes: list[NoteOut] = Field(default_factory=list)
    # Coordinate -> that session's unfilled slots / that block's one shortfall.
    session_shortfalls: dict[str, list[ShortfallOut]] = Field(default_factory=dict)
    block_shortfalls: dict[str, ShortfallOut] = Field(default_factory=dict)


def _stored_caveats(blueprint: PlanBlueprint) -> dict[str, Any]:
    """The blueprint's caveats, as the JSON `plan.generator_caveats` holds. Write path only.

    Sparse: a session with every slot filled and a block with no shortfall contribute no
    key at all, so a well-equipped climber's plan stores two empty lists and two empty
    objects rather than one entry per node.
    """
    session_shortfalls: dict[str, list[ShortfallOut]] = {}
    block_shortfalls: dict[str, ShortfallOut] = {}
    for mesocycle in blueprint.mesocycles:
        for microcycle in mesocycle.microcycles:
            for planned in microcycle.sessions:
                if planned.shortfalls:
                    session_shortfalls[_session_key(microcycle.week_no, planned.weekday)] = [
                        _shortfall_out(shortfall) for shortfall in planned.shortfalls
                    ]
                for block in planned.blocks:
                    if block.shortfall is not None:
                        key = _block_key(microcycle.week_no, planned.weekday, block.order_index)
                        block_shortfalls[key] = _shortfall_out(block.shortfall)
    return _StoredCaveats(
        shape_version=_CAVEATS_SHAPE_VERSION,
        shortfalls=[_shortfall_out(shortfall) for shortfall in blueprint.shortfalls],
        notes=[_note_out(note) for note in blueprint.notes],
        session_shortfalls=session_shortfalls,
        block_shortfalls=block_shortfalls,
    ).model_dump(mode="json")


def _read_caveats(plan: Plan) -> _StoredCaveats:
    """`plan.generator_caveats`, parsed — or an EMPTY record. Never raises."""
    raw = plan.generator_caveats
    if raw is None:
        return _StoredCaveats()
    try:
        return _StoredCaveats.model_validate(raw)
    except ValidationError:
        # See `_StoredCaveats`: an unrecognised shape is "no caveats", never a 500.
        return _StoredCaveats()


@dataclass(frozen=True, slots=True)
class _ReadContext:
    """What the plan's own rows cannot answer, fetched once per response.

    `exercises` maps `exercise.id` to `(key, aspect_key)` — the two fields a persisted block
    derives rather than stores. `caveats` is `plan.generator_caveats`, parsed.
    """

    exercises: dict[int, tuple[str, str]]
    caveats: _StoredCaveats


def _exercise_reference(session: Session) -> dict[int, tuple[str, str]]:
    """Every exercise's key and aspect key, by id. **One statement, ~120 rows.**

    Whole-table rather than filtered to the ids in this plan: the table is seeded reference
    data of a hundred-odd rows, and building an `IN (...)` first would mean walking the
    2,400-node tree twice.

    Retired exercises are INCLUDED, on purpose. A plan generated before a retirement still
    points at the row, and the reason `exercise.retired_at` exists instead of a DELETE is
    that an old plan has to keep resolving to a name.
    """
    return {
        row.id: (row.key, row.aspect_key)
        for row in session.execute(
            select(Exercise.id, Exercise.key, ClimbingAspect.key.label("aspect_key")).join(
                ClimbingAspect, ClimbingAspect.id == Exercise.climbing_aspect_id
            )
        ).all()
    }


def _grade_gap(stored_generator_input: dict[str, Any]) -> int:
    """`target_ordinal - current_ordinal`, off the stored `generator_input`.

    Derived rather than stored, because it IS `PlannerInput.grade_gap` and both ordinals are
    already on the row inside the reproducibility record. A column would be a third copy of
    one fact, and the copy that drifts.

    The two grade *ids* on `plan` joined twice to `grade.ordinal` would be the other route
    and are deliberately not used: both are nullable, and the ordinals are what the
    generator actually consumed.

    Same degrade rule as `_StoredCaveats` — a `generator_input` whose ordinals this module
    does not recognise yields **0** rather than a 500, so an old plan stays openable.
    """
    target = stored_generator_input.get("target_ordinal")
    current = stored_generator_input.get("current_ordinal")
    if isinstance(target, int) and isinstance(current, int):
        return target - current
    return 0


class ActivePlanResponse(BaseModel):
    """`{"plan": null}` when there is none — a **200**, not a 404.

    "No plan yet" is the state every new account is in and the `/plan` screen has to render
    it as an ordinary view with a Generate button, not as an error. A 404 would make the
    normal case an error at three layers that all treat 4xx as failure: `apiFetch` throws on
    it, the query retry predicate skips 4xx as unwinnable, and a route-level guard would
    have `data === undefined` and swap itself for a fallback. Every one of those would then
    need a special case for "the expected answer".

    A wrapper object rather than a bare nullable body, so the endpoint can grow a sibling
    field (a count of past plans, say) without changing shape, and so no client has to
    handle a top-level `null`.
    """

    plan: PlanOut | None


class PlanAbandonResponse(BaseModel):
    """The timestamp that was set, or the one already there. Idempotent either way."""

    id: int
    abandoned_at: datetime


def _persisted_set(prescribed: PrescribedSet) -> SetOut:
    return SetOut(
        id=prescribed.id,
        set_index=prescribed.set_index,
        target_reps=prescribed.target_reps,
        target_work_seconds=prescribed.target_work_seconds,
        target_rest_seconds=prescribed.target_rest_seconds,
        target_intensity_pct=prescribed.target_intensity_pct,
        target_rpe=prescribed.target_rpe,
        target_load_kg=prescribed.target_load_kg,
        target_grade_id=prescribed.target_grade_id,
    )


def _persisted_block(
    block: SessionBlock, context: _ReadContext, *, week_no: int, weekday: int
) -> BlockOut:
    # A `KeyError` here would be a fault, not a missing-data case, so it is not defended
    # against: `session_block.exercise_id` is NOT NULL and `NO ACTION`, so Postgres refuses
    # to delete an exercise a plan points at, and the map above is the whole table.
    exercise_key, aspect_key = context.exercises[block.exercise_id]
    return BlockOut(
        id=block.id,
        order_index=block.order_index,
        exercise_key=exercise_key,
        exercise_id=block.exercise_id,
        aspect_key=aspect_key,
        protocol_kind=block.protocol_kind,
        rest_after_seconds=block.rest_after_seconds,
        rest_between_sets_seconds=block.rest_between_sets_seconds,
        sets=[_persisted_set(prescribed) for prescribed in block.prescribed_sets],
        shortfall=context.caveats.block_shortfalls.get(
            _block_key(week_no, weekday, block.order_index)
        ),
    )


def _persisted_session(
    planned: PlannedSession, context: _ReadContext, *, week_no: int
) -> SessionOut:
    return SessionOut(
        id=planned.id,
        weekday=planned.weekday,
        scheduled_on=planned.scheduled_on,
        activity_kind=planned.activity_kind,
        status=planned.status,
        title=planned.title,
        estimated_minutes=planned.estimated_minutes,
        blocks=[
            _persisted_block(block, context, week_no=week_no, weekday=planned.weekday)
            for block in planned.blocks
        ],
        shortfalls=context.caveats.session_shortfalls.get(
            _session_key(week_no, planned.weekday), []
        ),
    )


def _persisted_microcycle(
    microcycle: Microcycle, context: _ReadContext, *, phase: Phase
) -> MicrocycleOut:
    return MicrocycleOut(
        id=microcycle.id,
        week_no=microcycle.week_no,
        start_date=microcycle.start_date,
        is_deload=microcycle.is_deload,
        phase=phase,
        sessions=[
            _persisted_session(planned, context, week_no=microcycle.week_no)
            for planned in microcycle.planned_sessions
        ],
    )


def _persisted_mesocycle(mesocycle: Mesocycle, context: _ReadContext) -> MesocycleOut:
    return MesocycleOut(
        id=mesocycle.id,
        phase=mesocycle.phase,
        start_week=mesocycle.start_week,
        end_week=mesocycle.end_week,
        microcycles=[
            # The phase is the mesocycle's; `microcycle` has no column for it.
            _persisted_microcycle(microcycle, context, phase=mesocycle.phase)
            for microcycle in mesocycle.microcycles
        ],
    )


def _plan_response(session: Session, plan: Plan) -> PlanOut:
    """A persisted plan, in the shape `/preview` returns. **One extra statement.**

    That statement is `_exercise_reference`, issued once per response rather than once per
    block; it is what buys `exercise_key` and `aspect_key` on a persisted block with no
    column for either. Used by both `POST ""` and `GET /active`, so the body a client gets
    when it creates a plan is byte-identical to the one it gets when it reloads.
    """
    context = _ReadContext(exercises=_exercise_reference(session), caveats=_read_caveats(plan))
    return PlanOut(
        id=plan.id,
        generator_version=plan.generator_version,
        generator_input=plan.generator_input,
        name=plan.name,
        discipline=plan.discipline,
        target_grade_id=plan.target_grade_id,
        current_grade_id=plan.current_grade_id,
        start_date=plan.start_date,
        week_count=plan.week_count,
        grade_gap=_grade_gap(plan.generator_input),
        activated_at=plan.activated_at,
        mesocycles=[_persisted_mesocycle(mesocycle, context) for mesocycle in plan.mesocycles],
        shortfalls=context.caveats.shortfalls,
        notes=context.caveats.notes,
    )


# "Active", once, as criteria rather than as a query — because the READ needs a `select` and
# the stand-down needs an `update`, and a shared `select` would give only one of them.
#
# ⚠️ Kept character-identical to `uq_plan_one_active_per_user`'s predicate and to
# `server/models.py::Plan`'s docstring. The index can only refuse a second active row, so if
# this criterion and that predicate disagreed the index would keep passing while the app
# stopped agreeing with it. Pinned by
# `tests/test_plans_persist.py::test_the_ACTIVE_CRITERION_and_the_INDEX_PREDICATE_cannot_drift`,
# which reads the predicate back out of `pg_indexes` and compares it to this tuple.
_ACTIVE_STATE: Final = (
    Plan.activated_at.is_not(None),
    Plan.abandoned_at.is_(None),
    Plan.completed_at.is_(None),
)


def _active_plan_query(user_id: int) -> Select[tuple[Plan]]:
    """This user's active plan. See `_ACTIVE_STATE`."""
    return select(Plan).where(Plan.user_id == user_id, *_ACTIVE_STATE)


# One SELECT per level rather than one wide join: a join down five 1:N edges repeats every
# ancestor's columns on all 2,421 leaf rows, and the round trips are the cheap axis here
# (six statements inside one transaction is one Neon wake either way). The relationships
# already declare `order_by`, so nothing here re-sorts.
_PLAN_TREE: Final = (
    selectinload(Plan.mesocycles)
    .selectinload(Mesocycle.microcycles)
    .selectinload(Microcycle.planned_sessions)
    .selectinload(PlannedSession.blocks)
    .selectinload(SessionBlock.prescribed_sets)
)


def _exercise_ids(session: Session, blueprint: PlanBlueprint) -> dict[str, int]:
    """Every `exercise_key` in the tree, resolved to an id in ONE statement.

    The `server/contentseed.py::_ids_by_key` idiom. The set is small — a generated plan
    draws on a few dozen distinct keys however many thousand sets it has — so this is one
    `WHERE key IN (...)` regardless of plan length.

    ⚠️ **A missing key raises, and that is an ASSERTION rather than a fallback.** It should
    be impossible: the blueprint's keys come from `server/domain/exercises.py`, and
    `library_digest` — a sha256 over that same authored library — is part of the
    `generator_input` stored on the row, so a plan that referenced a key the database does
    not have would already be unreproducible. The alternatives are both worse than a 500: a
    NULL `exercise_id` is refused by the column, and skipping the block silently ships a
    session missing an exercise the user was told they would do.
    """
    keys = {
        block.exercise_key
        for mesocycle in blueprint.mesocycles
        for microcycle in mesocycle.microcycles
        for planned in microcycle.sessions
        for block in planned.blocks
    }
    if not keys:
        return {}
    found = {
        key: row_id
        for key, row_id in session.execute(
            select(Exercise.key, Exercise.id).where(Exercise.key.in_(keys))
        ).all()
    }
    missing = sorted(keys - found.keys())
    if missing:
        raise RuntimeError(
            f"the generator prescribed exercise keys with no row: {missing}. The library is "
            f"an input to the plan (see `library_digest` in `generator_input`), so this "
            f"means the database's exercise table and server/domain/exercises.py disagree — "
            f"run `python -m server.contentseed`. Nothing was written."
        )
    return found


def _insert_plan_tree(
    session: Session,
    blueprint: PlanBlueprint,
    planner_input: PlannerInput,
    *,
    user_id: int,
    target_grade_id: int | None,
    current_grade_id: int | None,
    activated_at: datetime,
) -> Plan:
    """Build the ORM object graph and let the existing cascades flush it. Two flushes.

    ## Why the ORM graph, and not `insert().values([...])` per level

    Both shapes were credible; this one was chosen after reading the installed SQLAlchemy
    (2.0.52), because the objection to it — "an ORM flush emits one INSERT per row" — is
    false on this dialect. What the source says, with citations, since an uncited claim
    about a library's behaviour is how the last three review rounds each found a bug:

    - `orm/persistence.py:1086-1146` (`_emit_insert_statements`). With no client-side
      primary key, `table.implicit_returning` true and more than one record in the group, it
      consults `connection.dialect.insert_executemany_returning_sort_by_parameter_order`;
      when that is true it sets `do_executemany = True`, adds `return_defaults(
      *table.primary_key, sort_by_parameter_order=...)`, and issues **one**
      `connection.execute(statement, multiparams)` for the whole group.
    - `dialects/postgresql/base.py:3320` sets `use_insertmanyvalues = True`, and
      `engine/default.py:395-430` derives both `insert_executemany_returning*` flags as
      `insert_returning and use_insertmanyvalues`. `dialects/postgresql/psycopg.py:467-473`
      is the only thing that clears them, and only for a server <= 8.2.
    - `engine/default.py:245` — `insertmanyvalues_page_size = 1000`, so the worst-case
      2,421 `prescribed_set` rows are **3** statements, not 2,421.
    - `orm/mapper.py:2765` (`_insert_cols_as_none`) plus `orm/persistence.py:368-380`: a
      non-bulk flush adds an explicit `None` for every column with **no default and no
      server default**, so the parameter-key set is identical for every instance of a
      mapper. That matters because `persistence.py:1003-1015` groups records with
      `itertools.groupby` on that key set, and `groupby` only groups *consecutive* runs —
      alternating shapes would fragment one executemany into many.

    So the flush is ~6 statements per level, the ids come back in `RETURNING` and are
    populated onto the objects, and the response is built from the objects with no re-read.
    The explicit-insert shape would need either `RETURNING` (the same mechanism, spelled by
    hand) or a re-`SELECT` per level, and `prescribed_set` has no natural key to re-select
    on.

    ⚠️ **`status`, `activity_kind` and `is_deload` are passed explicitly even though all
    three have a server default.** Two reasons, both from the citations above: a column with
    a `server_default` is NOT in `_insert_cols_as_none`, so setting it on some rows and not
    others is exactly the fragmentation `groupby` punishes; and an unset server default
    comes back as an expired attribute, which the response serialiser would then refresh one
    row at a time. All three values are known here, so there is nothing to fetch.

    ## ⚠️ The graph must be attached through the COLLECTION, not the child's parent

    This is a bug that shipped in the first draft of this function and was caught by running
    it, not by reading it: `Mesocycle(plan=plan, ...)` persisted the plan row and **silently
    dropped every one of its 2,400 descendants**, with a `201`, a committed transaction, and
    one `SAWarning` in the log.

    `orm/unitofwork.py::track_cascade_events` is why. Its `append` listener runs the
    save-update cascade only when `prop._cascade.save_update and (key == initiator.key) and
    not sess._contains_state(item_state)`. `initiator.key` is the attribute the caller
    actually mutated — so setting the many-to-one `Mesocycle.plan` fires `set_` on an object
    with no session (nothing happens), and the backref's `append` on `plan.mesocycles`
    arrives with `initiator.key == "plan"`, fails the gate, and cascades nothing. That gate
    **is** the `cascade_backrefs` behaviour SQLAlchemy 2.0 removed. Appending to
    `plan.mesocycles` directly passes it, and `session.py:3512-3518`
    (`_save_or_update_state`) then walks `mapper.cascade_iterator("save-update", ...)`
    recursively, which is what picks up the microcycles, sessions, blocks and sets below in
    one call. The warning itself comes from `orm/dependency.py:840-848`.

    Nothing in the schema requires a plan to have a mesocycle, so there is no constraint
    that would have caught this — hence the collection form plus this note.

    ## Two flushes, and the first one is not avoidable

    `microcycle.plan_id` is a **denormalised** column with no relationship behind it — the
    composite FK `(mesocycle_id, plan_id) -> mesocycle (id, plan_id)` is what makes it safe
    — so SQLAlchemy will not populate it, and `plan.id` does not exist until the plan row
    is inserted. Hence: add the plan, flush (one INSERT), then build the subtree with
    `plan_id` set, and flush that.
    """
    exercise_ids = _exercise_ids(session, blueprint)

    plan = Plan(
        user_id=user_id,
        name=blueprint.name,
        discipline=blueprint.discipline,
        target_grade_id=target_grade_id,
        current_grade_id=current_grade_id,
        start_date=blueprint.start_date,
        week_count=blueprint.week_count,
        generator_version=GENERATOR_VERSION,
        generator_input=generator_input(planner_input),
        # The generator's caveats about the plan it just built. Written here rather than
        # derived on the way out because a block's shortfall names the aspect the generator
        # WANTED and could not fill, which no persisted row records. See `_StoredCaveats`.
        generator_caveats=_stored_caveats(blueprint),
        activated_at=activated_at,
        # Initialised empty so the collection counts as LOADED. Without it, the first
        # `plan.mesocycles.append(...)` below happens on a persistent object and lazy-loads
        # the collection — one extra round trip, guaranteed to return zero rows, because the
        # plan was inserted by this transaction moments earlier.
        mesocycles=[],
    )
    session.add(plan)
    # One statement, and the only reason it is separate: see the docstring's second half.
    session.flush()

    # ⚠️ Built BOTTOM-UP and attached through the COLLECTION, never through the child's
    # parent attribute. See the docstring's third section — the child-side form loses the
    # whole subtree and only warns.
    for mesocycle_blueprint in blueprint.mesocycles:
        microcycles = []
        for microcycle_blueprint in mesocycle_blueprint.microcycles:
            planned_sessions = []
            for session_blueprint in microcycle_blueprint.sessions:
                blocks = []
                for block_blueprint in session_blueprint.blocks:
                    blocks.append(
                        SessionBlock(
                            order_index=block_blueprint.order_index,
                            exercise_id=exercise_ids[block_blueprint.exercise_key],
                            protocol_kind=block_blueprint.protocol_kind,
                            rest_after_seconds=block_blueprint.rest_after_seconds,
                            rest_between_sets_seconds=block_blueprint.rest_between_sets_seconds,
                            prescribed_sets=[
                                PrescribedSet(
                                    set_index=set_blueprint.set_index,
                                    target_reps=set_blueprint.target_reps,
                                    target_work_seconds=set_blueprint.target_work_seconds,
                                    target_rest_seconds=set_blueprint.target_rest_seconds,
                                    target_intensity_pct=set_blueprint.target_intensity_pct,
                                    target_rpe=set_blueprint.target_rpe,
                                    target_load_kg=set_blueprint.target_load_kg,
                                    target_grade_id=set_blueprint.target_grade_id,
                                )
                                for set_blueprint in block_blueprint.sets
                            ],
                        )
                    )
                planned_sessions.append(
                    PlannedSession(
                        weekday=session_blueprint.weekday,
                        scheduled_on=session_blueprint.scheduled_on,
                        activity_kind=session_blueprint.activity_kind,
                        status=SessionStatus.PLANNED,
                        title=session_blueprint.title,
                        estimated_minutes=session_blueprint.estimated_minutes,
                        blocks=blocks,
                    )
                )
            microcycles.append(
                Microcycle(
                    # ⚠️ The denormalised column the composite FK
                    # `(mesocycle_id, plan_id) -> mesocycle (id, plan_id)` ties back. There
                    # is deliberately no relationship to `plan` for SQLAlchemy to populate
                    # this from, so omitting it is not a NULL — it is a failed insert.
                    plan_id=plan.id,
                    week_no=microcycle_blueprint.week_no,
                    start_date=microcycle_blueprint.start_date,
                    is_deload=microcycle_blueprint.is_deload,
                    planned_sessions=planned_sessions,
                )
            )
        # THIS append is what puts the whole subtree in the session.
        plan.mesocycles.append(
            Mesocycle(
                phase=mesocycle_blueprint.phase,
                start_week=mesocycle_blueprint.start_week,
                end_week=mesocycle_blueprint.end_week,
                microcycles=microcycles,
            )
        )

    # Everything below the plan, in five executemany groups plus paging.
    session.flush()
    return plan


def _stand_down_active_plan(session: Session, user_id: int, at: datetime) -> None:
    """Mark this user's active plan abandoned, if there is one. One statement, no read.

    **This is the invariant, and it is why there is no separate "switch" endpoint:** the
    transaction that activates one plan is the transaction that stands the other down.
    `uq_plan_one_active_per_user` can only refuse a second active row — it cannot decide
    which one survives — so without this the second activation would simply 409.

    Order matters: this runs BEFORE the insert. The index is not deferrable, so it is
    checked per statement, and the old row has to leave the predicate before the new one
    enters it.

    The criterion is `_ACTIVE_STATE`, shared with `_active_plan_query` — an `update` cannot
    reuse the `select`, but it can reuse the predicates.
    """
    session.execute(
        update(Plan).where(Plan.user_id == user_id, *_ACTIVE_STATE).values(abandoned_at=at)
    )


def _constraint_name(error: IntegrityError) -> str | None:
    """psycopg3's `Diagnostic.constraint_name` — the index name for a unique violation.

    Read structurally rather than by matching a substring of the driver's message, and it is
    the ONLY part of an `IntegrityError` this module is allowed to keep: see `create_plan`.
    """
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


def _is_one_active_conflict(error: IntegrityError) -> bool:
    """Was this the one-active-plan index refusing a second active plan, or something else?

    Anything else — a foreign key, a CHECK, an index this module does not know about — is a
    real 500 and must not be reported to the client as "you already have a plan".
    """
    return _constraint_name(error) == _ONE_ACTIVE_INDEX


@router.post("", status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: PlanPreviewRequest,
    principal: CurrentUser,
    session: RequestSession,
    response: Response,
) -> PlanOut:
    """Generate this user's plan, persist it activated, and return it with ids. **201.**

    A **Tier-1 write** (CLAUDE.md, "Two write tiers", which already groups creating,
    switching, activating and abandoning a plan as one write-through): one request, one
    transaction, one Neon wake.

    ## The server regenerates; it never accepts a tree

    The request body is `PlanPreviewRequest` — `start_date` and nothing else, `extra
    ="forbid"`. **A client-supplied tree is not accepted and must never be**, for two
    independent reasons: it would let any caller fabricate an arbitrary plan (prescriptions
    against exercises their injuries contraindicate, included), and it would be a 583 KiB
    request body. `user_id` comes from `principal.user_id` and from nowhere else — no path
    parameter, no body field, no query parameter in this module names a user.

    The generation path is the preview's, reused rather than reimplemented
    (`_planner_input` -> `generate` -> `_grade_ids`), so a plan can never be persisted in a
    shape the preview would not have shown.

    ## One transaction, all-or-nothing

    Four steps, one `commit()` at the end, following `server/profile/routes.py::patch_profile`
    (each route commits itself; `get_session` deliberately does not):

    1. Stand the currently-active plan down — see `_stand_down_active_plan` for why this is
       the same transaction and why it is first.
    2. Resolve every `exercise_key` to an id in one statement, raising if any is missing.
    3. Insert the tree, with `generator_version`, `generator_input` and `activated_at`.
    4. Build the response from the in-memory objects, then commit.

    A failure anywhere — the refusal, the missing key, an insert, the unique index — leaves
    zero rows in all six tables, because nothing before the `commit()` is durable.

    ## 409 is a legitimate answer, not a fault

    A double-tap races: both requests stand the same plan down and both insert an active
    one, and the second trips `uq_plan_one_active_per_user`. That is not an error state —
    the user does have an active plan — so it comes back as a **409** for the client to
    treat as "you already have one" and refetch.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    start_date = (
        payload.start_date
        if payload.start_date is not None
        else week_start_on_or_after(_today_utc())
    )
    try:
        planner_input = _planner_input(session, principal.user_id, start_date)
        blueprint = generate(planner_input)
    except CannotPlanError as error:
        raise _unprocessable(error.message) from error

    target_grade_id, current_grade_id = _grade_ids(session, principal.user_id)
    now = _now_utc()

    try:
        _stand_down_active_plan(session, principal.user_id, now)
        plan = _insert_plan_tree(
            session,
            blueprint,
            planner_input,
            user_id=principal.user_id,
            target_grade_id=target_grade_id,
            current_grade_id=current_grade_id,
            activated_at=now,
        )
        # Serialise BEFORE committing, like `patch_profile` reads before committing: the
        # response is what the transaction is about to make durable, and the objects are
        # still fully populated here.
        body = _plan_response(session, plan)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if _is_one_active_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have an active plan.",
            ) from error
        # ⚠️ **The exception is not re-raised, and that is input minimisation on the LOG
        # side.** `str(IntegrityError)` carries the failing statement *and its bound
        # parameters* — for a failure on the `plan` INSERT that is `generator_input` and
        # `generator_caveats`, i.e. the climber's open-injury keys, in the function log.
        # (This repo has form: a guard once printed a live Neon password 51x through
        # pytest's frame rendering.) So the constraint name and plan-level metadata are
        # logged — enough to find the bug — and `from None` drops the chained traceback so
        # the parameters cannot come back through the renderer either.
        _logger.error(
            "plan insert failed: constraint=%s user_id=%s week_count=%s generator_version=%s",
            _constraint_name(error) or "unknown",
            principal.user_id,
            blueprint.week_count,
            GENERATOR_VERSION,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Your plan could not be saved.",
        ) from None
    return body


@router.get("/active")
def active_plan(
    principal: CurrentUser, session: RequestSession, response: Response
) -> ActivePlanResponse:
    """This user's active plan with ids, or `{"plan": null}`. Always **200** — see the model.

    Without this endpoint a persisted plan is invisible after a page reload and the whole
    write path delivers nothing observable.

    `.one_or_none()` rather than `.first()`: "at most one" is `uq_plan_one_active_per_user`'s
    job, and if the index were ever dropped, a silent `LIMIT 1` would hide that while
    quietly picking an arbitrary plan.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    plan = session.scalars(_active_plan_query(principal.user_id).options(_PLAN_TREE)).one_or_none()
    return ActivePlanResponse(plan=None if plan is None else _plan_response(session, plan))


@router.post("/{plan_id}/abandon")
def abandon_plan(
    plan_id: int, principal: CurrentUser, session: RequestSession, response: Response
) -> PlanAbandonResponse:
    """Stand a plan down. **Marks, never deletes.** Idempotent, and 404 for anyone else's.

    ## Why a timestamp and not a delete

    `activity.planned_session_id` is the only link from a logged activity to the plan it
    satisfied, so deleting an abandoned plan would cascade through the tree and destroy the
    adherence record of sessions the user really did.

    ## The 404 is scoped, and the scoping is the security property

    The `WHERE` names both the id and `principal.user_id`, so another user's plan is
    indistinguishable from one that does not exist — the same answer, the same message. A
    403 here would confirm the row exists, which is the IDOR read this project treats as its
    real extraction risk.

    **Idempotent:** an already-abandoned plan keeps its original timestamp and nothing is
    written, because when it was stood down is the fact the diary wants, not when someone
    last pressed the button. `completed_at` is deliberately untouched — completing and
    abandoning are different things and only one of them is in scope for #11b.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    # ⚠️ Scoped by id and user, deliberately NOT by `_ACTIVE_STATE`: today the only way to
    # leave the active set is this endpoint, so "abandon a plan that is not active" is
    # unreachable. **The first path that COMPLETES a plan makes it reachable**, and this
    # would then stamp `abandoned_at` on a completed plan — `completed_at IS NOT NULL AND
    # abandoned_at IS NOT NULL`, a state nothing else can produce. Add the guard with that
    # path, not before: a guard now would be an untestable branch.
    plan = session.scalars(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == principal.user_id)
    ).one_or_none()
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such plan.")
    abandoned_at = plan.abandoned_at
    if abandoned_at is None:
        abandoned_at = _now_utc()
        plan.abandoned_at = abandoned_at
        session.commit()
    return PlanAbandonResponse(id=plan.id, abandoned_at=abandoned_at)
