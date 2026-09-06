"""⚠️ GUARD. Issue #117: loading weeks 1, 2 and 3 of a block owe a week-to-week progression.

Both sources require one — Dylan "progress the weight or time every week", Barrows a rule per
attribute — and a dose is one row per (exercise, phase), so nothing in the schema can carry it.
Every claim is MEASURED off `generate()`'s own output at the granularity of the claim: per
`(block, exercise, week-pair)`, because a pooled read over a plan or a union over profiles reads
green while every individual block is internally identical. Ruling 46's key is the
`(aspect_key, protocol_kind)` PAIR, and the tables below restate it independently of
`progression.py` — a guard that asks the rule what the rule is agrees with a wrong answer.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache

import pytest

from server.domain.exercises import EXERCISES, OPEN_CLIMBING_KEYS, PrescriptionSpec
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner.blueprint import BlockBlueprint
from server.domain.planner.contract import PlannerInput
from server.domain.planner.generate import _pool_index, _spread, generate
from server.domain.planner.selection import (
    candidates,
    on_the_wall,
    ordinary,
    prescribable,
    wall_led_aspects,
)
from server.domain.vocabulary import EQUIPMENT, Phase, ProtocolKind

_MONDAY = date(2026, 8, 24)
_ALL_EQUIPMENT = tuple(sorted(spec.key for spec in EQUIPMENT))
_BY_KEY = {spec.key: spec for spec in EXERCISES}

# The block shape, restated rather than imported from `periodisation.py` for the reason in the
# module docstring: three loading weeks then one unload, so week 4 of a block progresses nothing.
_WEEKS_PER_BLOCK = 4
_LOADING_WEEKS = 3
_UNLOADING_PHASES = frozenset({Phase.DELOAD, Phase.TAPER})

# Ruling 46's own table, as this file's data. `LONGER_WORK` is An Cap — harder or longer work and
# NEVER less rest; `SHORTER_REST` is lactic An Pow; `MORE_ROUNDS` is alactic max-effort work.
_LONGER_WORK = "longer_work"
_SHORTER_REST = "shorter_rest"
_MORE_ROUNDS = "more_rounds"
_RULES: Mapping[tuple[str, ProtocolKind], str] = {
    ("anaerobic_capacity", ProtocolKind.INTERVALS): _LONGER_WORK,
    ("anaerobic_capacity", ProtocolKind.CIRCUIT): _LONGER_WORK,
    ("power", ProtocolKind.CIRCUIT): _SHORTER_REST,
    ("power", ProtocolKind.STRAIGHT_SETS): _MORE_ROUNDS,
    ("power", ProtocolKind.LIMIT_BOULDER): _MORE_ROUNDS,
}

# The one cell two rows share, and the work duration that tells them apart: 6 s of alactic burst
# against a 30 s lactic interval, so the pair alone cannot name the rule here (ruling 46).
_SPLIT_CELL = ("power", ProtocolKind.INTERVALS)
_ALACTIC_WORK_SECONDS_MAX = 15

# Anti-vacuity floors: 90% of what the sweep MEASURED when this file landed — 637 longer-work, 57
# shorter-rest and 498 more-rounds cells — so selection may drift without buying silence.
#
# A rule reaching zero cells is a rule nobody is testing, which is how three prescribed mechanisms
# shipped byte-identical in this package before anybody measured the counterfactual.
#
# ⚠️ RE-BASED for ruling 41's `easy_climbing_flush`, and the shorter-rest arm lost more than a
# tenth. Re-measured with the row in the tree: longer-work 608 (floor unchanged, it still clears
# 573), more-rounds 498 → 438, shorter-rest **57 → 15**. The row takes a wall turn in `strength`
# and `power`, so an exercise that used to land in two loading weeks of the SAME block now often
# lands in one, and a week-PAIR is what this arm counts. What that costs is named, not averaged:
# `boulders_on_the_two_minute` contributed 30 of the 57 shorter-rest cells (18 `strength`, 12
# `power`) and now contributes **none**, so the arm reads `short_rest_boulder_sets` alone — the
# very row ruling 43 records as carrying no `work_seconds` for its own guard to read. F26 hangs
# on this rule and this arm is now thin. Raising it back is a sweep widening, not a re-dose.
_CELLS_INSPECTED = {_LONGER_WORK: 573, _SHORTER_REST: 13, _MORE_ROUNDS: 394}

# Pools of exactly one exercise, which no index can move week to week. Pinned so the arm below
# cannot silently start passing because a pool collapsed rather than because the index works.
# ⚠️ 2 → 6 with ruling 41's row: `easy_climbing_flush` is the ONLY on-wall `endurance` candidate
# in `strength` and in `power`, so both phases gain a singleton wall pool for both disciplines.
# A second on-wall `endurance` row in either phase takes this back down and must be a decision.
_SINGLETON_WALL_POOLS = 6


@dataclass(frozen=True, slots=True)
class _Climber:
    """One generated plan's inputs, frozen so `@cache` can key generation on it."""

    discipline: Discipline
    system: GradeSystemKey
    grade: str
    sessions: int
    weakness: str | None


_CLIMBERS = (
    (Discipline.SPORT, GradeSystemKey.FRENCH, "6a"),
    (Discipline.BOULDER, GradeSystemKey.FONT, "6A"),
    (Discipline.SPORT, GradeSystemKey.FRENCH, "6c"),
    (Discipline.BOULDER, GradeSystemKey.FONT, "6C"),
    (Discipline.SPORT, GradeSystemKey.FRENCH, "7c"),
    (Discipline.BOULDER, GradeSystemKey.FONT, "7C"),
)

# 72 plans: the same three dimensions `test_phase_guide.py`'s weakness sweep uses, because the
# declared weakness is the largest categorical lever in the generator and it re-keys selection.
_SWEEP: tuple[_Climber, ...] = tuple(
    _Climber(discipline, system, grade, sessions, weakness)
    for discipline, system, grade in _CLIMBERS
    for sessions in (2, 3, 5, 7)
    for weakness in (None, "power", "power_endurance")
)


def _input(climber: _Climber) -> PlannerInput:
    """A plannable climber with no injuries, holding the whole vocabulary."""
    current = ordinal_of(climber.system, climber.grade)
    return PlannerInput(
        discipline=climber.discipline,
        current_ordinal=current,
        target_ordinal=current + 3,
        sessions_per_week=climber.sessions,
        available_weekdays=0b111_1111,
        strength_aspect_key=None,
        weakness_aspect_key=climber.weakness,
        open_injury_keys=(),
        equipment_keys=_ALL_EQUIPMENT,
        start_date=_MONDAY,
    )


def _dose(block: BlockBlueprint) -> tuple[int, int | None, int | None, int | None]:
    """One block's prescribed dose: rounds, work, within-set rest, between-sets rest."""
    first = block.sets[0]
    return (
        len(block.sets),
        first.target_work_seconds,
        first.target_rest_seconds,
        block.rest_between_sets_seconds,
    )


@cache
def _doses_by_block(climber: _Climber) -> tuple[tuple[str, Phase, int, str, tuple[int, ...]], ...]:
    """Every (mesocycle, week, exercise) dose of one plan, keyed by the BLOCK it sits in."""
    plan = generate(_input(climber))
    rows: list[tuple[str, Phase, int, str, tuple[int, ...]]] = []
    for index, mesocycle in enumerate(plan.mesocycles):
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                for block in session.blocks:
                    rows.append(
                        (
                            f"{climber.grade}/{climber.sessions}x/{climber.weakness}/{index}",
                            microcycle.phase,
                            microcycle.week_no,
                            block.exercise_key,
                            _dose(block),  # type: ignore[arg-type]
                        )
                    )
    return tuple(rows)


def _rule_of(exercise_key: str, phase: Phase) -> str | None:
    """Ruling 46's key applied to one row: the pair, and `work_seconds` in the split cell."""
    spec = _BY_KEY[exercise_key]
    if phase in _UNLOADING_PHASES or exercise_key in OPEN_CLIMBING_KEYS:
        return None
    cell = (spec.aspect_key, spec.protocol_kind)
    if cell == _SPLIT_CELL:
        work = _authored(exercise_key, phase).work_seconds
        if work is not None and work <= _ALACTIC_WORK_SECONDS_MAX:
            return _MORE_ROUNDS
        return _SHORTER_REST
    return _RULES.get(cell)


def _authored(exercise_key: str, phase: Phase) -> PrescriptionSpec:
    """The library's own row for this (exercise, phase), before any week has moved it."""
    return next(p for p in _BY_KEY[exercise_key].prescriptions if p.phase is phase)


def _week_pairs(
    climber: _Climber,
) -> list[tuple[str, Phase, str, int, tuple[int, ...], int, tuple[int, ...]]]:
    """Every (block, exercise) that appears in two loading weeks of the SAME block, paired up."""
    seen: dict[tuple[str, Phase, str], dict[int, tuple[int, ...]]] = {}
    for block_id, phase, week_no, exercise_key, dose in _doses_by_block(climber):
        seen.setdefault((block_id, phase, exercise_key), {})[week_no] = dose
    pairs = []
    for (block_id, phase, exercise_key), by_week in seen.items():
        weeks = sorted(by_week)
        for earlier, later in ((a, b) for a in weeks for b in weeks if a < b):
            pairs.append(
                (block_id, phase, exercise_key, earlier, by_week[earlier], later, by_week[later])
            )
    return pairs


@pytest.mark.parametrize("rule", sorted(_CELLS_INSPECTED))
def test_a_PROGRESSING_PAIR_never_repeats_its_dose_inside_ONE_BLOCK(rule: str) -> None:
    """⚠️ GUARD, per `(block, exercise, week-pair)`. Weeks 1-3 of the same block must move."""
    inspected = 0
    for climber in _SWEEP:
        for block_id, phase, key, earlier, before, later, after in _week_pairs(climber):
            if _rule_of(key, phase) != rule:
                continue
            inspected += 1
            assert before != after, (
                f"{key} is dosed {before} in week {earlier} and {after} in week {later} of the "
                f"same {phase.value} block ({block_id}); its {rule} rule moved nothing."
            )
    assert inspected >= _CELLS_INSPECTED[rule], (
        f"only {inspected} {rule} cells inspected against the {_CELLS_INSPECTED[rule]} measured "
        f"when this arm landed, so it has stopped reading the rule it exists to check."
    )


def test_ANAEROBIC_CAPACITY_progresses_by_LONGER_WORK_and_NEVER_by_LESS_REST() -> None:
    """⚠️ GUARD. Barrows §5.2 names a shorter rest as the one thing An Cap must not do."""
    for climber in _SWEEP:
        for block_id, phase, key, earlier, before, later, after in _week_pairs(climber):
            if _rule_of(key, phase) != _LONGER_WORK:
                continue
            where = f"{key} in {phase.value} ({block_id}), weeks {earlier} -> {later}"
            assert after[1] is not None and before[1] is not None, f"{where}: no work to lengthen."
            assert after[1] > before[1], f"{where}: work {before[1]} s -> {after[1]} s."
            for index, field in ((2, "rest_seconds"), (3, "rest_between_sets_seconds")):
                if before[index] is None or after[index] is None:
                    continue
                assert after[index] >= before[index], (
                    f"{where}: {field} fell {before[index]} s -> {after[index]} s. An Cap "
                    f"progresses by harder or longer work and never by less rest."
                )


def test_LACTIC_POWER_progresses_by_SHORTER_REST_and_ALACTIC_POWER_by_ROUNDS_ONLY() -> None:
    """⚠️ GUARD, the two rules that share one aspect. Alactic rest and work must not move."""
    for climber in _SWEEP:
        for block_id, phase, key, earlier, before, later, after in _week_pairs(climber):
            rule = _rule_of(key, phase)
            where = f"{key} in {phase.value} ({block_id}), weeks {earlier} -> {later}"
            if rule == _SHORTER_REST:
                assert max(x or 0 for x in after[2:]) < max(x or 0 for x in before[2:]), (
                    f"{where}: the operative rest did not shorten, {before} -> {after}."
                )
            if rule == _MORE_ROUNDS:
                assert after[0] > before[0], f"{where}: rounds {before[0]} -> {after[0]}."
                assert after[1:] == before[1:], (
                    f"{where}: alactic work only gains ROUNDS. Longer work and shorter rest are "
                    f"both named counterproductive, and this moved {before} -> {after}."
                )


def test_the_RULE_IS_KEYED_ON_THE_PAIR_and_could_NEVER_be_read_off_the_ASPECT() -> None:
    """⚠️ GUARD, ruling 46. `power` reaches all three rules, so no aspect-level rule can serve."""
    reached = {rule for cell, rule in _RULES.items() if cell[0] == "power"}
    for spec in EXERCISES:
        if (spec.aspect_key, spec.protocol_kind) != _SPLIT_CELL:
            continue
        for prescription in spec.prescriptions:
            rule = _rule_of(spec.key, prescription.phase)
            if rule is not None:
                reached.add(rule)
    assert reached == {_SHORTER_REST, _MORE_ROUNDS}, (
        f"the `power` aspect reaches {sorted(reached)}. Ruling 36 forbids reading any rule off "
        f"`aspect_key` alone precisely because this set has more than one member."
    )
    split = {
        spec.key
        for spec in EXERCISES
        if (spec.aspect_key, spec.protocol_kind) == _SPLIT_CELL
        for p in spec.prescriptions
    }
    assert split == {"boulders_on_the_two_minute", "explosive_move_intervals"}, (
        f"the split cell holds {sorted(split)}. `work_seconds` is read in ONE cell and its "
        f"threshold is authored against those two rows; a third row needs a decision, not a pass."
    )


def test_a_PAIR_WITH_NO_SOURCED_RULE_KEEPS_ITS_AUTHORED_DOSE_IN_EVERY_LOADING_WEEK() -> None:
    """⚠️ GUARD. This is what stops #117 becoming a per-phase volume multiplier."""
    checked: Counter[str] = Counter()
    for climber in _SWEEP:
        for block_id, phase, week_no, key, dose in _doses_by_block(climber):
            if _rule_of(key, phase) is not None or key in OPEN_CLIMBING_KEYS:
                continue
            authored = _authored(key, phase)
            checked[key] += 1
            assert dose[1:] == (
                authored.work_seconds,
                authored.rest_seconds,
                authored.rest_between_sets_seconds,
            ), (
                f"{key} ({_BY_KEY[key].aspect_key} x {_BY_KEY[key].protocol_kind.value}) has no "
                f"sourced week rule, yet week {week_no} of {block_id} doses it {dose} against the "
                f"library's own {authored}. Only the pairs ruling 46 names may move."
            )
    assert len(checked) >= 60, (
        f"only {len(checked)} exercises checked for an unmoved dose; the arm has stopped "
        f"covering the library and could no longer see a volume multiplier appear."
    )


def test_an_UNLOAD_WEEK_IS_DOSED_AS_AUTHORED_and_progresses_NOTHING() -> None:
    """⚠️ GUARD. A deload has its own prescriptions, so it is not a loading week's third step."""
    inspected = 0
    for climber in _SWEEP:
        for block_id, phase, week_no, key, dose in _doses_by_block(climber):
            if phase not in _UNLOADING_PHASES or key in OPEN_CLIMBING_KEYS:
                continue
            authored = _authored(key, phase)
            inspected += 1
            assert dose == (
                authored.sets,
                authored.work_seconds,
                authored.rest_seconds,
                authored.rest_between_sets_seconds,
            ), (
                f"{key} in {phase.value} week {week_no} of {block_id} is dosed {dose} against "
                f"the authored {authored}; an unload week takes the library's row as written."
            )
    assert inspected > 1000, f"only {inspected} unload blocks inspected; the arm is not reading."


def test_the_WEEK_TERM_CANNOT_CANCEL_OUT_OF_ANY_POOL_THE_LIBRARY_CAN_BUILD() -> None:
    """⚠️ GUARD, #117's mechanical half. A pool length equal to the stride ate the week entirely."""
    singletons = 0
    for phase in Phase:
        for discipline in (Discipline.BOULDER, Discipline.SPORT):
            for aspect_key in wall_led_aspects(phase):
                pool = prescribable(
                    on_the_wall(ordinary(candidates(phase, aspect_key))),
                    discipline=discipline,
                    equipment_keys=_ALL_EQUIPMENT,
                    open_injury_keys=(),
                )
                if not pool:
                    continue
                if len(pool) == 1:
                    singletons += 1
                    continue
                for session_index in range(7):
                    drawn = {
                        _pool_index(_spread(week_no, session_index), len(pool))
                        for week_no in range(1, _LOADING_WEEKS + 1)
                    }
                    assert len(drawn) > 1, (
                        f"({phase.value}, {discipline.value}, {aspect_key}) is a pool of "
                        f"{len(pool)} and session {session_index} draws index {drawn} in all "
                        f"{_LOADING_WEEKS} loading weeks: the week term cancelled out."
                    )
    assert singletons == _SINGLETON_WALL_POOLS, (
        f"{singletons} wall pools hold one exercise, not {_SINGLETON_WALL_POOLS}. A pool of one "
        f"is the only pool a week cannot move, so this count is what the arm above skips."
    )


def test_the_POOL_INDEX_MOVES_EVERY_WEEK_AT_EVERY_POOL_SIZE_A_LIBRARY_COULD_REACH() -> None:
    """⚠️ GUARD on the mechanism itself: the week's stride is 1, so no size can divide it."""
    for size in range(2, 41):
        for session_index in range(7):
            drawn = [
                _pool_index(_spread(week_no, session_index), size)
                for week_no in range(1, _LOADING_WEEKS + 1)
            ]
            assert drawn[0] != drawn[1] and drawn[1] != drawn[2], (
                f"a pool of {size} at session {session_index} draws {drawn} across the loading "
                f"weeks; consecutive weeks must differ at every size."
            )
