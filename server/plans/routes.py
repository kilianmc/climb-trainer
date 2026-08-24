"""`POST /api/plans/preview` — the plan the generator would build, without building it.

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
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

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
from server.domain.vocabulary import EQUIPMENT, ActivityKind, Phase, ProtocolKind
from server.models import ClimbingAspect, Grade, InjuryArea, UserInjury, UserProfile

router = APIRouter(prefix="/api/plans", tags=["plans"])

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


def _today_utc() -> date:
    """The server's own date. The domain may not ask this question; this module may."""
    return datetime.now(UTC).date()


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


class SetOut(BaseModel):
    """One prescribed set, straight off the `(exercise, phase)` prescription template.

    `target_load_kg` and `target_grade_id` are present and always `null` in v1.0.0, so the
    wire shape is stable when they are filled. Deriving a load is the one place a bodyweight
    figure could creep into a plan, which CLAUDE.md's weight rule forbids outright.
    """

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

    `exercise_key`, not `exercise_id`: the domain is DB-free and speaks keys, the client
    already holds `key` from `useLibrary()`, and it saves a `SELECT`. #11b resolves keys to
    ids at persist time.

    `rest_between_sets_seconds` has no home in the persisted plan tree — the template has it
    and `session_block` does not — and is carried anyway so the preview is honest. #11b needs
    a column or a redefinition.
    """

    order_index: int
    exercise_key: str
    aspect_key: str
    protocol_kind: ProtocolKind
    rest_after_seconds: int | None
    rest_between_sets_seconds: int | None
    sets: list[SetOut]
    shortfall: ShortfallOut | None


class SessionOut(BaseModel):
    """One planned session. `estimated_minutes` is `null` for a session with no blocks."""

    weekday: int
    scheduled_on: date
    activity_kind: ActivityKind
    title: str
    estimated_minutes: int | None
    blocks: list[BlockOut]
    shortfalls: list[ShortfallOut]


class MicrocycleOut(BaseModel):
    """One week. `is_deload` is exactly `phase is Phase.DELOAD`; a taper is known by `phase`."""

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

    phase: Phase
    start_week: int
    end_week: int
    microcycles: list[MicrocycleOut]


class NoteOut(BaseModel):
    """One honest caveat about the plan as a whole. `kind` is the contract, `message` is copy."""

    kind: NoteKind
    message: str


class PlanPreviewResponse(BaseModel):
    """The whole plan, plus what would be needed to reproduce it.

    `generator_input` is the canonical JSON of the `PlannerInput` actually used, plus
    `generator_version` and `library_digest`. That digest is load-bearing:
    `server/models.py::Plan` promises that re-running a version on the same input reproduces
    the tree, and **the library is a third input** — without it the promise is false the
    first time content is edited, and the failure is silent.

    ⚠️ `target_grade_id` and `current_grade_id` are set HERE and are always `None` on the
    blueprint: `PlannerInput` carries ordinals, so the domain never sees a `grade.id`. Note
    `plan` has no `current_grade_id` column, so the field is a preview-only convenience the
    `/plan` header uses for `compareToGoal`; #11b needs a column or has to drop it.
    """

    generator_version: str
    generator_input: dict[str, Any]
    name: str
    discipline: Discipline
    target_grade_id: int | None
    current_grade_id: int | None
    start_date: date
    week_count: int
    grade_gap: int
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
) -> PlanPreviewResponse:
    return PlanPreviewResponse(
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
) -> PlanPreviewResponse:
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
