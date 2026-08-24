"""The generated plan as plain frozen dataclasses — the shape before it is a row or JSON.

Mirrors `Plan -> Mesocycle -> Microcycle -> PlannedSession -> SessionBlock -> PrescribedSet`
field for field, with the departures listed below. Dataclasses rather than Pydantic so the
domain gains no dependency on the API layer; `server/plans/routes.py` maps these to response
models by hand, the same stitching `server/library/routes.py` does for the library.

## The five documented departures from the persisted tree

1. **No ids and no back-references.** The tree is nested, so parentage is structural.
   `Microcycle.plan_id`'s denormalisation and its composite foreign key are an insert-time
   concern for PR #11b, not something a preview can express.
2. **`exercise_key`, not `exercise_id`.** The domain is DB-free and speaks keys; the client
   already holds `key` from `useLibrary()`, and it saves a `SELECT`. #11b resolves keys to
   ids at persist time.
3. **`PlannedSession.status` omitted.** A preview has no status. #11b takes the column's
   `'planned'` default rather than sending one over the wire.
4. **⚠️ `rest_between_sets_seconds` has no home in the persisted tree.**
   `prescription_template` has it, but `session_block` has only `rest_after_seconds` (rest
   *after* the block) and `prescribed_set` only `target_rest_seconds` (rest *within* a set).
   The blueprint carries the template's value so the preview is honest about what it
   prescribes; **#11b needs a new column or a redefinition**, and taking that decision now
   beats discovering it mid-insert.
5. **`target_load_kg` / `target_grade_id` are present and always `None` in v1.0.0.** The
   wire shape stays stable for when they are filled, and deriving a load is the one place a
   bodyweight figure could creep into a prescription (CLAUDE.md, "never recommends losing
   weight").

## What `__post_init__` checks, and what it deliberately does not

Only a **schema CHECK**. A blueprint that could not be inserted is worth failing on in the
generator's own tests rather than in #11b's first bulk insert. `String(80)` limits are NOT
checked here: they are a column width, not a CHECK, and the safety guard already asserts
every generated string fits — duplicating it would turn that guard's red into a traceback
from a constructor, which is a worse failure to read.
"""

import enum
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from server.domain.grades import Discipline
from server.domain.vocabulary import ActivityKind, Phase, ProtocolKind

# `ck_plan_week_count_in_range`. The upper bound is why `MAX_BLOCKS` exists at all.
MIN_WEEK_COUNT: Final = 1
MAX_WEEK_COUNT: Final = 52


class NoteKind(enum.StrEnum):
    """Why a plan carries a note. Closed, so the client can style or order them.

    A note is **never a gate**: the plan is complete and nothing is disabled. It exists so
    that a plan which is not quite what was asked for says so, in the plan, instead of
    leaving the user to notice.
    """

    FEWER_SESSIONS_THAN_REQUESTED = "fewer_sessions_than_requested"
    TARGET_BEYOND_ONE_PLAN = "target_beyond_one_plan"


@dataclass(frozen=True, slots=True)
class ScheduleNote:
    """One honest caveat about the plan as a whole. `kind` is the contract, `message` is copy."""

    kind: NoteKind
    message: str


@dataclass(frozen=True, slots=True)
class Shortfall:
    """An aspect this phase cannot train with the gear the climber has, and what would fix it.

    `options` is the minimal set of equipment combinations that would unlock the cell: each
    inner tuple is an AND set, and the outer tuple is the OR. It names **equipment rows
    only** — never a movement substitute, never an improvised edge (CLAUDE.md, the
    finger-loading safety boundary), which is why `substitution_hint` is not read here.

    Attached to the block it displaced and rolled up, deduped by `(phase, aspect_key)`, to
    the plan. Never a gate.
    """

    phase: Phase
    aspect_key: str
    options: tuple[tuple[str, ...], ...]
    message: str


@dataclass(frozen=True, slots=True)
class SetBlueprint:
    """One prescribed set. `prescribed_set` minus its ids."""

    set_index: int
    target_reps: int | None = None
    target_work_seconds: int | None = None
    target_rest_seconds: int | None = None
    target_intensity_pct: int | None = None
    target_rpe: int | None = None
    target_load_kg: Decimal | None = None
    target_grade_id: int | None = None

    def __post_init__(self) -> None:
        if self.set_index < 1:
            raise ValueError(
                f"set_index is 1-based (ck_prescribed_set_set_index_positive), "
                f"got {self.set_index}."
            )
        if self.target_rpe is not None and not 1 <= self.target_rpe <= 10:
            raise ValueError(
                f"target_rpe is 1-10 (ck_prescribed_set_target_rpe_in_range), "
                f"got {self.target_rpe}."
            )
        if self.target_intensity_pct is not None and not 1 <= self.target_intensity_pct <= 200:
            raise ValueError(
                f"target_intensity_pct is 1-200 (ck_prescribed_set_target_intensity_pct_sane), "
                f"got {self.target_intensity_pct}."
            )


@dataclass(frozen=True, slots=True)
class BlockBlueprint:
    """One exercise in one session. `protocol_kind` is snapshotted, as `session_block` does.

    `shortfall` is set when this block's aspect was **displaced** — the slot's intended
    aspect had no prescribable candidate, so the next emphasis entry that did was used and
    the miss is recorded on the block that replaced it.
    """

    order_index: int
    exercise_key: str
    aspect_key: str
    protocol_kind: ProtocolKind
    sets: tuple[SetBlueprint, ...]
    rest_after_seconds: int | None = None
    # Departure 4: carried so the preview is honest, with nowhere to persist it yet.
    rest_between_sets_seconds: int | None = None
    shortfall: Shortfall | None = None


@dataclass(frozen=True, slots=True)
class SessionBlueprint:
    """One prescribed session on one day. `weekday` is 0-6, Monday = 0.

    `blocks` may be empty in exactly one case, and it is documented rather than prevented:
    zero equipment with every injury area open leaves no safe candidate at all, so the
    session becomes `activity_kind=other` with a shortfall naming the injuries. The
    invariant is never an *unexplained* empty session.
    """

    weekday: int
    scheduled_on: date
    activity_kind: ActivityKind
    title: str
    estimated_minutes: int | None
    blocks: tuple[BlockBlueprint, ...]
    shortfalls: tuple[Shortfall, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.weekday <= 6:
            raise ValueError(
                f"weekday is 0-6 with Monday = 0 (ck_planned_session_weekday_in_range), "
                f"got {self.weekday}."
            )
        if self.scheduled_on.weekday() != self.weekday:
            raise ValueError(
                f"scheduled_on {self.scheduled_on} is a {self.scheduled_on.strftime('%A')} "
                f"but weekday says {self.weekday}. `planned_session` stores both and nothing "
                f"in the schema keeps them in agreement, so the generator has to."
            )


@dataclass(frozen=True, slots=True)
class MicrocycleBlueprint:
    """One week. `phase` is the parent mesocycle's, denormalised the way the read path wants it.

    `is_deload` is exactly `phase is Phase.DELOAD` and nothing cleverer — a taper is
    identified by its phase, not by this flag, because a taper is not a deload.
    """

    week_no: int
    start_date: date
    is_deload: bool
    phase: Phase
    sessions: tuple[SessionBlueprint, ...]

    def __post_init__(self) -> None:
        if self.week_no < 1:
            raise ValueError(
                f"week_no is 1-based (ck_microcycle_week_no_positive), got {self.week_no}."
            )
        if self.start_date.weekday() != 0:
            raise ValueError(f"a microcycle starts on a Monday; {self.start_date} does not.")


@dataclass(frozen=True, slots=True)
class MesocycleBlueprint:
    """A phase block. `start_week` / `end_week` are 1-based and inclusive, as the column is."""

    phase: Phase
    start_week: int
    end_week: int
    microcycles: tuple[MicrocycleBlueprint, ...]

    def __post_init__(self) -> None:
        if self.start_week < 1:
            raise ValueError(
                f"start_week is 1-based (ck_mesocycle_start_week_positive), got {self.start_week}."
            )
        if self.end_week < self.start_week:
            raise ValueError(
                f"end_week {self.end_week} precedes start_week {self.start_week} "
                f"(ck_mesocycle_end_week_after_start)."
            )


@dataclass(frozen=True, slots=True)
class PlanBlueprint:
    """A whole generated plan. The root the endpoint serialises and #11b inserts.

    `shortfalls` is the plan-level roll-up, deduped by `(phase, aspect_key)` from the blocks;
    `notes` is everything the plan wants to say about itself. Both may be empty, and an empty
    one is the normal case for a well-equipped climber with enough days.
    """

    name: str
    discipline: Discipline
    target_grade_id: int | None
    current_grade_id: int | None
    start_date: date
    week_count: int
    grade_gap: int
    mesocycles: tuple[MesocycleBlueprint, ...]
    shortfalls: tuple[Shortfall, ...] = ()
    notes: tuple[ScheduleNote, ...] = ()

    def __post_init__(self) -> None:
        if not MIN_WEEK_COUNT <= self.week_count <= MAX_WEEK_COUNT:
            raise ValueError(
                f"week_count must be {MIN_WEEK_COUNT}-{MAX_WEEK_COUNT} "
                f"(ck_plan_week_count_in_range), got {self.week_count}."
            )
        if self.start_date.weekday() != 0:
            raise ValueError(f"a plan starts on a Monday; {self.start_date} does not.")
