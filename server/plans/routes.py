"""`/api/plans` — preview a generated plan, persist it, read it back, stand it down.

`POST /preview` builds the plan the generator would build and **writes nothing**. `POST ""`
regenerates the same tree and **persists it, activated, standing the previously active plan
down in the same transaction**. `GET /active` reads it back — without which a persisted plan is
invisible after a reload — and `POST /{plan_id}/abandon` stands one down.

⚠️ **`/preview` is the ONLY one of the four in `DEMO_WRITE_EXEMPT_ROUTES`**, because it is the
only one that writes nothing. The other three are refused for a demo principal twice over:
`enforce_auth` 403s a demo-scope token on every `POST`, and `get_request_session` has issued
`SET LOCAL transaction_read_only`. Adding an exemption entry would remove both.

**A POST for a read**, because a per-user body on a cacheable verb is the `/api/library` CDN
trap read backwards: that endpoint is `public, immutable` *because* its body is identical for
everyone, and this one is assembled from one climber's grades, availability, declared weakness
and open injuries. `POST` is uncached by default, so the safe thing is the default thing.

**Exactly one field is the client's: `start_date`** — the client knows the timezone and the
domain has no clock. Everything else is read here, scoped by the user id **from the token**;
there is deliberately no way to name a user in a path, a body or a query, because one unscoped
read hands over somebody's training history.

**Four refusals are raised here, two by the domain.** An unanswered profile column has no
representation in a plannable `PlannerInput` and CLAUDE.md forbids substituting a default, so
the four NULL cases are detected where the row is read; the two that are properties of the
*values* (cross-ladder grades, an empty weekday mask) are raised inside the domain. All six
share one `RefusalReason`, so the HTTP mapping is one `except CannotPlanError`, and every
sentence comes from `REFUSAL_MESSAGES`.

**Pydantic here, dataclasses in the domain**, with a hand-written mapper per node — the same
stitching `server/library/routes.py` does, so the domain gains no FastAPI dependency. The
return-type annotation IS the response model; `response_model=` is used nowhere in this repo.

**ONE set of response models, two mappers.** `PlanOut` serves all four routes. Two mapper
families because there are two sources (`_*_out` from the blueprint, `_persisted_*` from the ORM
rows); one model family because there is one client renderer, and a second renderer is where the
two would drift.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    computed_field,
    field_validator,
)
from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from server.auth.deps import CurrentUser, RequestSession
from server.domain.grades import Discipline
from server.domain.planner import (
    GENERATOR_VERSION,
    BlockBlueprint,
    CannotPlanError,
    Level,
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
    climbing_floor_pct,
    climbing_target_band,
    generate,
    generator_input,
    level_for,
)
from server.domain.planner.climbing import FINGER_PHASES, finger_sessions_for
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

# ⚠️ **A security decision, not cache tuning.** These bodies are assembled from ONE climber's
# grades, availability, declared weakness and **open injuries**, so a shared-cache entry would
# hand a stranger a picture of somebody's injuries and no behavioural test could see it happen.
# `private` forbids the CDN; `no-store` also keeps it off the browser's disk, the same argument
# that keeps `runtimeCaching` off `/api` in the service worker. Contrast `/api/library`, which is
# `public, s-maxage=31536000, immutable` precisely because its body is identical for every user —
# the two rules differ on purpose.
#
# `POST` is already uncached by default, so this is defence in depth: the verb was chosen FOR
# that property, and a later "make it a GET so it caches" would remove it while this header
# quietly kept working.
_CACHE_CONTROL: Final = "private, no-store"

# How far either side of today's UTC date a client may place a start.
#
# ⚠️ Deliberately NOT in `server/fields.py`, whose discipline is one bounded type per persisted
# CHECK: `plan.start_date` has no CHECK, and this is a request-sanity bound rather than a schema
# fact.
#
# A week behind, because a client in UTC-11 legitimately calls this on what the server still
# calls yesterday, and because "start the plan from last Monday" is a real thing to ask for.
_START_DATE_BACKDATE_DAYS: Final = 7
_START_DATE_HORIZON_DAYS: Final = 365

# ⚠️ The full 17-row vocabulary — Kilian's decision 3 (2026-08-24), not an oversight. Every real
# user has **zero** `user_equipment` rows since issue #54 deleted the step that wrote them, so
# reading that table would hand the generator an empty set for everyone and thin every plan to
# its bodyweight options.
#
# The DOMAIN still takes the set as a parameter and is tested against `()`, so the
# gearless-shortfall machinery is real. **When the "I don't have access to this" flag lands, this
# constant is the ONE line that changes** — it is behind a name for exactly that reason.
_ASSUMED_EQUIPMENT_KEYS: Final[tuple[str, ...]] = tuple(sorted(spec.key for spec in EQUIPMENT))


# The partial unique index from `0008`. Named here so the 409 branch below matches on a
# constant rather than on a substring of a driver message.
_ONE_ACTIVE_INDEX: Final = "uq_plan_one_active_per_user"


def _today_utc() -> date:
    """The server's own date. The domain may not ask this question; this module may."""
    return datetime.now(UTC).date()


def _now_utc() -> datetime:
    """One instant per request, used for every timestamp the request writes.

    ⚠️ A Python value rather than the house default `func.now()`: this module's `POST` builds its
    response from the ORM objects it just inserted, and a column set to a SQL function is not
    readable from those without a per-row refresh — 200+ extra round trips to learn a timestamp
    we already know.

    Called once and passed down, so the plan being stood down and the plan being activated carry
    the same instant: no gap and no overlap in the handover.
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

        The order is deliberate: the bound judges the client's request, so it applies to the
        client's value. Normalising can then carry the start up to six days past the horizon —
        the server's own doing, and not a request to refuse.

        `week_start_on_or_after` is the domain's, so the edge and the generator's date maths
        cannot drift; `PlannerInput` re-asserts the Monday because an off-by-one here would move
        every session in the plan.
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
# ⚠️ These models serve BOTH `/preview` and the persisted routes, so
# `web/src/routes/_authed/plan.lazy.tsx` renders one tree with one renderer.
#
# The only difference is **which nullable fields are filled**: a preview is not a row, so
# everything only a row has is `null` — every `id`, a block's `exercise_id`, a session's
# `status`, the plan's `activated_at`. A persisted plan fills all of them; every other field has
# the same name and the same meaning on both paths.
#
# A nullable `id` rather than two model families is a real trade — it lets a client forget to
# check — and it is the cheaper one: the alternative is a second renderer for the same tree, and
# a second renderer is where the two drift.


class SetOut(BaseModel):
    """One prescribed set, straight off the `(exercise, phase)` prescription template.

    `target_load_kg` and `target_grade_id` are present and always `null` in v1.0.0, so the wire
    shape is stable when they are filled. Deriving a load is the one place a bodyweight figure
    could creep into a plan, which CLAUDE.md's weight rule forbids outright.

    The id is the point of the persisted response: the session player logs a `logged_set` against
    `prescribed_set.id`, so re-fetching to learn it would cost a round trip before the user could
    start.
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
    speaks keys, so a preview has the key and no id; a persisted block holds the id and the key is
    derived from it (`_exercise_reference`). Carrying both means the client's library lookup is
    written once for both paths.

    ⚠️ `aspect_key` is read LIVE off `exercise.climbing_aspect_id` and can therefore drift, unlike
    the snapshotted `protocol_kind` — an accepted asymmetry, recorded on `models.py::SessionBlock`.
    It is also **not** `shortfall.aspect_key`, which names the aspect the generator *wanted* and
    could not fill — precisely why a block's shortfall has to be stored rather than derived.
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

    `status` is `null` on a preview: a preview has no lifecycle, and inventing `planned` would
    make "not a row yet" and "a row nobody has started" the same answer.

    `shortfalls` here are the slots that produced **no block at all**. Stored, not derived —
    nothing in the tree records a slot that was never filled.
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

    Flattening the tree here would drop the phase spans the `/plan` timeline draws.
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


class ClimbingBandOut(BaseModel):
    """The training constants THIS plan was generated under. Derived, never stored.

    ⚠️ **Keyed off `generator_input.current_ordinal`, never off the profile's grade today.**
    `Level` is not persisted (`server/domain/planner/climbing.py`), and it is what
    `CLIMBING_FLOOR_PCT`, `CLIMBING_TARGET_PCT` and `FINGER_SESSIONS_PER_WEEK` were read
    with when the tree was built. A climber who logs a harder grade tomorrow has not changed
    the plan in front of them, so a band re-derived from the profile would make the payload
    misdescribe its own contents.

    Sent so **no client re-implements a training constant**: the ordinal thresholds are four
    named ceilings in one Python module, and re-deriving them in TypeScript would put the
    same numbers in two languages with nothing able to see them drift.

    `finger_phases` is the set those sessions are owed in, so a client can place the figure
    without knowing which phases they are; `finger_sessions_per_week` is **0 for beginner**
    by design, and a renderer must omit the line rather than print a zero.
    """

    level: Level
    climbing_floor_pct: int
    climbing_target_pct_low: int
    climbing_target_pct_high: int
    finger_sessions_per_week: int
    finger_phases: list[Phase]


def _climbing_band(
    discipline: Discipline, stored_generator_input: dict[str, Any]
) -> ClimbingBandOut | None:
    """Every figure through the function that owns it, so not one number is restated here.
    `None` on an unusable ordinal — `_grade_gap`'s degrade rule: a reload must not 500."""
    current = stored_generator_input.get("current_ordinal")
    if not isinstance(current, int):
        return None
    target_low, target_high = climbing_target_band(discipline, current)
    return ClimbingBandOut(
        level=level_for(discipline, current),
        climbing_floor_pct=climbing_floor_pct(discipline, current),
        climbing_target_pct_low=target_low,
        climbing_target_pct_high=target_high,
        # Asked for in a phase that owes the work, so the band's own figure comes back rather
        # than the zero every non-finger phase would answer with.
        finger_sessions_per_week=finger_sessions_for(discipline, current, Phase.STRENGTH),
        finger_phases=[member for member in Phase if member in FINGER_PHASES],
    )


class PlanOut(BaseModel):
    """A whole plan — previewed or persisted — plus what would be needed to reproduce it.

    `generator_input` is the canonical JSON of the `PlannerInput` actually used, plus
    `generator_version` and `library_digest`. That digest is load-bearing:
    `server/models.py::Plan` promises that re-running a version on the same input reproduces the
    tree, and **the library is a third input** — without it the promise is silently false the
    first time content is edited.

    ⚠️ `target_grade_id` and `current_grade_id` are set by this MODULE and are always `None` on
    the blueprint, because `PlannerInput` carries ordinals and the domain never sees a `grade.id`.
    Both are real `plan` columns (`0008`), so both survive a reload — the profile's current grade
    drifts as the climber improves and nothing else recovers what the plan was built from.

    `grade_gap` is derived on the persisted path rather than stored; see `_grade_gap`.

    ⚠️ **Size against the PERSISTED response, not the preview** (figures in PR #11b): the raw
    bytes are identical for the same tree, but gzipped the persisted body is ~1.9x, because
    thousands of repeated `null` ids compress away and distinct integers do not. If it ever bites,
    the lever is trimming sets beyond the first N weeks, not splitting the endpoint.
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

    # mypy cannot see through a decorator stacked on `@property`; pydantic's own docs use
    # exactly this ignore. The RETURN type is still checked, which is the part that matters.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def climbing_band(self) -> ClimbingBandOut | None:
        """Computed on serialisation, on both paths, from fields already on this model —
        which is why a persisted plan and a preview cannot disagree about it."""
        return _climbing_band(self.discipline, self.generator_input)


def _unprocessable(detail: str) -> HTTPException:
    """A well-formed request against stored state no plan can be built from.

    Matches `server/profile/routes.py::_unprocessable`. The client holds the profile and decides
    whether to ask at all, so this is defence in depth, and it invents no error-code vocabulary.
    """
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _planner_input(session: Session, user_id: int, start_date: date) -> PlannerInput:
    """The profile, resolved into the generator's input. Two statements, no writes.

    The four NULL refusals are raised here (see the module docstring), as `CannotPlanError` rather
    than `HTTPException`, so the route has one mapping site for all six reasons.

    ⚠️ `user_id` comes from the token and from nowhere else.

    The four grade/aspect lookups are outer JOINs rather than follow-up selects: primary-key reads
    of tiny seeded tables, and every extra round trip is Neon awake time.
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

    `PlannerInput` carries ordinals, so `generate()` leaves both `None`. Set here rather than
    `dataclasses.replace`d onto the blueprint, because adding ids to the input would give the
    domain a value it has no use for and would put them in the reproducibility digest.
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

    Enforced three ways rather than asserted: the generator is pure (ruff `TID251` in
    `server/domain/.ruff.toml`), this handler issues only `SELECT`s, and for a demo principal
    `SET LOCAL transaction_read_only` is already on, so Postgres itself would refuse.
    `tests/test_plans_api.py` counts rows after a successful preview.
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
# Four fields the persisted response would otherwise lack, and where each comes from:
#
# - the plan's `shortfalls` and `notes`, a session's `shortfalls`, a block's `shortfall` —
#   **stored**, as `plan.generator_caveats` (`0008`). Without them the `/plan` screen loses every
#   equipment-gap banner on reload; the plan is still complete (a shortfall is never a gate), but
#   a plan that silently stops explaining itself is worse than one that never did.
# - `grade_gap` — **derived** from `generator_input`'s two ordinals (`_grade_gap`).
# - `aspect_key` and `exercise_key` — **derived** from `_exercise_reference`, the second carried
#   next to `exercise_id` rather than replaced by it.
#
# ⚠️ One column for all four caveat kinds, not four, and not one each on `plan`,
# `planned_session` and `session_block`. They are ONE fact — what the generator said about the
# plan it built — written by one statement, read by one screen, and **never queried inside**, the
# same argument `plan.generator_input` is `jsonb` for. Per-row columns would have put ~2,400
# mostly-NULL jsonb values in `session_block` to record a handful of caveats.


def _session_key(week_no: int, weekday: int) -> str:
    return f"{week_no}.{weekday}"


def _block_key(week_no: int, weekday: int, order_index: int) -> str:
    return f"{week_no}.{weekday}.{order_index}"


# ⚠️ **A coordinate, not a row id, and not a position.** A caveat is written by the same INSERT
# that creates the plan row, long before any `session_block.id` exists. So the key is the node's
# natural key within the plan, and all three levels are already enforced UNIQUE by the schema —
# `microcycle (plan_id, week_no)`, `planned_session (microcycle_id, weekday)`,
# `session_block (planned_session_id, order_index)` — which is what makes it a key rather than a
# convention. A list index would mis-attach silently the day an `order_by` changed.
#
# The version is bumped when this module changes what it WRITES, and deliberately never branched
# on when reading: it tells you a blob is old, not whether it parses, and the read path validates
# the blob itself.
_CAVEATS_SHAPE_VERSION: Final = 1


class _StoredCaveats(BaseModel):
    """`plan.generator_caveats`, in both directions. **Private to this module.**

    ⚠️ **The read path degrades and never 500s.** Every field has a default, and anything this
    module does not recognise — a `Shortfall` that gained a required field, a retired `Phase`, a
    hand-edited row, a `null`, a list where a dict belongs — is treated as **"no caveats"**. A
    plan somebody is halfway through must not become unreadable because a dataclass in
    `server/domain/planner/blueprint.py` changed shape.

    Unknown keys are IGNORED rather than rejected (Pydantic's default, left alone on purpose), so
    a newer writer's blob still parses for an older reader — the other half of the same property.
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

    Whole-table rather than filtered to this plan's ids: the table is seeded reference data of a
    hundred-odd rows, and building an `IN (...)` first would mean walking the 2,400-node tree
    twice.

    Retired exercises are INCLUDED, on purpose: a plan generated before a retirement still points
    at the row, and keeping an old plan resolvable to a name is why `retired_at` exists instead of
    a DELETE.
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

    Derived rather than stored: both ordinals are already on the row inside the reproducibility
    record, so a column would be a third copy of one fact and the copy that drifts. Joining the
    two nullable grade *ids* to `grade.ordinal` is the other route and is not used — the ordinals
    are what the generator actually consumed.

    Same degrade rule as `_StoredCaveats`: unrecognised ordinals yield **0**, never a 500.
    """
    target = stored_generator_input.get("target_ordinal")
    current = stored_generator_input.get("current_ordinal")
    if isinstance(target, int) and isinstance(current, int):
        return target - current
    return 0


class ActivePlanResponse(BaseModel):
    """`{"plan": null}` when there is none — a **200**, not a 404.

    "No plan yet" is the state every new account is in, and the `/plan` screen renders it as an
    ordinary view with a Generate button. A 404 would make the normal case an error at three
    layers that all treat 4xx as failure: `apiFetch` throws, the query retry predicate skips 4xx
    as unwinnable, and a route-level guard would see `data === undefined` and swap itself for a
    fallback.

    A wrapper object rather than a bare nullable body, so the endpoint can grow a sibling field
    without changing shape and no client has to handle a top-level `null`.
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

    That statement is `_exercise_reference`, issued once per response rather than once per block,
    and it is what buys `exercise_key` and `aspect_key` on a block with no column for either. Used
    by both `POST ""` and `GET /active`, so a created plan and a reloaded one are byte-identical.
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


# "Active", once, as criteria rather than as a query: the READ needs a `select` and the
# stand-down needs an `update`, so a shared `select` would serve only one of them.
#
# ⚠️ **Kept character-identical** to `uq_plan_one_active_per_user`'s predicate and to
# `server/models.py::Plan`. The index can only refuse a second active row, so if this criterion
# and that predicate disagreed the index would keep passing while the app stopped agreeing with
# it. Pinned by
# `tests/test_plans_persist.py::test_the_ACTIVE_CRITERION_and_the_INDEX_PREDICATE_cannot_drift`,
# which reads the predicate back out of `pg_indexes`.
_ACTIVE_STATE: Final = (
    Plan.activated_at.is_not(None),
    Plan.abandoned_at.is_(None),
    Plan.completed_at.is_(None),
)


def _active_plan_query(user_id: int) -> Select[tuple[Plan]]:
    """This user's active plan. See `_ACTIVE_STATE`."""
    return select(Plan).where(Plan.user_id == user_id, *_ACTIVE_STATE)


# One SELECT per level rather than one wide join: a join down five 1:N edges repeats every
# ancestor's columns on every leaf row, and round trips are the cheap axis here (six statements
# in one transaction is one Neon wake either way). The relationships already declare `order_by`.
_PLAN_TREE: Final = (
    selectinload(Plan.mesocycles)
    .selectinload(Mesocycle.microcycles)
    .selectinload(Microcycle.planned_sessions)
    .selectinload(PlannedSession.blocks)
    .selectinload(SessionBlock.prescribed_sets)
)


def _exercise_ids(session: Session, blueprint: PlanBlueprint) -> dict[str, int]:
    """Every `exercise_key` in the tree, resolved to an id in ONE statement.

    The `server/contentseed.py::_ids_by_key` idiom. A generated plan draws on a few dozen distinct
    keys however many thousand sets it has, so this is one `WHERE key IN (...)` regardless of
    plan length.

    ⚠️ **A missing key raises: an ASSERTION, not a fallback.** Both alternatives are worse than a
    500 — a NULL `exercise_id` is refused by the column, and skipping the block silently ships a
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

    "An ORM flush emits one INSERT per row" is false on this dialect. Cited against the installed
    SQLAlchemy 2.0.52, because an uncited claim about a library's behaviour is how the last three
    review rounds each found a bug:

    - `orm/persistence.py:1086-1146` (`_emit_insert_statements`): with no client-side primary key,
      `implicit_returning` true and more than one record in the group, it consults
      `dialect.insert_executemany_returning_sort_by_parameter_order` and, when true, sets
      `do_executemany`, adds `return_defaults(*table.primary_key, sort_by_parameter_order=...)`
      and issues **one** `connection.execute(statement, multiparams)` per group.
    - `dialects/postgresql/base.py:3320` sets `use_insertmanyvalues = True`;
      `engine/default.py:395-430` derives both `insert_executemany_returning*` flags from it;
      `dialects/postgresql/psycopg.py:467-473` is the only thing that clears them, and only for a
      server <= 8.2.
    - `engine/default.py:245` — `insertmanyvalues_page_size = 1000`, so ~2,400 `prescribed_set`
      rows are **3** statements, not 2,400.
    - `orm/mapper.py:2765` (`_insert_cols_as_none`) + `orm/persistence.py:368-380`: a non-bulk
      flush adds an explicit `None` for every column with no default and no server default, so
      every instance of a mapper has the same parameter-key set — which matters because
      `persistence.py:1003-1015` groups records with `itertools.groupby` on that key set, and
      `groupby` only groups *consecutive* runs, so alternating shapes fragment one executemany.

    So the flush is ~6 statements per level, the ids come back in `RETURNING`, and the response is
    built from the objects with no re-read. ⚠️ **`status`, `activity_kind` and `is_deload` are
    passed explicitly despite having server defaults**, for two reasons from those citations: a
    `server_default` column is not in `_insert_cols_as_none`, so setting it on some rows and not
    others is the fragmentation `groupby` punishes; and an unset server default comes back
    expired, which the serialiser would refresh one row at a time.

    ## ⚠️ THE GRAPH MUST BE ATTACHED THROUGH THE COLLECTION, NOT THE CHILD'S PARENT

    `Mesocycle(plan=plan, ...)` persists the plan row and **silently drops every one of its
    ~2,400 descendants** — a `201`, a committed transaction, and one `SAWarning`. It shipped in
    the first draft and was caught by running it, not by reading it.

    `orm/unitofwork.py::track_cascade_events` is why: its `append` listener runs the save-update
    cascade only when `prop._cascade.save_update and (key == initiator.key) and not
    sess._contains_state(item_state)`. `initiator.key` is the attribute the caller actually
    mutated, so the backref's `append` on `plan.mesocycles` arrives with `initiator.key == "plan"`
    and cascades nothing. (That gate **is** the `cascade_backrefs` behaviour SQLAlchemy 2.0
    removed; the warning comes from `orm/dependency.py:840-848`.) Appending to `plan.mesocycles`
    directly passes it, and `session.py:3512-3518` then walks
    `mapper.cascade_iterator("save-update", ...)` recursively over the whole subtree.

    ⚠️ **Nothing in the schema requires a plan to have a mesocycle**, so no constraint catches
    this — only a row count across all six tables does.

    Two flushes, and the first is not avoidable: `microcycle.plan_id` is a **denormalised** column
    with no relationship behind it (the composite FK is what makes it safe), so SQLAlchemy will
    not populate it, and `plan.id` does not exist until the plan row is inserted.
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
        # Written rather than derived on the way out, because a block's shortfall names the
        # aspect the generator WANTED and could not fill, which no persisted row records.
        generator_caveats=_stored_caveats(blueprint),
        activated_at=activated_at,
        # Initialised empty so the collection counts as LOADED: otherwise the first
        # `plan.mesocycles.append(...)` below lazy-loads it — one extra round trip, guaranteed
        # to return zero rows.
        mesocycles=[],
    )
    session.add(plan)
    # Separate only because `microcycle.plan_id` needs `plan.id`; see the docstring.
    session.flush()

    # ⚠️ Built BOTTOM-UP and attached through the COLLECTION, never through the child's parent
    # attribute: the child-side form loses the whole subtree and only warns. See the docstring.
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
                    # `(mesocycle_id, plan_id) -> mesocycle (id, plan_id)` ties back. No
                    # relationship exists for SQLAlchemy to populate it from, so omitting it is
                    # not a NULL — it is a failed insert.
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

    **The invariant, and why there is no separate "switch" endpoint:** the transaction that
    activates one plan is the transaction that stands the other down.
    `uq_plan_one_active_per_user` can only refuse a second active row, not decide which survives,
    so without this the second activation would simply 409.

    ⚠️ Runs BEFORE the insert. The index is not deferrable, so it is checked per statement and the
    old row has to leave the predicate before the new one enters it.
    """
    session.execute(
        update(Plan).where(Plan.user_id == user_id, *_ACTIVE_STATE).values(abandoned_at=at)
    )


def _constraint_name(error: IntegrityError) -> str | None:
    """psycopg3's `Diagnostic.constraint_name` — the index name for a unique violation.

    Read structurally rather than from a substring of the driver's message, and it is the ONLY
    part of an `IntegrityError` this module may keep: see `create_plan`.
    """
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


def _is_one_active_conflict(error: IntegrityError) -> bool:
    """Was this the one-active-plan index, or something else?

    Anything else — a foreign key, a CHECK, an unknown index — is a real 500 and must not be
    reported to the client as "you already have a plan".
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

    A **Tier-1 write**: one request, one transaction, one Neon wake.

    **The server regenerates; it never accepts a tree.** The body is `PlanPreviewRequest` —
    `start_date` and nothing else, `extra="forbid"`. A client-supplied tree would let any caller
    fabricate an arbitrary plan, prescriptions against exercises their injuries contraindicate
    included, and it would be a ~600 KiB request body. `user_id` comes from `principal.user_id`
    and from nowhere else. The generation path is the preview's, reused rather than reimplemented,
    so a plan can never be persisted in a shape the preview would not have shown.

    **One transaction, all-or-nothing.** Four steps, one `commit()` at the end (each route commits
    itself; `get_session` deliberately does not): stand the active plan down, resolve every
    `exercise_key`, insert the tree, serialise. A failure anywhere leaves zero rows in all six
    tables, because nothing before the `commit()` is durable.

    **409 is a legitimate answer, not a fault.** A double-tap races: both requests stand the same
    plan down and both insert, and the second trips `uq_plan_one_active_per_user`. The user does
    have an active plan, so the client treats it as "you already have one" and refetches.
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
        # Serialise BEFORE committing: the objects are still fully populated here.
        body = _plan_response(session, plan)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if _is_one_active_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have an active plan.",
            ) from error
        # ⚠️ **Never re-raised: input minimisation applies to the LOG.**
        # `str(IntegrityError)` carries the failing statement *and its bound parameters* — on the
        # `plan` INSERT that is `generator_input` and `generator_caveats`, i.e. the climber's
        # open-injury keys. So only the constraint name and plan-level metadata are logged, and
        # `from None` drops the chained traceback so the parameters cannot come back through the
        # renderer either.
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

    `.one_or_none()` rather than `.first()`: "at most one" is `uq_plan_one_active_per_user`'s job,
    and if the index were ever dropped a silent `LIMIT 1` would hide that while quietly picking an
    arbitrary plan.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    plan = session.scalars(_active_plan_query(principal.user_id).options(_PLAN_TREE)).one_or_none()
    return ActivePlanResponse(plan=None if plan is None else _plan_response(session, plan))


@router.post("/{plan_id}/abandon")
def abandon_plan(
    plan_id: int, principal: CurrentUser, session: RequestSession, response: Response
) -> PlanAbandonResponse:
    """Stand a plan down. **Marks, never deletes.** Idempotent, and 404 for anyone else's.

    **A timestamp and not a delete**, because `activity.planned_session_id` is the only link from a
    logged activity to the plan it satisfied: deleting would cascade through the tree and destroy
    the adherence record of sessions the user really did.

    **The 404 is scoped, and the scoping is the security property.** The `WHERE` names both the id
    and `principal.user_id`, so another user's plan is indistinguishable from one that never
    existed. A 403 would confirm the row exists — the IDOR read this project treats as its real
    extraction risk.

    **Idempotent:** an already-abandoned plan keeps its original timestamp, because *when* it was
    stood down is the fact the diary wants. `completed_at` is deliberately untouched.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    # ⚠️ Scoped by id and user, deliberately NOT by `_ACTIVE_STATE`: today this endpoint is the
    # only way to leave the active set, so "abandon a plan that is not active" is unreachable.
    # **The first path that COMPLETES a plan makes it reachable**, and this would then stamp
    # `abandoned_at` on a completed plan. Add the guard with that path — a guard now would be an
    # untestable branch.
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
