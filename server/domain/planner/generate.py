"""`generate()` — a `PlannerInput` in, a whole `PlanBlueprint` out, and nothing else.

Pure: no DB, no clock, no RNG, no I/O. Every varying quantity is a function of
`(week_no, session_index)`, which is the promise `server/models.py::Plan` makes and the reason
`generator_input` folds `library_digest()` in beside the version.

Four invariants, in priority order. (1) **Nothing non-deterministic reaches the output** — no
`random`, no `secrets`, no `hash()`, no set iteration; `server/domain/.ruff.toml` bans the
imports and `tests/test_planner_reproducibility.py` is the check. (2) **A contraindicated
exercise is never prescribed** — `prescribable()` never relaxes the injury filter, which is why
(4) exists. (3) **Never an *unexplained* empty session** — an unfillable slot is displaced to
the next aspect in `ASPECT_EMPHASIS`, carrying a `Shortfall` naming what would open the
original. (4) The one honest exception: nothing available and every injury area open leaves no
aspect in `power_endurance` or `performance`, so the session becomes `activity_kind=other`,
"Recovery", with a shortfall per empty slot. Explained, therefore allowed.

⚠️ Every string built here is user facing and two hard rules bind all of them: **never suggest
losing weight** (there is no bodyweight figure in this module, which is also why
`target_load_kg` stays `None`) and **never suggest improvising finger loading** (a shortfall
names equipment rows; `substitution_hint` is deliberately not read here).
`tests/test_planner_safety.py` asserts both against every string a plan can produce.

`estimated_minutes` is arithmetic, not a guess: prescribed seconds (work or
`reps * SECONDS_PER_REP`, plus rests) over 60, ceiled, plus `WARMUP_MINUTES` — which is not a
prescribed block, because a block would make warming up skippable. No blocks means `None`.
`target_grade_id`/`current_grade_id` are `None` here: `PlannerInput` carries **ordinals**, so
only the route that read those rows knows their ids.
"""

import math
from typing import Final

from server.domain.exercises import ExerciseSpec, PrescriptionSpec
from server.domain.planner.blueprint import (
    BlockBlueprint,
    MesocycleBlueprint,
    MicrocycleBlueprint,
    PlanBlueprint,
    ScheduleNote,
    SessionBlueprint,
    SetBlueprint,
    Shortfall,
)
from server.domain.planner.contract import PlannerInput
from server.domain.planner.periodisation import (
    beyond_one_plan_note,
    block_count_for,
    mesocycle_spans,
    week_count_for,
)
from server.domain.planner.schedule import (
    choose_weekdays,
    fewer_sessions_note,
    microcycle_start,
    session_date,
)
from server.domain.planner.selection import (
    ASPECT_EMPHASIS,
    ASPECT_NAMES,
    BLOCKS_PER_SESSION,
    SUPPORT_ASPECTS,
    candidates,
    prescribable,
    shortfall_message,
    unlock_options,
)
from server.domain.vocabulary import ActivityKind, Phase

WARMUP_MINUTES: Final = 15
SECONDS_PER_REP: Final = 4

_RECOVERY_TITLE: Final = "Recovery"


def generate(planner_input: PlannerInput) -> PlanBlueprint:
    """Build the whole plan. Raises `CannotPlanError` only for an empty weekday mask."""
    gap = planner_input.grade_gap
    week_count = week_count_for(gap)
    weekdays = choose_weekdays(planner_input.available_weekdays, planner_input.sessions_per_week)

    mesocycles = tuple(
        MesocycleBlueprint(
            phase=span.phase,
            start_week=span.start_week,
            end_week=span.end_week,
            microcycles=tuple(
                _microcycle(planner_input, span.phase, week_no, weekdays)
                for week_no in range(span.start_week, span.end_week + 1)
            ),
        )
        for span in mesocycle_spans(block_count_for(gap))
    )

    return PlanBlueprint(
        name=f"{week_count}-week {planner_input.discipline.value} plan",
        discipline=planner_input.discipline,
        target_grade_id=None,
        current_grade_id=None,
        start_date=planner_input.start_date,
        week_count=week_count,
        grade_gap=gap,
        mesocycles=mesocycles,
        shortfalls=_rolled_up(mesocycles),
        notes=_notes(planner_input, scheduled=len(weekdays), gap=gap),
    )


def _notes(planner_input: PlannerInput, *, scheduled: int, gap: int) -> tuple[ScheduleNote, ...]:
    """Everything the plan says about itself. Never a gate — the plan is complete either way."""
    possible = (
        fewer_sessions_note(requested=planner_input.sessions_per_week, scheduled=scheduled),
        beyond_one_plan_note(gap),
    )
    return tuple(note for note in possible if note is not None)


def _microcycle(
    planner_input: PlannerInput, phase: Phase, week_no: int, weekdays: tuple[int, ...]
) -> MicrocycleBlueprint:
    """One week. The weekday set is the plan's, every week — only the rotation moves."""
    week_start = microcycle_start(planner_input.start_date, week_no)
    return MicrocycleBlueprint(
        week_no=week_no,
        start_date=week_start,
        is_deload=phase is Phase.DELOAD,
        phase=phase,
        sessions=tuple(
            _session(planner_input, phase, week_no, session_index, weekday)
            for session_index, weekday in enumerate(weekdays)
        ),
    )


def _session(
    planner_input: PlannerInput,
    phase: Phase,
    week_no: int,
    session_index: int,
    weekday: int,
) -> SessionBlueprint:
    """Three slots, filled in order, each displaced rather than dropped where it can be."""
    emphasis = ASPECT_EMPHASIS[phase]
    used: list[str] = []
    blocks: list[BlockBlueprint] = []
    unfilled: list[Shortfall] = []

    for slot in range(BLOCKS_PER_SESSION):
        intended = _intended_aspect(
            slot, emphasis, planner_input, week_no=week_no, session_index=session_index, used=used
        )
        if intended is None:
            continue
        filled = _fill_slot(
            intended,
            emphasis,
            planner_input,
            phase=phase,
            week_no=week_no,
            session_index=session_index,
            used=used,
        )
        shortfall = (
            None
            if filled is not None and filled[0] == intended
            else _shortfall(planner_input, phase, intended)
        )
        if filled is None:
            unfilled.append(_require(shortfall))
            continue
        aspect_key, spec = filled
        used.append(aspect_key)
        blocks.append(_block(len(blocks) + 1, spec, phase=phase, shortfall=shortfall))

    return SessionBlueprint(
        weekday=weekday,
        scheduled_on=session_date(microcycle_start(planner_input.start_date, week_no), weekday),
        # A slot-less session is the terminal all-injuries case. `other`, so adherence does
        # not read it as a climbing session nobody did.
        activity_kind=ActivityKind.CLIMBING if blocks else ActivityKind.OTHER,
        title=_title(blocks),
        estimated_minutes=_estimated_minutes(blocks) if blocks else None,
        blocks=tuple(blocks),
        shortfalls=tuple(unfilled),
    )


def _intended_aspect(
    slot: int,
    emphasis: tuple[str, ...],
    planner_input: PlannerInput,
    *,
    week_no: int,
    session_index: int,
    used: list[str],
) -> str | None:
    """What this slot is *for*, before the climber's gear and injuries are consulted.

    Slot 0 is the phase's defining quality — a quality leads its own block. Slot 1 is the
    **weakness bias**, and it is one printable sentence: your weakness appears in every
    session of every phase where it can be trained. "Where it can be trained" is the
    library's judgement (the phase prescribes that aspect at all), deliberately not the
    climber's gear — a weakness that needs a hangboard should surface as "here is what you
    would need", not vanish. Slot 2 rotates the support aspects.

    `UserAspectRating`'s eight scores are never read: since issue #54 they sit behind a
    disclosure and may be untouched defaults, while `weakness_aspect_id` is the answer to a
    direct question.
    """
    if slot == 0:
        return emphasis[0]
    if slot == 1:
        weakness = planner_input.weakness_aspect_key
        if weakness is not None and weakness in emphasis and weakness not in used:
            return weakness
        return _rotated(_secondary_pool(emphasis, planner_input, used), week_no - 1 + session_index)
    return _rotated(
        tuple(key for key in SUPPORT_ASPECTS if key not in used) or SUPPORT_ASPECTS,
        week_no + session_index,
    )


def _secondary_pool(
    emphasis: tuple[str, ...], planner_input: PlannerInput, used: list[str]
) -> tuple[str, ...]:
    """The rotation slot 1 falls back to, with the declared strength last.

    A strength is **maintained, never dropped** — it stays in the rotation and goes to the
    end of it, so it comes round less often than everything the climber is worse at.
    """
    pool = [key for key in emphasis if key not in used and key != planner_input.weakness_aspect_key]
    strength = planner_input.strength_aspect_key
    if strength in pool:
        pool.remove(strength)
        pool.append(strength)
    return tuple(pool)


def _rotated(pool: tuple[str, ...], offset: int) -> str | None:
    """Pick one, deterministically, by an offset that moves week to week and slot to slot."""
    if not pool:
        return None
    return pool[offset % len(pool)]


def _fill_slot(
    intended: str,
    emphasis: tuple[str, ...],
    planner_input: PlannerInput,
    *,
    phase: Phase,
    week_no: int,
    session_index: int,
    used: list[str],
) -> tuple[str, ExerciseSpec] | None:
    """Try `intended`, then walk the emphasis order for the next aspect that can be filled.

    The walk starts at `intended`'s own position and wraps, so displacement moves *down* the
    phase's priority order first — the nearest thing to what the slot was for.
    """
    start = emphasis.index(intended) if intended in emphasis else 0
    for step in range(len(emphasis)):
        aspect_key = emphasis[(start + step) % len(emphasis)]
        if aspect_key in used:
            continue
        ordered = prescribable(
            candidates(phase, aspect_key),
            discipline=planner_input.discipline,
            equipment_keys=planner_input.equipment_keys,
            open_injury_keys=planner_input.open_injury_keys,
        )
        if ordered:
            return aspect_key, ordered[(week_no - 1 + session_index) % len(ordered)]
    return None


def _shortfall(planner_input: PlannerInput, phase: Phase, aspect_key: str) -> Shortfall:
    """What the slot was for, and what would have let us prescribe it."""
    options = unlock_options(
        phase,
        aspect_key,
        discipline=planner_input.discipline,
        open_injury_keys=planner_input.open_injury_keys,
    )
    return Shortfall(
        phase=phase,
        aspect_key=aspect_key,
        options=options,
        message=shortfall_message(
            phase, aspect_key, options, open_injury_keys=planner_input.open_injury_keys
        ),
    )


def _block(
    order_index: int, spec: ExerciseSpec, *, phase: Phase, shortfall: Shortfall | None
) -> BlockBlueprint:
    """One exercise, with its prescription snapshotted the way `session_block` snapshots it."""
    prescription = _prescription_for(spec, phase)
    return BlockBlueprint(
        order_index=order_index,
        exercise_key=spec.key,
        aspect_key=spec.aspect_key,
        protocol_kind=spec.protocol_kind,
        sets=tuple(
            SetBlueprint(
                set_index=index,
                target_reps=prescription.reps,
                target_work_seconds=prescription.work_seconds,
                target_rest_seconds=prescription.rest_seconds,
                target_intensity_pct=prescription.intensity_pct,
                target_rpe=prescription.target_rpe,
            )
            for index in range(1, prescription.sets + 1)
        ),
        # No source: `prescription_template` authors no rest between BLOCKS, so v1.0.0
        # leaves it NULL rather than inventing a number, exactly as it does for
        # `target_load_kg`. Departure 4 in `blueprint.py` is the other half of this.
        rest_after_seconds=None,
        rest_between_sets_seconds=prescription.rest_between_sets_seconds,
        shortfall=shortfall,
    )


def _prescription_for(spec: ExerciseSpec, phase: Phase) -> PrescriptionSpec:
    """The authored row for this phase. `candidates()` already proved one exists."""
    for prescription in spec.prescriptions:
        if prescription.phase is phase:
            return prescription
    raise ValueError(
        f"{spec.key!r} has no prescription for {phase.value}, so selection should never "
        f"have offered it. This is a bug in server/domain/planner/selection.py."
    )


def _title(blocks: list[BlockBlueprint]) -> str:
    """The session's aspects, in prescribed order. Fits `String(80)` — the safety test checks.

    Deliberately not "Strength week 3": the microcycle already carries `phase` and
    `week_no`, and inventing display labels for `Phase` would be a second vocabulary for the
    client to disagree with. Comma-joined rather than "x, y and z" because two of the aspect
    names contain "and" themselves ("Core and tension"), and the list then reads as four.
    """
    if not blocks:
        return _RECOVERY_TITLE
    names = [ASPECT_NAMES[block.aspect_key] for block in blocks]
    return ", ".join([names[0], *(name.lower() for name in names[1:])])


def _estimated_minutes(blocks: list[BlockBlueprint]) -> int:
    """Prescribed seconds, rounded up, plus the warm-up nobody gets to skip."""
    seconds = sum(_block_seconds(block) for block in blocks)
    return math.ceil(seconds / 60) + WARMUP_MINUTES


def _block_seconds(block: BlockBlueprint) -> int:
    """Work plus rest, for every set and between them, plus any rest after the block."""
    per_set = sum(
        (item.target_work_seconds or (item.target_reps or 0) * SECONDS_PER_REP)
        + (item.target_rest_seconds or 0)
        for item in block.sets
    )
    between = max(len(block.sets) - 1, 0) * (block.rest_between_sets_seconds or 0)
    return per_set + between + (block.rest_after_seconds or 0)


def _rolled_up(mesocycles: tuple[MesocycleBlueprint, ...]) -> tuple[Shortfall, ...]:
    """Every shortfall in the tree, deduped by `(phase, aspect_key)`, first occurrence kept.

    Derived from the blocks rather than accumulated alongside them, so the plan-level list
    and the per-block notices cannot disagree.
    """
    seen: dict[tuple[Phase, str], Shortfall] = {}
    for mesocycle in mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                found = [
                    *(block.shortfall for block in session.blocks if block.shortfall is not None),
                    *session.shortfalls,
                ]
                for shortfall in found:
                    seen.setdefault((shortfall.phase, shortfall.aspect_key), shortfall)
    return tuple(seen.values())


def _require(shortfall: Shortfall | None) -> Shortfall:
    """An unfilled slot always has a shortfall — this makes that a type, not a comment."""
    if shortfall is None:
        raise ValueError("an unfilled slot must carry a shortfall; never an unexplained gap.")
    return shortfall
