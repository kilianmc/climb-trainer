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

from server.domain.exercises import (
    DELIBERATELY_UNPRESCRIBED,
    EXERCISES,
    OPEN_CLIMBING_KEYS,
    ExerciseSpec,
)
from server.domain.grades import Discipline
from server.domain.planner.climbing import (
    WALL_LED_ASPECTS,
    requires_wall,
    week_ceiling_governs,
)
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

# Turns a wall-led aspect gets in `wall_aspect_turns()`, capped at one more than a session's
# blocks. ⚠️ **The cap FLATTENS the head of the authored order and it STAYS (F11, ruling 38) —
# seven readings were measured and every one of them turns a shipped ruling's guard red.**
# `wall_aspect_turns`' docstring is the register; do not lift this without reading it.
MAX_WALL_TURNS: Final = BLOCKS_PER_SESSION + 1

# The third slot, rotated. These are the qualities that keep the pulling durable and the
# body able to hold a position; they are worth a slot in every phase and they are never the
# thing a phase is *about*, which is why they get their own rotation instead of competing
# for the first two slots.
SUPPORT_ASPECTS: Final[tuple[str, ...]] = ("antagonist_prehab", "mobility", "core_tension")

# Ruling 21: slot 1 is the declared weakness's, but it YIELDS the slot one turn in this many.
# Why 3 and not 2 or 4 is measured in the docstring of `tests/test_phase_guide.py`'s
# `test_a_DECLARED_WEAKNESS_LEAVES_the_base_blocks_general_strength_A_TURN`.
WEAKNESS_YIELDS_SLOT_ONE_EVERY: Final = 3

# ⚠️ **Position in a row is a TURN COUNT, not a label**: `wall_aspect_turns()` gives a wall-led
# aspect `len(row) - index` turns, so EVERY position differentiates and reordering a row is a
# volume decision. The TAIL is where a wall quality is deliberately given fewer turns; the
# support rotation sits mid-row because it never leads a block. ⚠️ There is deliberately NO cap
# on the count any more (F11, ruling 38) — `_rank_weighted_ring` records what removing it moved.
ASPECT_EMPHASIS: Final[Mapping[Phase, tuple[str, ...]]] = MappingProxyType(
    {
        # Base builds the capacity everything later spends: wall time first, then the movement
        # quality that makes it useful. General strength and anaerobic capacity start here as the
        # slowest qualities to arrive; endurance keeps the wall lead (Kilian, 2026-09-04).
        Phase.BASE: (
            "endurance",
            "technique",
            "general_strength",
            "anaerobic_capacity",
            "finger_strength",
            "core_tension",
            "antagonist_prehab",
            "mobility",
            "power_endurance",
            "power",
        ),
        # Fingers lead their own block — the slowest quality to build — with general strength and
        # anaerobic capacity behind them, and aerobic work high alongside: `PHASE_GUIDE` carries
        # why. Power endurance is absent by authored decision (`DELIBERATELY_UNPRESCRIBED`): it
        # competes for the recovery the heavy sessions need and comes back in weeks.
        Phase.STRENGTH: (
            "finger_strength",
            "general_strength",
            "anaerobic_capacity",
            "endurance",
            "power",
            "technique",
            "core_tension",
            "antagonist_prehab",
            "mobility",
        ),
        # Power leads, with fingers second because contact strength is what a power block
        # expresses. Power endurance is absent; anaerobic capacity is maintained, off the wall.
        Phase.POWER: (
            "power",
            "finger_strength",
            "general_strength",
            "anaerobic_capacity",
            "core_tension",
            "technique",
            "endurance",
            "antagonist_prehab",
            "mobility",
        ),
        # Aerobic endurance sits LAST, on one wall turn: at equal turns its far longer exercises
        # take more minutes than PE's do. Ruling 20 supersedes ruling 13's INDEX and nothing else.
        Phase.POWER_ENDURANCE: (
            "power_endurance",
            "technique",
            "anaerobic_capacity",
            "core_tension",
            "finger_strength",
            "antagonist_prehab",
            "mobility",
            "power",
            "endurance",
        ),
        # Performance is about performing: limit attempts and redpoint burns, `power_endurance`
        # right after so a rope climber whose weakness is stamina still leads with it. Anaerobic
        # capacity is absent here; general strength and endurance sit at the tail, maintained.
        Phase.PERFORMANCE: (
            "power",
            "power_endurance",
            "technique",
            "finger_strength",
            "core_tension",
            "antagonist_prehab",
            "mobility",
            "general_strength",
            "endurance",
        ),
        # A deload is a block with its own prescriptions, not a scaled one. What it is for is
        # movement quality and range at low load, so technique and mobility lead and the
        # qualities that cost the most to recover from sit at the end.
        Phase.DELOAD: (
            "technique",
            "mobility",
            "antagonist_prehab",
            "core_tension",
            "general_strength",
            "finger_strength",
            "endurance",
            "anaerobic_capacity",
            "power_endurance",
            "power",
        ),
        # Barrows §3.3: only hard strength/power and hard aerobic power. Power leads, aerobic
        # power follows it, and the gym strength is the short upper-body kind — a heavy hinge or
        # squat leaves fatigue that hides the fitness the whole plan built.
        Phase.TAPER: (
            "power",
            "power_endurance",
            "technique",
            "general_strength",
            "core_tension",
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


def ordinary(cands: Iterable[ExerciseSpec]) -> tuple[ExerciseSpec, ...]:
    """The candidates that are a PROTOCOL, i.e. everything except ruling 29's open-climbing
    filler. Subtracted from every pool the ordinary passes draw from, so "climb for X minutes,
    your choice" can only ever arrive as ruling 27's length fill and never as a session's
    prescribed work — the filler has no dose to progress and nothing to be a week 3 of."""
    return tuple(spec for spec in cands if spec.key not in OPEN_CLIMBING_KEYS)


def open_climbing_fill(phase: Phase) -> tuple[ExerciseSpec, ...]:
    """Ruling 29's filler rows for this phase, in `aspect_rank()` order — F11's second surface.

    Ruling 30's two invariants are both this order: the first row is the one attributed to the
    quality the block is most named after, so it is the cue the climber reads AND the quality
    the filled minutes are credited to. `generate.py::_length_pick` takes the first row the
    week's frequency ceilings allow, which is a FILTER — `_validate_open_climbing_fill` proves
    every phase's pool holds a row no ceiling governs, so the pool is never empty.

    ⚠️ **This surface is rank-ORDERED and must not become rank-WEIGHTED, and that is measured.**
    Ruling 38 asks for both surfaces to rank; the same rank now decides both, through
    `aspect_rank()`, so neither can drift from the other. But a *weight* here is a frequency,
    and frequency is the one thing ruling 30 fixes: `_length_pick` rotated over a
    `_rank_weighted_ring` of this pool measured **1242 of 6000 fills credited off-lead on a day
    that still carried hard energy-system work**, against the 0 that
    `test_the_LENGTH_FILL_is_ONE_block_carrying_THE_BLOCKS_OWN_INTENTION` pins over its own 9837
    blocks. Every phase's pool is at most TWO rows — the leader, and the row for the days ruling
    9 has already made easy — so a weight here has nowhere to go that is not that defect.
    """
    by_aspect = {
        spec.aspect_key: spec
        for key in ASPECT_EMPHASIS[phase]
        for spec in candidates(phase, key)
        if spec.key in OPEN_CLIMBING_KEYS
    }
    return tuple(sorted(by_aspect.values(), key=lambda spec: -aspect_rank(phase, spec.aspect_key)))


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
        if key in WALL_LED_ASPECTS and on_the_wall(ordinary(candidates(phase, key)))
    )


def aspect_rank(phase: Phase, aspect_key: str) -> int:
    """One aspect's authored weight in this phase: its distance from the END of the row, so the
    head of `ASPECT_EMPHASIS` is the biggest number. The single definition of "rank" both of
    F11's surfaces read (`wall_aspect_turns` weights by it, `open_climbing_fill` orders by it),
    so a reordered row cannot move one surface and leave the other where it was."""
    row = ASPECT_EMPHASIS[phase]
    return len(row) - row.index(aspect_key)


def _rank_weighted_ring(items: tuple[str, ...], turns: Mapping[str, int]) -> tuple[str, ...]:
    """`items` as a ring, each appearing `turns[item]` times, interleaved by largest quotient so
    the turns spread rather than arrive in runs and the authored order breaks every tie: a run of
    four endurance turns hides every aspect behind it."""
    taken = dict.fromkeys(items, 0)
    ring: list[str] = []
    for _ in range(sum(turns[item] for item in items)):
        leader = items[0]
        for key in items:
            if turns[key] * (taken[leader] + 1) > turns[leader] * (taken[key] + 1):
                leader = key
        taken[leader] += 1
        ring.append(leader)
    return tuple(ring)


def wall_aspect_turns(phase: Phase) -> tuple[str, ...]:
    """The wall-led aspects as a ring of TURNS — which quality leads a climbing session here,
    and how OFTEN, which is the half of the phase's authored order a flat rotation loses.

    ⚠️ **THE CAP FLATTENS THE HEAD AND STAYS. F11 / ruling 38 asked for it to be lifted; seven
    readings were measured and every one of them turns a shipped ruling's guard RED.** What the
    cap costs, re-measured with ruling 41's row in the tree: **21 of 30** phase/aspect pairs sit
    on it, and `strength` and `taper` come out perfectly FLAT — so "rank-weighted" is false in
    **2 of 7** phases, down from 3, because ruling 41's `endurance` row gives `power` a 3 where
    everything else there is a 4.

    Each reading over the 72-plan sweep, with "agreement" = the fraction of the phase's authored
    aspect PAIRS the observed per-phase WALL BLOCK counts put in the right order, and the arms
    it turned red. **cap 4 (this) 35/51, GREEN.** cap 5: 14 red (ruling 35's habituation, reach).
    cap 6: 37/51, 9 red (ruling 24's day-count copy, ruling 23's boulderer aerobic row at 2×).
    cap 8: 36/51, co-occurrence 26 → 128 red weeks. **Uncapped: 38/51, the best agreement, 9
    red** — ruling 23 (a 6A boulderer at 2× and 3× takes NO aerobic block in the whole
    power-endurance block), ruling 24 (5 profiles at 4-5 days), **ruling 30's out-training
    invariant** (POWER_ENDURANCE technique 25200 min against power_endurance 24664 = 36.1%), and
    two rows unreachable. Dense rank over the wall-led aspects (4/3/2/1) and doubled: 38/51, 8
    red each, co-occurrence 26 → 90. Proportional to rank at **today's exact ring lengths**:
    every phase strictly ordered, lengths byte-identical, still 5 red — ruling 30 in
    POWER_ENDURANCE *and* in BASE ("power sits last"), plus habituation.

    ⚠️ **Why even the length-preserving reading breaks PRESENCE guards — the fact no ruling
    had:** `_rotated_pool(ring, spread)` starts at `spread % len(ring)` and `_spread` is
    `(week - 1) * DAYS_PER_WEEK + session_index`, so a **2-session week visits 6 of this ring's
    16 rotations**. Which qualities such a week gets AT ALL is which aspects sit at those six
    positions, so re-weighting moves presence and not only proportion — and presence at 2-3
    sessions is exactly what rulings 23, 24, 30 and 35 pin.
    ⚠️ **The ring cannot buy a share of the clock.** The same pairs read on wall MINUTES barely
    move across all seven readings (36/51 → 37/51): minutes come from the dose and from
    `MAX_EXPANSION_FACTOR`. **The ring ranks BLOCKS and nothing else.**
    ⚠️ **Not strict rank order, and it must not become it** (PR #116): with no ring a leading
    `endurance` block expands to the fill target, `_fill_climbing` breaks, and whichever aspect
    leads takes the whole session — 100% of a base block's wall minutes, technique zero.
    """
    aspects = wall_led_aspects(phase)
    if not aspects:
        return ()
    return _rank_weighted_ring(
        aspects, {key: min(aspect_rank(phase, key), MAX_WALL_TURNS) for key in aspects}
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
    """Agree with `DELIBERATELY_UNPRESCRIBED` in both directions, and keep a fillable row once
    the weekly frequency ceilings have filtered it — both at import.

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
        # `generate.py::_try_supplementary` FILTERS this row by the weekly frequency ceilings
        # and then indexes `[0]`, so a row the ceilings could empty is an `IndexError` mid-
        # generate — which is the failure `climbing.py::_validate_frequency_ceilings` exists to
        # move to import time. Subtracted through `week_ceiling_governs`, the predicate's own
        # key space, so this floor cannot drift out of step with what the filter refuses.
        survivors = sorted(key for key in row if not week_ceiling_governs(key))
        if len(survivors) < BLOCKS_PER_SESSION:
            raise ValueError(
                f"ASPECT_EMPHASIS[{phase.value}] keeps only {len(survivors)} aspect(s) the "
                f"weekly frequency ceilings can never refuse ({survivors}), against the "
                f"{BLOCKS_PER_SESSION} a session's slots need. A week that has spent its hard "
                f"energy-system days filters this row down to those, and "
                f"generate.py::_try_supplementary indexes the result."
            )


def _validate_open_climbing_fill() -> None:
    """Every phase's filler pool HOLDS a row no weekly ceiling can refuse — at import.

    ⚠️ "Holds", not "ends in": the check is `any`, and it always was. The pool is a rank ORDER
    and `_length_pick` walks all of it, so where the ungoverned row sits is not the invariant.

    This is what makes ruling 27's fill a filter rather than a ranking: `_length_pick` walks
    `open_climbing_fill(phase)` and takes the first row the week allows, so a phase whose only
    filler is attributed to an energy-system quality would leave a session short of ruling 25's
    length on every day the ~3-hard-days ceiling has already made easy. Checked here for
    `_validate_aspect_emphasis`' reason: a missing fallback is a silently shorter session, and
    a shorter session is exactly what ruling 27 exists to remove.
    """
    for phase in Phase:
        row = open_climbing_fill(phase)
        if not any(not week_ceiling_governs(spec.aspect_key) for spec in row):
            raise ValueError(
                f"open_climbing_fill({phase.value}) offers "
                f"{[spec.key for spec in row]}, none of which is attributed to a quality the "
                f"weekly frequency ceilings leave alone. Ruling 27's length fill would then "
                f"have no candidate on a day already at its hard-energy ceiling. Give "
                f"server/domain/exercises.py's open-climbing family a row for this phase."
            )


_validate_aspect_emphasis()
_validate_open_climbing_fill()
