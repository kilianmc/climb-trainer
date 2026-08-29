"""Which exercises can fill a (phase, aspect) cell — and, when none can, what would.

Pure and deterministic: every function is a filter over the authored order of `EXERCISES`, and
nothing iterates a set into its result. `candidates()` answers the library question (prescribed
in this phase for this aspect — no `PrescriptionSpec` for the phase means not prescribable in
it); `prescribable()` answers the user question, dropping a `discipline` that is set and
differs, then anything whose `contraindication_keys` meet an open injury, then anything whose
`equipment_keys` are not a subset of what the climber has (an AND set, so `()` always passes).
The survivors keep the library's authored order, which is the content decision.

Those three clauses are one conjunction, so their order cannot change *which* exercises
survive. ⚠️ What "safety outranks everything below it" buys is the rule for every future
change: **the equipment clause may be relaxed to explain a gap — `unlock_options()` does
exactly that — and the injury clause never is.** There is deliberately no parameter, flag or
fallback anywhere in this package that widens the pool by ignoring an injury.

`ASPECT_EMPHASIS` is authored data — one priority order per phase, most-defining quality first
— **validated at import in BOTH directions** against `DELIBERATELY_UNPRESCRIBED`: a cell the
library declines to prescribe may not appear (the generator would walk to an aspect with no
candidate in any circumstances), and every cell it does prescribe must (an omission silently
deletes an aspect from a phase, a content decision made by accident).
`tests/test_planner_selection.py` asserts the same agreement, so it is visible in a test run
and not only as an import error. A row lists the phase's **full** prescribable vocabulary in
priority order rather than a top three, because displacement walks it.
"""

from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from types import MappingProxyType
from typing import Final

from server.domain.exercises import DELIBERATELY_UNPRESCRIBED, EXERCISES, ExerciseSpec
from server.domain.grades import Discipline
from server.domain.planner.climbing import WALL_LED_ASPECTS, requires_wall
from server.domain.vocabulary import (
    CLIMBING_ASPECTS,
    EQUIPMENT,
    INJURY_AREAS,
    Phase,
    ProtocolKind,
)

# Primary + secondary + support. Three is what fits a session with a warm-up inside a
# training evening; it is also exactly the gearless floor the library actually meets in
# every phase (measured — see `tests/test_planner_gearless.py`), so a climber with no gear
# is never short of a slot to fill.
BLOCKS_PER_SESSION: Final = 3

# The third slot, rotated. These are the qualities that keep the pulling durable and the
# body able to hold a position; they are worth a slot in every phase and they are never the
# thing a phase is *about*, which is why they get their own rotation instead of competing
# for the first two slots.
SUPPORT_ASPECTS: Final[tuple[str, ...]] = ("antagonist_prehab", "mobility", "core_tension")

ASPECT_EMPHASIS: Final[Mapping[Phase, tuple[str, ...]]] = MappingProxyType(
    {
        # Base builds the capacity everything later spends: time on the wall first, then
        # the movement quality that makes that time useful, then tissue tolerance. Power
        # sits last because a base block is the one place it is genuinely not the point.
        Phase.BASE: (
            "endurance",
            "technique",
            "core_tension",
            "finger_strength",
            "antagonist_prehab",
            "mobility",
            "power_endurance",
            "power",
        ),
        # Fingers lead their own block — it is the slowest quality to build and the one the
        # rest of the plan is scheduled around. Power endurance is absent by authored
        # decision (`DELIBERATELY_UNPRESCRIBED`): it competes for the recovery the heavy
        # sessions need and comes back in weeks, where strength takes months.
        Phase.STRENGTH: (
            "finger_strength",
            "core_tension",
            "power",
            "technique",
            "endurance",
            "antagonist_prehab",
            "mobility",
        ),
        # Power leads, with fingers second because contact strength is what a power block
        # actually expresses. Power endurance is absent for the same one-sided-trade reason.
        Phase.POWER: (
            "power",
            "finger_strength",
            "core_tension",
            "technique",
            "endurance",
            "antagonist_prehab",
            "mobility",
        ),
        # Its own block, with aerobic endurance right behind it: the capacity underneath a
        # power-endurance session is what lets the next one happen two days later.
        Phase.POWER_ENDURANCE: (
            "power_endurance",
            "endurance",
            "technique",
            "core_tension",
            "finger_strength",
            "power",
            "antagonist_prehab",
            "mobility",
        ),
        # Performance is about performing, and the library expresses that as limit attempts
        # and redpoint burns — `power` first, `power_endurance` immediately after so a rope
        # climber whose weakness is stamina still leads with it through the weakness bias.
        Phase.PERFORMANCE: (
            "power",
            "power_endurance",
            "technique",
            "finger_strength",
            "core_tension",
            "endurance",
            "antagonist_prehab",
            "mobility",
        ),
        # A deload is a block with its own prescriptions, not a scaled one. What it is for
        # is movement quality and range at low load, so technique and mobility lead and the
        # maximal qualities sit at the end.
        Phase.DELOAD: (
            "technique",
            "mobility",
            "antagonist_prehab",
            "core_tension",
            "finger_strength",
            "endurance",
            "power_endurance",
            "power",
        ),
        # Sharpness comes from climbing on the target style, not from a board — the same
        # reasoning `DELIBERATELY_UNPRESCRIBED` gives for leaving isolated finger loading
        # and full power-endurance sessions out of a taper entirely.
        Phase.TAPER: (
            "technique",
            "power",
            "core_tension",
            "endurance",
            "mobility",
            "antagonist_prehab",
        ),
    }
)

_ASPECT_KEYS: Final[tuple[str, ...]] = tuple(spec.key for spec in CLIMBING_ASPECTS)
ASPECT_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {spec.key: spec.name for spec in CLIMBING_ASPECTS}
)
_EQUIPMENT_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {spec.key: spec.name for spec in EQUIPMENT}
)
_INJURY_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {spec.key: spec.name for spec in INJURY_AREAS}
)
_INJURY_ORDER: Final[tuple[str, ...]] = tuple(spec.key for spec in INJURY_AREAS)


def candidates(phase: Phase, aspect_key: str) -> tuple[ExerciseSpec, ...]:
    """Everything the generator could prescribe in one cell of the (phase, aspect) grid.

    A single-expression filter, and `tests/test_exercise_library.py` imports it rather than
    keeping a private copy: that file's coverage guard describes itself in exactly these
    words, and the claim is only true while it is *this* function.
    """
    return tuple(
        spec
        for spec in EXERCISES
        if spec.aspect_key == aspect_key
        and any(prescription.phase is phase for prescription in spec.prescriptions)
    )


def prescribable(
    cands: Iterable[ExerciseSpec],
    *,
    discipline: Discipline,
    equipment_keys: Sequence[str],
    open_injury_keys: Sequence[str],
) -> tuple[ExerciseSpec, ...]:
    """The candidates this climber can actually be given, in the library's authored order."""
    available = frozenset(equipment_keys)
    injured = frozenset(open_injury_keys)
    return tuple(
        spec
        for spec in cands
        if (spec.discipline is None or spec.discipline is discipline)
        and not injured.intersection(spec.contraindication_keys)
        and available.issuperset(spec.equipment_keys)
    )


def unlock_options(
    phase: Phase,
    aspect_key: str,
    *,
    discipline: Discipline,
    open_injury_keys: Sequence[str],
) -> tuple[tuple[str, ...], ...]:
    """The minimal equipment combinations that would open this cell, sorted.

    Each inner tuple is an AND set and the outer tuple is the OR. Supersets are dropped, so
    the answer is what is genuinely needed and not every requirement in the cell.

    **Injuries are not relaxed here** — the pool is the injury-surviving candidates only, so
    the message can never tell somebody to buy a hangboard for work we would withhold anyway.
    An empty result therefore means the gap is an injury, not a purchase.
    """
    survivors = [
        spec
        for spec in candidates(phase, aspect_key)
        if (spec.discipline is None or spec.discipline is discipline)
        and not frozenset(open_injury_keys).intersection(spec.contraindication_keys)
    ]
    requirements = {tuple(sorted(spec.equipment_keys)) for spec in survivors}
    return tuple(
        sorted(
            option
            for option in requirements
            if option and not any(set(other) < set(option) for other in requirements)
        )
    )


def shortfall_message(
    phase: Phase,
    aspect_key: str,
    options: tuple[tuple[str, ...], ...],
    *,
    open_injury_keys: Sequence[str],
) -> str:
    """The sentence a displaced slot carries. Equipment rows only, never a substitute.

    Built from `CLIMBING_ASPECTS`, `EQUIPMENT` and `INJURY_AREAS` display names so the
    wording cannot drift from the vocabulary the rest of the app shows.

    ⚠️ It names **equipment rows and injury areas and nothing else**. Never a movement
    substitute, never `exercise.substitution_hint`, never an improvised edge: a home-made
    hangboard is the most injury-prone thing a climber can rig, and "you could use a door
    frame" is the one answer this message must never give (CLAUDE.md's finger-loading
    safety boundary). Articles are omitted deliberately rather than derived — "a free
    weights" is what a naive `a`/`an` rule produces, and a wrong article in the one place
    the app admits a limitation reads worse than a bare list.
    """
    aspect = ASPECT_NAMES[aspect_key].lower()
    if not options:
        blocking = _blocking_injuries(phase, aspect_key, open_injury_keys=open_injury_keys)
        return (
            f"We've left {aspect} out of this phase: everything we would prescribe for it "
            f"is work we hold back while you have {blocking} flagged as injured."
        )
    listed = [" and ".join(_EQUIPMENT_NAMES[key].lower() for key in option) for option in options]
    if len(listed) == 1:
        return f"To train {aspect} in this phase you need {listed[0]}."
    return f"To train {aspect} in this phase you need one of these: {', '.join(listed)}."


def on_the_wall(cands: Iterable[ExerciseSpec]) -> tuple[ExerciseSpec, ...]:
    """The candidates that put the climber on a wall, in the library's authored order."""
    return tuple(spec for spec in cands if requires_wall(spec.equipment_keys))


def off_the_wall(cands: Iterable[ExerciseSpec]) -> tuple[ExerciseSpec, ...]:
    """The candidates that are not climbing. Climbing is allocated in its own pass, so this is
    what "supplementary" means: the remainder is genuinely reserved for other work."""
    return tuple(spec for spec in cands if not requires_wall(spec.equipment_keys))


def with_protocols(
    cands: Iterable[ExerciseSpec], kinds: AbstractSet[ProtocolKind]
) -> tuple[ExerciseSpec, ...]:
    """The candidates written as one of these protocols, in the library's authored order."""
    return tuple(spec for spec in cands if spec.protocol_kind in kinds)


def wall_led_aspects(phase: Phase) -> tuple[str, ...]:
    """The aspects a climbing session here can be about, in the phase's own order.
    Equipment-independent: a shortfall has to name what climbing here WOULD be."""
    return tuple(
        key
        for key in ASPECT_EMPHASIS[phase]
        if key in WALL_LED_ASPECTS and on_the_wall(candidates(phase, key))
    )


def wall_unlock_options(
    phase: Phase, *, discipline: Discipline, open_injury_keys: Sequence[str]
) -> tuple[tuple[str, ...], ...]:
    """The minimal equipment combinations that would put real climbing in this phase, sorted.
    Same shape and same injury rule as `unlock_options` — an AND per tuple, OR across them."""
    injured = frozenset(open_injury_keys)
    requirements = {
        tuple(sorted(spec.equipment_keys))
        for key in wall_led_aspects(phase)
        for spec in on_the_wall(candidates(phase, key))
        if (spec.discipline is None or spec.discipline is discipline)
        and not injured.intersection(spec.contraindication_keys)
    }
    return tuple(
        sorted(
            option
            for option in requirements
            if option and not any(set(other) < set(option) for other in requirements)
        )
    )


def no_climbing_message(options: tuple[tuple[str, ...], ...]) -> str:
    """The sentence a week with no wall time carries. Equipment rows only, never a substitute,
    and worded as the app saying something useful rather than as a gate (issue #61)."""
    if not options:
        return (
            "Climbing is the core of this plan, and everything we would put on a wall in this "
            "phase is work we hold back while you have an injury flagged."
        )
    listed = [" and ".join(_EQUIPMENT_NAMES[key].lower() for key in option) for option in options]
    tail = listed[0] if len(listed) == 1 else f"one of these: {', '.join(listed)}"
    return (
        f"Climbing is the core of this plan and we have nowhere to put it, so this phase is "
        f"supplementary work only. For the climbing itself you need {tail}."
    )


def _blocking_injuries(phase: Phase, aspect_key: str, *, open_injury_keys: Sequence[str]) -> str:
    """The open injuries that actually withheld this cell, in vocabulary order.

    The open set, filtered by what the cell's exercises name — naming every flag would tell
    somebody their ankle is why they cannot train their fingers.
    """
    open_keys = frozenset(open_injury_keys)
    named = {
        key
        for spec in candidates(phase, aspect_key)
        for key in spec.contraindication_keys
        if key in open_keys
    }
    labels = [_INJURY_NAMES[key].lower() for key in _INJURY_ORDER if key in named]
    if len(labels) <= 1:
        return labels[0] if labels else "an injury"
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def _validate_aspect_emphasis() -> None:
    """Agree with `DELIBERATELY_UNPRESCRIBED` in both directions, at import.

    Loud and early for the same reason `exercises.py::_require` is: the alternative is a
    generated plan quietly missing an aspect, or a displacement walk that lands on a cell
    with no candidate in any circumstances and produces a shortfall nobody can act on.

    ⚠️ Consequence, measured: `tests/test_exercise_library.py` imports `candidates` from this
    module, so an edit to `DELIBERATELY_UNPRESCRIBED` that opens a cell now fails at
    *collection* here rather than in that file's coverage guard. Both are red and both name
    the cell; this one names it first, which is why the message points at the other file.
    """
    unprescribed = {(cell.phase, cell.aspect_key) for cell in DELIBERATELY_UNPRESCRIBED}
    for phase in Phase:
        row = ASPECT_EMPHASIS.get(phase)
        if row is None:
            raise ValueError(
                f"ASPECT_EMPHASIS has no row for {phase.value}. Every phase a mesocycle can "
                f"carry needs a priority order — see server/domain/planner/selection.py."
            )
        if len(set(row)) != len(row):
            raise ValueError(f"ASPECT_EMPHASIS[{phase.value}] repeats an aspect: {row}.")
        expected = {key for key in _ASPECT_KEYS if (phase, key) not in unprescribed}
        if set(row) != expected:
            missing = sorted(expected - set(row))
            extra = sorted(set(row) - expected)
            raise ValueError(
                f"ASPECT_EMPHASIS[{phase.value}] disagrees with the library. Prescribable "
                f"but missing here: {missing}; listed here but in "
                f"DELIBERATELY_UNPRESCRIBED or not an aspect at all: {extra}. "
                f"If you just edited DELIBERATELY_UNPRESCRIBED in "
                f"server/domain/exercises.py, this row is the other half of that edit."
            )


_validate_aspect_emphasis()
