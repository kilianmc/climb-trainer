"""⚠️ GUARD. Climbing is the core of every week of a generated plan, and long enough to be one.
DB-free. Issue #84: the generator prescribed 28% of its minutes on a wall and gave week 19 none at
all, while ruff, mypy and the whole suite stayed green — because nothing recomputed the wall-minutes
matrix from a real plan. Every claim here is therefore MEASURED off `generate()`'s own output, never
restated from `server/domain/planner/climbing.py`: the PR #63 lesson was that 20 exercises landed in
the wrong tuple with 266 tests passing, and only recomputing the matrix caught it. The session
windows are the second half — a fixed-volume protocol must never be padded, because low volume *is*
the protocol — and WHICH climbing is the third: a phase's authored emphasis has to be where its
minutes go. Shown to fail before being trusted; captures in `.claude/pr-a-state.md`.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache

import pytest

from server.domain.exercises import EXERCISES
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner.blueprint import (
    BlockBlueprint,
    MicrocycleBlueprint,
    PlanBlueprint,
    SessionBlueprint,
)
from server.domain.planner.climbing import (
    EXPANDABLE_ASPECTS,
    EXPANDABLE_PROTOCOLS,
    MAX_EXPANSION_FACTOR,
    UNLOADING_PHASES,
    WALL_EQUIPMENT,
    Level,
    level_for,
    session_window,
    week_climbing_floor_pct,
)
from server.domain.planner.contract import PlannerInput
from server.domain.planner.generate import SECONDS_PER_REP, generate
from server.domain.planner.selection import BLOCKS_PER_SESSION
from server.domain.vocabulary import EQUIPMENT, Phase, ProtocolKind

_MONDAY = date(2026, 8, 24)
_ALL_EQUIPMENT = tuple(sorted(spec.key for spec in EQUIPMENT))
_BY_KEY = {spec.key: spec for spec in EXERCISES}

# The plan document's own table, restated INDEPENDENTLY of `climbing.py` on purpose: a guard
# that asks `is_expandable()` whether a block may expand agrees with any answer that function
# gives, including a wrong one. Measured: sabotaging it to `return True` left that arm green.
_MAY_EXPAND: frozenset[tuple[str, ProtocolKind]] = frozenset(
    {
        ("endurance", ProtocolKind.LAPS),
        ("endurance", ProtocolKind.CIRCUIT),
        ("endurance", ProtocolKind.OTHER),
        ("technique", ProtocolKind.LAPS),
        ("technique", ProtocolKind.CIRCUIT),
        ("technique", ProtocolKind.OTHER),
    }
)

# Kilian's target BANDS. This and the two tables below are restated independently of
# `climbing.py` for `_MAY_EXPAND`'s reason: a guard that reads its constant agrees with it.
_TARGET_BAND: Mapping[Level, tuple[int, int]] = {
    Level.BEGINNER: (85, 90),
    Level.INTERMEDIATE: (75, 82),
    Level.ADVANCED: (50, 65),
}

# Real max-hang / repeater sessions a LOADING week owes, per band. Beginner is zero by decision:
# the sources want 6-12 months of climbing first and no column records that history.
_FINGER_SESSIONS_PER_WEEK: Mapping[Level, int] = {
    Level.BEGINNER: 0,
    Level.INTERMEDIATE: 1,
    Level.ADVANCED: 2,
}
_FINGER_PROTOCOLS = frozenset({ProtocolKind.MAX_HANG, ProtocolKind.REPEATERS})
_FINGER_PHASES = frozenset({Phase.STRENGTH, Phase.POWER})


@dataclass(frozen=True, slots=True)
class _AcceptedFingerGap:
    """One (climber, sessions, loading week) that misses its band's hangboard floor. `delivered`
    is the measurement, so the row cannot widen, and the reverse arm fails one that stops firing."""

    profile: str
    sessions: int
    loading_week: int
    delivered: int
    reason: str


# The register, and EMPTY is a measurement: §3.4's ordering repaired both rows — ruling 15's
# intermediate 2x/week hangboard loss included — by making the window follow the hardest block.
_ACCEPTED_FINGER_GAPS: tuple[_AcceptedFingerGap, ...] = ()

# Quality first. The fixed-volume protocols are the ones whose adaptation is decided by the
# quality of the effort, so none of them may sit behind any of the volume protocols.
_PRIORITY_PROTOCOLS = frozenset(
    {ProtocolKind.MAX_HANG, ProtocolKind.REPEATERS, ProtocolKind.LIMIT_BOULDER}
)
# The two qualities a DELOAD session leads with, restated independently for `_MAY_EXPAND`'s
# reason. Kilian, 2026-09-04: at low load movement quality goes ahead of the climbing.
_DELOAD_LEAD_ASPECTS: frozenset[str] = frozenset({"technique", "mobility"})
# Everything else is volume work, DERIVED so a new kind joins automatically: `OTHER` was in
# neither set, so a priority block behind an `OTHER`-kind block passed (320 of 4867 blocks).
_VOLUME_PROTOCOLS = frozenset(ProtocolKind) - _PRIORITY_PROTOCOLS

# Barrows §3.4's tiers, restated independently of `climbing.py` for `_MAY_EXPAND`'s reason: a
# guard that asks `intensity_tier()` for a tier agrees with any answer that function gives.
_INTENSITY_TIERS: tuple[tuple[str, ...], ...] = (
    ("power", "finger_strength", "general_strength"),
    ("anaerobic_capacity",),
    ("power_endurance",),
    ("endurance",),
    ("technique", "core_tension", "antagonist_prehab", "mobility"),
)
_TIER: Mapping[str, int] = {key: tier for tier, keys in enumerate(_INTENSITY_TIERS) for key in keys}

# The four aspects §3.4 NAMES. Everything else is off the chain, which is also why a deload's
# `technique`/`mobility` lead needs no exemption below: neither of them is on it.
_INTENSITY_CHAIN: tuple[str, ...] = ("power", "anaerobic_capacity", "power_endurance", "endurance")

# Sessions carrying two or more chain aspects — the only ones whose order can be WRONG. Measured
# 13-91 per profile per session count, so the floor is the worst of them and still bites.
_CHAIN_PAIRED_SESSIONS_FLOOR = 13

# On the full weekday mask `choose_weekdays` leaves 2 and 3 sessions with NO back-to-back pair at
# all; 5 sessions get 3 a week and 7 get 6, so below this the descending arm has nothing to say.
_SESSIONS_WITH_BACK_TO_BACK_DAYS = 5

# Barrows §3.3, restated as this file's own data for `_MAY_EXPAND`'s reason: a taper drops ALL
# anaerobic capacity, aerobic capacity and ARC, and holds only hard strength/power and Aero Pow.
_TAPER_DROPPED: tuple[str, ...] = ("anaerobic_capacity", "endurance")
_TAPER_HARD: tuple[str, ...] = ("power", "power_endurance", "general_strength")

# §3.3 holds a taper's intensity at the loading value or higher, and every taper prescription in
# those three aspects is authored at RPE 8 or 9 — so the held intensity is checkable as a floor.
_TAPER_HARD_RPE_FLOOR = 8

# Upper-body PULLING only, which is the half of the retired `(taper, general_strength)` exemption
# that still argues: a heavy hinge or squat leaves fatigue that hides the fitness the plan built.
_TAPER_STRENGTH_ROWS: frozenset[str] = frozenset({"weighted_pull_ups", "one_arm_lockoff_negatives"})

# Taper weeks the sweep reaches, and the 6 of them carrying gym strength — which is why THAT
# aspect's arm is POOLED while `power`/`power_endurance`, at 24 of 24, are asserted per week.
_TAPER_WEEKS_IN_THE_SWEEP = 24
_TAPER_HARD_PER_WEEK: tuple[str, ...] = ("power", "power_endurance")

# ⚠️ Both sources agree an unload week KEEPS 40-60% of a loading week's volume with intensity
# held: Barrows §3.3 puts the taper at ~50%, Dylan's deload "reduce the volume of everything you
# do by 40-60%". Warm-up EXCLUDED on both sides — the fixed 15 min is not a block, and counting
# it inflates the ratio by a session-count-dependent amount: the beginner 2x/week taper read
# 9.8% excluding and 35.6% including before this PR, which would have let a 7-minute taper week
# pass as a third of a loading week.
# ⚠️ The 60% CEILING is deliberately NOT asserted, and it is an OPEN DECISION FOR KILIAN rather
# than an accepted exception. Measured after C2's top-up, 52 of 96 deload weeks (to 85.5%) and
# 8 of 24 taper weeks (to 68.1%) sit above it, because a deload week's length comes from its own
# prescriptions and its own session types and so does not know which block it closes. Turning it
# on needs either a per-block unload target or a third re-baseline of `_TARGET_BAND[ADVANCED]`.
_UNLOAD_FLOOR_PCT = 40

# One climber per band, by CURRENT grade, spanning both ladders so neither discipline's
# threshold constant can be wrong without a red test. The gap is 3 by default — the shortest
# plan covering all five training phases plus deload and taper; the band-range test sweeps it.
_CLIMBERS: tuple[tuple[Level, Discipline, GradeSystemKey, str], ...] = (
    (Level.BEGINNER, Discipline.SPORT, GradeSystemKey.FRENCH, "6a"),
    (Level.BEGINNER, Discipline.BOULDER, GradeSystemKey.FONT, "6A"),
    (Level.INTERMEDIATE, Discipline.SPORT, GradeSystemKey.FRENCH, "6c"),
    (Level.INTERMEDIATE, Discipline.BOULDER, GradeSystemKey.FONT, "6C"),
    (Level.ADVANCED, Discipline.SPORT, GradeSystemKey.FRENCH, "7c"),
    (Level.ADVANCED, Discipline.BOULDER, GradeSystemKey.FONT, "7C"),
)


def _profile(level: Level, discipline: Discipline, label: str) -> str:
    """The `_ACCEPTED_FINGER_GAPS` key: one climber of `_CLIMBERS`, without the session count."""
    return f"{level.value} {discipline.value} {label}"


_BY_PROFILE = {
    _profile(level, discipline, label): (level, discipline, system, label)
    for level, discipline, system, label in _CLIMBERS
}


# Kilian's authored order for a base block, restated independently of `selection.py` for
# `_MAY_EXPAND`'s reason, and quoted almost verbatim in `PHASE_GUIDE[Phase.BASE]`.
# ⚠️ `general_strength` sits third in the authored row and is absent here, and since its three
# on-wall rows moved to `power` no on-wall one exists in ANY phase. `anaerobic_capacity` has two.
_BASE_WALL_EMPHASIS: tuple[str, ...] = (
    "endurance",
    "technique",
    "anaerobic_capacity",
    "power_endurance",
    "power",
)

# What the two qualities that order ranks last may take of a base block's prescribed minutes.
# Measured over both beginners at 1-7 sessions: 0.0-17.3% now against 20.6-36.0% before.
_BASE_TAIL_CEILING_PCT = 20

# Barrows §3.2 gives a base block HIGH PRIORITY: strength and anaerobic capacity, plus a
# reasonable amount of aerobic capacity. It MAINTAINS ONLY aerobic and anaerobic power.
_BASE_MAINTAINED_ONLY: tuple[str, ...] = ("power", "power_endurance")
_BASE_PRIORITISED_ON_WALL: tuple[str, ...] = ("endurance", "anaerobic_capacity")

# His worked base week is "0.5x Aero/An Pow" against four strength sessions out of five, i.e.
# ~10% across BOTH maintained qualities. Measured 2.5-10.7%, so 15 has margin and still bites.
_BASE_MAINTAINED_CEILING_PCT = 15

_BEGINNERS = tuple(row for row in _CLIMBERS if row[0] is Level.BEGINNER)

# A plain indoor bouldering gym, which is the equipment column PR C's whole pass condition is
# stated over, and the session counts the monotonicity guard steps through against `n + 1`.
_WALL_ONLY: tuple[str, ...] = ("bouldering_wall",)
_SESSION_STEPS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)


@dataclass(frozen=True, slots=True)
class _Sweep:
    """One climber the monotonicity guard adds a day to. `label` is the exemption register's key."""

    label: str
    discipline: Discipline
    system: GradeSystemKey
    grade: str
    equipment: tuple[str, ...]
    gap: int


# ⚠️ This sweep used to be `sessions` ALONE against one intermediate sport climber holding the
# full vocabulary, and that is exactly why both accepted exceptions below sat unsampled through
# three rounds of PR C: neither of them fires on that profile, so an accepted exception and an
# untested gap were indistinguishable here. Every band and both ladders now, in two equipment
# columns — the full vocabulary at the file's default gap, and a plain bouldering gym at a gap of
# 4. The second column is not decoration: it is the only one of the four combinations that
# inverts inside a TAPER week at all, which is four of the ten rows below, and a wall-only gym is
# also the harshest equipment column for this invariant because there is no off-the-wall
# substitute for the block the allocator declines to place.
_MONOTONICITY_SWEEP: tuple[_Sweep, ...] = tuple(
    _Sweep(
        f"{level.value} {discipline.value} {grade}, {column}",
        discipline,
        system,
        grade,
        equipment,
        gap,
    )
    for column, equipment, gap in (
        ("full vocabulary, gap 3", _ALL_EQUIPMENT, 3),
        ("bouldering wall only, gap 4", _WALL_ONLY, 4),
    )
    for level, discipline, system, grade in _CLIMBERS
)


@dataclass(frozen=True, slots=True)
class _AcceptedInversion:
    """One (climber, session step) where adding a day is ALLOWED to cost climbing minutes.

    Written as DATA on the idiom of `DELIBERATELY_UNPRESCRIBED`, and asserted in BOTH directions
    below: an inversion with no row here is a defect, and a row that no longer inverts is a stale
    claim about the generator. `max_loss_seconds` is the leash — it is the worst loss measured on
    this row, so an accepted exception cannot quietly grow into a larger one under its own reason.
    """

    sweep_label: str
    from_sessions: int
    max_loss_seconds: int
    reason: str


# Kilian, 2026-09-04: he takes this inversion at 1 → 2 and at that step ONLY. A row of this class
# at any other step is a defect rather than an exception, which is why the register keys on both.
_SOLO_WEEK_AIMS_AT_100_PCT = (
    "A one-session week is climbing and nothing else and aims at 100% of its minutes on a wall "
    "(`solo` in `_microcycle`, issue #84's decision), while two sessions put this climber on "
    "their band's target range instead — 50-62% for the four advanced rows, 75-82% for the "
    "intermediate one. Two decisions colliding, and no amount of per-session arithmetic "
    "reconciles them: the fix is either that a solo week stops aiming at 100%, or that this "
    "invariant is restated for a FIXED band rather than for otherwise-identical inputs. Kilian "
    "took the inversion instead. Re-measured after §3.4's ordering made a session's window "
    "follow its hardest block: 500 s (advanced sport, week 11, power), 490 s (advanced boulder, "
    "week 19, performance), 312 s for both advanced rows in a bouldering-wall-only gym at gap 4 "
    "(week 11, power) and 32 s (intermediate sport, week 11, power). Two of those five rows are "
    "new at this step and the wall-only pair is new to the register altogether."
)

# The two inversions the general-strength re-file leaves at 2 → 3 sessions. Their own reason:
# `_SOLO_WEEK_AIMS_AT_100_PCT` is about a one-session week and does not reach this step.
_A_THIRD_SESSION_REMOVES_THE_TOP_UP = (
    "At two sessions a week the whole week lands in two sessions that both run short of their "
    "protocol window, so the length pass spends the blocks `MAX_BLOCKS_PER_SESSION` reserves "
    "and — with `wall_pref` at `first` — spends them ON THE WALL: week 9 gives its Monday a "
    "FIFTH block and 36 min of limit boulders against a 40 min floor. A third session removes "
    "the shortfall, every session stops at `BLOCKS_PER_SESSION`, and the third slot's support "
    "rotation shifts with the session index onto a different exercise — off the wall in week "
    "10, where 13 min of on-wall core tension becomes 2 min of general strength and the new "
    "session returns 11 min of technique. Measured: both weeks stay INSIDE their band, 65.0% → "
    "53.5% and 61.8% → 58.7% against 50-65, so what is traded is a two-session week's top-up "
    "rather than the climbing the band asks for. The intermediate row this reason also covered "
    "stopped inverting under §3.4's ordering and was deleted."
)

# The register. Both arms of the guard read it, and the beginners are absent because they do not
# invert at all — their 85-90% band is close enough to a solo week's 100% that nothing is traded.
_ACCEPTED_INVERSIONS: tuple[_AcceptedInversion, ...] = (
    _AcceptedInversion(
        "advanced sport 7c, full vocabulary, gap 3", 1, 500, _SOLO_WEEK_AIMS_AT_100_PCT
    ),
    _AcceptedInversion(
        "advanced boulder 7C, full vocabulary, gap 3", 1, 490, _SOLO_WEEK_AIMS_AT_100_PCT
    ),
    _AcceptedInversion(
        "advanced sport 7c, bouldering wall only, gap 4", 1, 312, _SOLO_WEEK_AIMS_AT_100_PCT
    ),
    _AcceptedInversion(
        "advanced boulder 7C, bouldering wall only, gap 4", 1, 312, _SOLO_WEEK_AIMS_AT_100_PCT
    ),
    _AcceptedInversion(
        "intermediate sport 6c, full vocabulary, gap 3", 1, 32, _SOLO_WEEK_AIMS_AT_100_PCT
    ),
    _AcceptedInversion(
        "advanced boulder 7C, full vocabulary, gap 3", 2, 700, _A_THIRD_SESSION_REMOVES_THE_TOP_UP
    ),
)


def _input(
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    mask: int,
    gap: int = 3,
    equipment: tuple[str, ...] = _ALL_EQUIPMENT,
) -> PlannerInput:
    """A plannable climber with no injuries, holding the whole vocabulary unless told otherwise."""
    current = ordinal_of(system, label)
    return PlannerInput(
        discipline=discipline,
        current_ordinal=current,
        target_ordinal=current + gap,
        sessions_per_week=sessions,
        available_weekdays=mask,
        strength_aspect_key=None,
        weakness_aspect_key=None,
        open_injury_keys=(),
        equipment_keys=equipment,
        start_date=_MONDAY,
    )


def _block_seconds(block: BlockBlueprint) -> int:
    """Recomputed here rather than imported, so the guard does not share the code it checks."""
    per_set = sum(
        (item.target_work_seconds or (item.target_reps or 0) * SECONDS_PER_REP)
        + (item.target_rest_seconds or 0)
        for item in block.sets
    )
    return (
        per_set
        + max(len(block.sets) - 1, 0) * (block.rest_between_sets_seconds or 0)
        + (block.rest_after_seconds or 0)
    )


def _on_wall(block: BlockBlueprint) -> bool:
    """Wall time is read off the exercise's own equipment, from the library, not off the block."""
    return bool(WALL_EQUIPMENT.intersection(_BY_KEY[block.exercise_key].equipment_keys))


def _weekly_matrix(plan: PlanBlueprint) -> list[tuple[int, Phase, int, int, int]]:
    """`(week_no, phase, wall_seconds, other_seconds, climbing_sessions)` for every week."""
    rows: list[tuple[int, Phase, int, int, int]] = []
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            wall = other = climbing = 0
            for session in microcycle.sessions:
                on_wall = sum(_block_seconds(b) for b in session.blocks if _on_wall(b))
                wall += on_wall
                other += sum(_block_seconds(b) for b in session.blocks if not _on_wall(b))
                climbing += 1 if on_wall else 0
            rows.append((microcycle.week_no, microcycle.phase, wall, other, climbing))
    return rows


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [1, 2, 3, 5, 7])
def test_every_week_meets_its_bands_climbing_floor(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """The #84 matrix, recomputed per WEEK, not over the plan's total: a 28% plan and a plan with
    one empty week share an average. A DELOAD answers to its own lower floor, and is measured."""
    assert level_for(discipline, ordinal_of(system, label)) is level
    plan = generate(_input(discipline, system, label, sessions, 0b111_1111))
    matrix = _weekly_matrix(plan)
    assert matrix
    for week_no, phase, wall, other, climbing in matrix:
        floor = week_climbing_floor_pct(discipline, ordinal_of(system, label), phase)
        assert wall > 0, (
            f"week {week_no} ({phase.value}) prescribes no climbing at all for a "
            f"{level.value} — that is issue #84's week 19."
        )
        assert climbing >= min(sessions, 2), (
            f"week {week_no} ({phase.value}) has {climbing} climbing session(s) of "
            f"{sessions} scheduled; every week owes 1-2."
        )
        assert wall * 100 >= floor * (wall + other), (
            f"week {week_no} ({phase.value}) is {100 * wall / (wall + other):.0f}% wall "
            f"time against a {floor}% floor for {level.value}: {wall // 60} min climbing "
            f"vs {other // 60} min of everything else."
        )


def test_a_single_session_week_is_climbing_and_nothing_else() -> None:
    """`sessions_per_week == 1` gets a climbing session — not a hangboard, not mobility."""
    plan = generate(_input(Discipline.BOULDER, GradeSystemKey.FONT, "6C", 1, 0b000_0100))
    sessions = [
        session
        for mesocycle in plan.mesocycles
        for microcycle in mesocycle.microcycles
        for session in microcycle.sessions
    ]
    assert len(sessions) == plan.week_count
    for session in sessions:
        assert session.blocks
        assert all(_on_wall(block) for block in session.blocks), (
            f"a one-day week prescribed {[b.exercise_key for b in session.blocks]}; with one "
            f"session there is no better use of it than climbing."
        )


@cache
def _climbing_inversions(sweep: _Sweep) -> tuple[tuple[int, int, Phase, int], ...]:
    """Every `(from_sessions, week_no, phase, seconds_lost)` where a day added cost climbing."""
    matrices = {
        sessions: _weekly_matrix(
            generate(
                _input(
                    sweep.discipline,
                    sweep.system,
                    sweep.grade,
                    sessions,
                    0b111_1111,
                    gap=sweep.gap,
                    equipment=sweep.equipment,
                )
            )
        )
        for sessions in range(min(_SESSION_STEPS), max(_SESSION_STEPS) + 2)
    }
    return tuple(
        (sessions, week_no, phase, wall - wall_more)
        for sessions in _SESSION_STEPS
        for (week_no, phase, wall, _o, _c), (_w, _p, wall_more, _o2, _c2) in zip(
            matrices[sessions], matrices[sessions + 1], strict=True
        )
        if wall_more < wall
    )


@pytest.mark.parametrize("sweep", _MONOTONICITY_SWEEP, ids=lambda sweep: sweep.label)
def test_more_available_days_never_reduces_climbing_minutes(sweep: _Sweep) -> None:
    """Monotonicity, measured week by week: a day added is climbing added, never traded.

    The exceptions are DATA rather than silence. `_ACCEPTED_INVERSIONS` names every step Kilian
    has accepted, its reason, and the worst loss it was accepted at — so a reader can tell an
    accepted exception from an untested gap without leaving this file.
    """
    accepted = {(row.sweep_label, row.from_sessions): row for row in _ACCEPTED_INVERSIONS}
    for from_sessions, week_no, phase, loss in _climbing_inversions(sweep):
        row = accepted.get((sweep.label, from_sessions))
        assert row is not None, (
            f"going from {from_sessions} to {from_sessions + 1} sessions dropped week "
            f"{week_no} ({phase.value}) by {loss} s of climbing for a {sweep.label} climber. A "
            f"day added is climbing added, never traded. If that is a decision rather than a "
            f"defect it owes a row in _ACCEPTED_INVERSIONS carrying the reason and the cost."
        )
        assert loss <= row.max_loss_seconds, (
            f"{sweep.label} at {from_sessions} -> {from_sessions + 1} is an ACCEPTED inversion, "
            f"but week {week_no} ({phase.value}) now loses {loss} s against the "
            f"{row.max_loss_seconds} s it was accepted at, so the exception has grown into a "
            f"different one. The row reads: {row.reason}"
        )


def test_no_accepted_monotonicity_exception_has_quietly_become_true() -> None:
    """⚠️ GUARD, reverse arm. An accepted exception and an unsampled gap look identical in a
    suite, which is how both rows below spent three rounds of PR C invisible. A row that no
    longer costs any climbing — or whose label never matched a swept climber at all — is a claim
    about the generator that has stopped being true, and the next reader would trust it."""
    inverted = {
        (sweep.label, from_sessions)
        for sweep in _MONOTONICITY_SWEEP
        for from_sessions, _week, _phase, _loss in _climbing_inversions(sweep)
    }
    stale = sorted(
        f"{row.sweep_label} at {row.from_sessions} -> {row.from_sessions + 1}"
        for row in _ACCEPTED_INVERSIONS
        if (row.sweep_label, row.from_sessions) not in inverted
    )
    assert not stale, (
        f"{stale} are accepted in _ACCEPTED_INVERSIONS and now lose no climbing at all. Delete "
        f"those rows — the register is a measurement of the generator, not documentation of it."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
def test_every_session_lands_inside_its_types_window(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str
) -> None:
    """The window belongs to the session's TYPE, i.e. its leading block's protocol kind. The
    ceiling binds in every phase; the floor only in a loading one, or a deload is not one."""
    del level
    plan = generate(_input(discipline, system, label, 5, 0b111_1111))
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            unloading = microcycle.phase in {Phase.DELOAD, Phase.TAPER}
            for session in microcycle.sessions:
                if not session.blocks:
                    continue
                minutes = sum(_block_seconds(b) for b in session.blocks) / 60
                kind = session.blocks[0].protocol_kind
                floor, ceiling = session_window(kind)
                assert minutes <= ceiling, (
                    f"week {microcycle.week_no}, a {kind.value}-led session runs "
                    f"{minutes:.0f} min against a {ceiling} min window."
                )
                assert unloading or minutes >= floor, (
                    f"week {microcycle.week_no} ({microcycle.phase.value}), a {kind.value}-led "
                    f"session runs {minutes:.0f} min against a {floor} min floor."
                )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
def test_a_fixed_volume_protocol_is_never_padded_and_an_expandable_one_is_capped(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str
) -> None:
    """Extra time may not become extra volume where low volume is the protocol. Compared against
    the AUTHORED prescription, so a grown block shows even when the session still fits."""
    del level
    plan = generate(_input(discipline, system, label, 5, 0b111_1111))
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                for block in session.blocks:
                    spec = _BY_KEY[block.exercise_key]
                    authored = next(
                        p.sets for p in spec.prescriptions if p.phase is microcycle.phase
                    )
                    expandable = (
                        block.aspect_key,
                        block.protocol_kind,
                    ) in _MAY_EXPAND and microcycle.phase not in {Phase.DELOAD, Phase.TAPER}
                    ceiling = authored * MAX_EXPANSION_FACTOR if expandable else authored
                    assert authored <= len(block.sets) <= ceiling, (
                        f"{block.exercise_key} ({block.protocol_kind.value}, "
                        f"{microcycle.phase.value}) is authored at {authored} sets and was "
                        f"prescribed {len(block.sets)}; expandable={expandable}."
                    )


def test_the_expandability_table_cannot_widen_without_a_decision() -> None:
    """Pinned literals, on `tests/test_library_contract.py`'s pattern: widening any of these is
    a training decision — a deload has its own prescriptions — so it must not pass silently."""
    assert EXPANDABLE_ASPECTS == frozenset({"endurance", "technique"})
    assert EXPANDABLE_PROTOCOLS == frozenset(
        {ProtocolKind.LAPS, ProtocolKind.CIRCUIT, ProtocolKind.OTHER}
    )
    assert UNLOADING_PHASES == frozenset({Phase.DELOAD, Phase.TAPER})
    assert MAX_EXPANSION_FACTOR == 2


def test_a_climber_with_nowhere_to_climb_gets_a_plan_that_names_what_is_missing() -> None:
    """Issue #61's naming half: the plan is complete — full supplementary sessions — and every
    week says out loud which equipment rows would put real climbing in it."""
    current = ordinal_of(GradeSystemKey.FRENCH, "6c")
    plan = generate(
        PlannerInput(
            discipline=Discipline.SPORT,
            current_ordinal=current,
            target_ordinal=current + 3,
            sessions_per_week=3,
            available_weekdays=0b010_0101,
            strength_aspect_key=None,
            weakness_aspect_key=None,
            open_injury_keys=(),
            equipment_keys=("hangboard", "pull_up_bar", "resistance_bands"),
            start_date=_MONDAY,
        )
    )
    named: list[str] = []
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                assert len(session.blocks) >= BLOCKS_PER_SESSION, (
                    "an unbuildable climbing floor must not thin the plan; it names the gap."
                )
                wall = [shortfall for shortfall in session.shortfalls if shortfall.options]
                assert wall, f"week {microcycle.week_no} has no climbing and does not say why."
                named.extend(
                    key for shortfall in wall for option in shortfall.options for key in option
                )
    assert set(named) & WALL_EQUIPMENT, (
        f"the shortfalls name {sorted(set(named))} and not one place to climb."
    )


def _hang_sessions(plan: PlanBlueprint, phase_filter: frozenset[Phase] | None) -> list[int]:
    """Sessions per week carrying a real hangboard block, for the weeks in `phase_filter`."""
    return [
        sum(
            1
            for session in microcycle.sessions
            if any(
                block.aspect_key == "finger_strength" and block.protocol_kind in _FINGER_PROTOCOLS
                for block in session.blocks
            )
        )
        for mesocycle in plan.mesocycles
        for microcycle in mesocycle.microcycles
        if phase_filter is None or microcycle.phase in phase_filter
    ]


# ⚠️ THE DIMENSION THIS SWEEPS IS PLAN LENGTH, and it is the one the gate was missing. Round 3
# reordered `_wall_pref` to put a session's own length ahead of the week's share and this test
# stayed GREEN at the gap of 3 every other test here uses. Gap is therefore sampled at both ends
# of `periodisation`'s week_count table (0 → 8 weeks, 6 → 32) plus that 3. `sessions_per_week`
# runs the full 2-7 for completeness but is NOT the exposing dimension, and neither is the
# weekday mask: all four masks measured identical to a tenth of a point, because a mask moves
# which weekday a session lands on and never how many blocks it gets.
# ⚠️ THE ADVANCED CEILING IS 65: A RE-BASELINE OFF A DEFECT, NOT A WEAKENED GUARD. 62 was only
# green because it averaged in the deload weeks that now answer to `DELOAD_CLIMBING_FLOOR_PCT`;
# exclude them and `dev` itself measured 62.3% before any of this. Every breach since has been a
# gap-0 (8-week) plan, where the performance block is half the plan — the ceiling comes back DOWN
# when the fixed 12-week plan length lands (backlog item 3). 64 went to 65 when §3.4's ordering
# made a session's window follow its hardest block, lifting the honest advanced band from
# 58.8-63.3% to 60.6-64.4%: the one combination over 64 is advanced sport at 2 sessions, gap 0,
# 64.4%. Re-measured on this code, the `_wall_pref` sabotage reaches 68.6/66.3/66.2% (sport) and
# 66.0/65.8/66.9% (boulder) at gaps 0/3/6, so 65 bites at every sampled gap on both ladders.
@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 4, 5, 6, 7])
@pytest.mark.parametrize("gap", [0, 3, 6])
def test_the_measured_climbing_share_lands_inside_its_bands_target_range(
    level: Level,
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    gap: int,
) -> None:
    """The band is a TARGET RANGE, not only a floor: round 1 met every floor at 84-91%. DELOAD
    weeks are out — `DELOAD_CLIMBING_FLOOR_PCT` governs them and the per-week test measures it."""
    low, high = _TARGET_BAND[level]
    every = _weekly_matrix(generate(_input(discipline, system, label, sessions, 0b111_1111, gap)))
    matrix = [row for row in every if row[1] is not Phase.DELOAD]
    wall = sum(row[2] for row in matrix)
    other = sum(row[3] for row in matrix)
    share = 100 * wall / (wall + other)
    assert low <= share <= high, (
        f"a {level.value} training {sessions}x a week on a grade gap of {gap} "
        f"({len(matrix)} weeks) gets {share:.1f}% of prescribed minutes "
        f"on a wall, against a target band of {low}-{high}%: {wall // 60} min climbing vs "
        f"{other // 60} min of everything else. Above the band the supplementary work is "
        f"crowded out; below it the plan has stopped being a climbing plan."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_a_loading_week_meets_its_bands_finger_strength_floor(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """Finger strength is the strongest single predictor of climbing performance and matters more
    as level rises, so a strength or power week owes real hangs — not a leftover slot."""
    wanted = _FINGER_SESSIONS_PER_WEEK[level]
    plan = generate(_input(discipline, system, label, sessions, 0b111_1111))
    weeks = _hang_sessions(plan, _FINGER_PHASES)
    assert weeks, "no strength or power week in the plan; the parametrisation is wrong."
    accepted = {(row.profile, row.sessions, row.loading_week): row for row in _ACCEPTED_FINGER_GAPS}
    for index, count in enumerate(weeks, start=1):
        row = accepted.get((_profile(level, discipline, label), sessions, index))
        if row is not None:
            assert count >= row.delivered, (
                f"{row.profile} at {sessions}x, loading week {index} is an ACCEPTED gap that "
                f"delivered {row.delivered} hangboard session(s) and now delivers {count}, so "
                f"the exception has grown into a different one. The row reads: {row.reason}"
            )
            continue
        assert count >= wanted, (
            f"loading week {index} of a {level.value}'s plan has {count} real max-hang or "
            f"repeater session(s) against a floor of {wanted}. Round 1 measured eight minutes "
            f"of finger work a week for an advanced climber. If that is a decision rather than "
            f"a defect it owes a row in _ACCEPTED_FINGER_GAPS carrying the reason and the cost."
        )


def test_no_accepted_finger_strength_gap_has_quietly_become_true() -> None:
    """⚠️ GUARD, reverse arm, `_ACCEPTED_INVERSIONS`' contract applied to the hangboard floor: a
    registered gap that now meets its floor is a claim about the generator that has expired."""
    stale: list[str] = []
    for row in _ACCEPTED_FINGER_GAPS:
        climber = _BY_PROFILE.get(row.profile)
        assert climber is not None, (
            f"{row.profile} in _ACCEPTED_FINGER_GAPS matches no climber in _CLIMBERS."
        )
        level, discipline, system, label = climber
        weeks = _hang_sessions(
            generate(_input(discipline, system, label, row.sessions, 0b111_1111)), _FINGER_PHASES
        )
        count = weeks[row.loading_week - 1] if row.loading_week <= len(weeks) else -1
        if count >= _FINGER_SESSIONS_PER_WEEK[level]:
            stale.append(f"{row.profile} at {row.sessions}x, loading week {row.loading_week}")
    assert not stale, (
        f"{stale} are accepted in _ACCEPTED_FINGER_GAPS and now meet their band's floor. Delete "
        f"those rows — the register is a measurement of the generator, not documentation of it."
    )


@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_the_finger_strength_floor_RISES_WITH_THE_BAND(sessions: int) -> None:
    """The other direction, and the arm that keeps the zero honest: a beginner must get strictly
    less structured hangboarding than an intermediate, and an intermediate than an advanced."""
    counts = [
        sum(_hang_sessions(generate(_input(discipline, system, label, sessions, 0b111_1111)), None))
        for _level, discipline, system, label in _CLIMBERS
        if discipline is Discipline.SPORT
    ]
    beginner, intermediate, advanced = counts
    assert beginner < intermediate < advanced, (
        f"hangboard sessions per plan at {sessions}x a week are beginner={beginner}, "
        f"intermediate={intermediate}, advanced={advanced}; the band has to order them."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
def test_priority_work_never_sits_behind_volume_work(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str
) -> None:
    """Quality of effort decides the adaptation, so a max hang cannot sit behind 35 minutes of
    climbing. The one exemption is a deload's own technique or mobility lead, narrowed to those."""
    del level
    plan = generate(_input(discipline, system, label, 5, 0b111_1111))
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                order = [block.order_index for block in session.blocks]
                assert order == sorted(order) == list(range(1, len(order) + 1)), (
                    f"week {microcycle.week_no} has blocks indexed {order}."
                )
                seen_volume: list[str] = []
                deload_lead = microcycle.phase is Phase.DELOAD
                for block in session.blocks:
                    if block.protocol_kind in _VOLUME_PROTOCOLS and not (
                        deload_lead and block.aspect_key in _DELOAD_LEAD_ASPECTS
                    ):
                        seen_volume.append(block.exercise_key)
                    assert not (block.protocol_kind in _PRIORITY_PROTOCOLS and seen_volume), (
                        f"week {microcycle.week_no} ({microcycle.phase.value}) prescribes "
                        f"{block.exercise_key} ({block.protocol_kind.value}) after "
                        f"{seen_volume}; fixed-volume quality work leads a session."
                    )


@cache
def _plan(
    discipline: Discipline, system: GradeSystemKey, label: str, sessions: int, mask: int
) -> PlanBlueprint:
    """One plan, cached: the two §3.4 guards below sweep the same twenty-four of them."""
    return generate(_input(discipline, system, label, sessions, mask))


def _day_tier(session: SessionBlueprint) -> int:
    """How hard the DAY is: its hardest block on §3.4's chain, because the source's second half
    is about the day. A block-less Recovery session sinks past every tier there is."""
    return min((_TIER[block.aspect_key] for block in session.blocks), default=len(_INTENSITY_TIERS))


def _back_to_back(
    microcycle: MicrocycleBlueprint,
) -> list[tuple[SessionBlueprint, SessionBlueprint]]:
    """This week's pairs of sessions on CONSECUTIVE weekdays. Sunday to Monday is not one of
    them: the next Monday is a different microcycle, possibly in a different phase."""
    days = sorted(microcycle.sessions, key=lambda session: session.weekday)
    return [
        (first, second)
        for first, second in zip(days, days[1:], strict=False)
        if second.weekday == first.weekday + 1
    ]


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_a_session_works_DOWN_barrows_intensity_chain(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD. §3.4 within one session: "always start with the most intense and work down to
    the least intense", read off `order_index` and restricted to the four aspects it names."""
    del level
    paired = 0
    for mesocycle in _plan(discipline, system, label, sessions, 0b111_1111).mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                blocks = sorted(session.blocks, key=lambda block: block.order_index)
                chain = [block for block in blocks if block.aspect_key in _INTENSITY_CHAIN]
                tiers = [_TIER[block.aspect_key] for block in chain]
                paired += 1 if len(tiers) >= 2 else 0
                assert tiers == sorted(tiers), (
                    f"week {microcycle.week_no} ({microcycle.phase.value}) prescribes "
                    f"{[block.aspect_key for block in blocks]}, which runs "
                    f"{[block.aspect_key for block in chain]} up §3.4's chain instead of down "
                    f"it. Easy work in front of hard work spoils the hard work."
                )
    assert paired >= _CHAIN_PAIRED_SESSIONS_FLOOR, (
        f"only {paired} session(s) of a {label} climber's plan at {sessions}x a week carry two "
        f"or more of {_INTENSITY_CHAIN}, against {_CHAIN_PAIRED_SESSIONS_FLOOR} measured. With "
        f"fewer than two chain aspects in a session there is no order to get wrong, so the arm "
        f"above would be green on a generator that had stopped ordering anything at all."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_back_to_back_days_run_HARDEST_FIRST(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD. §3.4 applies "equally whether within a single session or planning for
    consecutive days", so where two sessions are on adjacent weekdays the harder one leads."""
    del level
    pairs = 0
    for mesocycle in _plan(discipline, system, label, sessions, 0b111_1111).mesocycles:
        for microcycle in mesocycle.microcycles:
            for first, second in _back_to_back(microcycle):
                pairs += 1
                assert _day_tier(second) >= _day_tier(first), (
                    f"week {microcycle.week_no} ({microcycle.phase.value}) puts weekday "
                    f"{first.weekday} at tier {_day_tier(first)} in front of weekday "
                    f"{second.weekday} at tier {_day_tier(second)}, so the harder of two "
                    f"back-to-back days comes second: {first.title!r} then {second.title!r}."
                )
    assert pairs > 0 or sessions < _SESSIONS_WITH_BACK_TO_BACK_DAYS, (
        f"a {label} climber training {sessions}x a week contributed no back-to-back pair at "
        f"all, so this parametrisation proved nothing."
    )


def test_the_consecutive_day_rule_bites_ONLY_where_the_days_ARE_consecutive() -> None:
    """⚠️ GUARD, structural arm. A Mon/Wed/Fri week owes EXACTLY ZERO pairs, so its green above
    is by construction; a five-day week owes many, so the sweep is not green by construction."""
    spread = sum(
        len(_back_to_back(microcycle))
        for mesocycle in _plan(
            Discipline.SPORT, GradeSystemKey.FRENCH, "6c", 3, 0b001_0101
        ).mesocycles
        for microcycle in mesocycle.microcycles
    )
    assert spread == 0, (
        f"a Mon/Wed/Fri climber has no two adjacent training days, but the plan produced "
        f"{spread} back-to-back pair(s); `choose_weekdays` is no longer honouring the mask and "
        f"the untouched-week half of §3.4 is being tested on the wrong shape."
    )
    packed = sum(
        len(_back_to_back(microcycle))
        for mesocycle in _plan(
            Discipline.SPORT, GradeSystemKey.FRENCH, "6c", 5, 0b111_1111
        ).mesocycles
        for microcycle in mesocycle.microcycles
    )
    assert packed > 0, f"a five-day week produced {packed} back-to-back pairs; nothing to order."


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_a_TAPER_WEEK_DROPS_every_minute_of_capacity_work(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD. §3.3 drops **ALL** An Cap, Aero Cap and ARC from a taper, so this is per WEEK
    and it is zero: `endurance` was 47% of the taper's minutes and ARC its largest block."""
    del level
    weeks = 0
    for mesocycle in _plan(discipline, system, label, sessions, 0b111_1111).mesocycles:
        for microcycle in mesocycle.microcycles:
            if microcycle.phase is not Phase.TAPER:
                continue
            weeks += 1
            blocks = [block for session in microcycle.sessions for block in session.blocks]
            dropped = {
                aspect: sum(_block_seconds(b) for b in blocks if b.aspect_key == aspect)
                for aspect in _TAPER_DROPPED
            }
            assert not any(dropped.values()), (
                f"week {microcycle.week_no}'s taper prescribes {dropped} (seconds) of the "
                f"capacity work §3.3 says to drop entirely: "
                f"{sorted({b.exercise_key for b in blocks if b.aspect_key in _TAPER_DROPPED})}."
            )
            assert sum(_block_seconds(block) for block in blocks), (
                f"week {microcycle.week_no}'s taper prescribes nothing at all, so its zero "
                f"above is vacuous rather than a dropped quality."
            )
    assert weeks, f"a {label} climber at {sessions}x a week has no taper week to check."


def test_the_TAPER_CARRIES_hard_strength_and_hard_aerobic_power() -> None:
    """⚠️ GUARD. §3.3's other half. Gym strength reaches 6 of the 24 taper weeks, so its
    presence arm is POOLED and the other two are per week. Held intensity is pooled too."""
    minutes: Counter[str] = Counter()
    weak: list[tuple[int, str, list[int | None]]] = []
    legs: set[str] = set()
    weeks = 0
    for _level, discipline, system, label in _CLIMBERS:
        for sessions in (2, 3, 5, 7):
            for mesocycle in _plan(discipline, system, label, sessions, 0b111_1111).mesocycles:
                for microcycle in mesocycle.microcycles:
                    if microcycle.phase is not Phase.TAPER:
                        continue
                    weeks += 1
                    present = {
                        block.aspect_key
                        for session in microcycle.sessions
                        for block in session.blocks
                    }
                    absent = [a for a in _TAPER_HARD_PER_WEEK if a not in present]
                    assert not absent, (
                        f"a {label} climber at {sessions}x a week gets a taper week "
                        f"({microcycle.week_no}) with no {absent}. §3.3's taper is made of hard "
                        f"strength/power and hard aerobic power, and 'maximal efforts, hard "
                        f"route-like circuits' is copy ONE climber reads about their OWN week."
                    )
                    for session in microcycle.sessions:
                        for block in session.blocks:
                            minutes[block.aspect_key] += _block_seconds(block)
                            if block.aspect_key not in _TAPER_HARD:
                                continue
                            rpes = [item.target_rpe for item in block.sets]
                            if any(r is None or r < _TAPER_HARD_RPE_FLOOR for r in rpes):
                                weak.append((microcycle.week_no, block.exercise_key, rpes))
                            if block.aspect_key == "general_strength" and (
                                block.exercise_key not in _TAPER_STRENGTH_ROWS
                            ):
                                legs.add(block.exercise_key)
    assert weeks == _TAPER_WEEKS_IN_THE_SWEEP, (
        f"the sweep reached {weeks} taper weeks, not {_TAPER_WEEKS_IN_THE_SWEEP}, so the pooled "
        f"presence arm below is being asserted over a different population than it was measured "
        f"on and 'reaches 2 of 24' is no longer the reason it is pooled."
    )
    for aspect in _TAPER_HARD:
        assert minutes[aspect] > 0, (
            f"no taper week in the sweep prescribes {aspect}, and §3.3 says a taper contains "
            f"ONLY hard strength/power and hard aerobic power. Its share was 0.0% before this "
            f"and a guard used to mandate that, so a zero here is the defect coming back."
        )
    assert not weak, (
        f"these taper blocks sit below RPE {_TAPER_HARD_RPE_FLOOR}: {weak}. §3.3 holds a "
        f"taper's intensity at the loading value or takes it higher — volume is the only thing "
        f"an unload week cuts, so a lowered RPE on a taper row is the wrong lever."
    )
    assert not legs, (
        f"the taper prescribes {sorted(legs)} for general strength. It carries "
        f"{sorted(_TAPER_STRENGTH_ROWS)} and nothing else: a heavy hinge or squat leaves "
        f"fatigue that hides the fitness the whole plan built, which is the half of the retired "
        f"`(taper, general_strength)` exemption that still argues."
    )


def _unload_ratio(plan: PlanBlueprint, phase: Phase) -> list[tuple[int, int, float, float]]:
    """Every unload week of one phase as (week, seconds, its own block's loading mean, %) — its
    OWN block, because a block is two mesocycles and a plan-wide mean hides the short ones."""
    rows: list[tuple[int, int, float, float]] = []
    loading: list[int] = []
    for mesocycle in plan.mesocycles:
        weeks = [
            sum(_block_seconds(block) for session in micro.sessions for block in session.blocks)
            for micro in mesocycle.microcycles
        ]
        if mesocycle.phase not in UNLOADING_PHASES:
            loading = weeks
            continue
        if mesocycle.phase is not phase or not loading:
            continue
        mean = sum(loading) / len(loading)
        rows.extend(
            (micro.week_no, seconds, mean, 100 * seconds / mean)
            for micro, seconds in zip(mesocycle.microcycles, weeks, strict=True)
        )
    return rows


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
@pytest.mark.parametrize("phase", [Phase.DELOAD, Phase.TAPER], ids=lambda phase: phase.value)
def test_an_UNLOAD_WEEK_KEEPS_at_least_forty_percent_of_its_own_blocks_volume(
    phase: Phase,
    level: Level,
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
) -> None:
    """⚠️ GUARD. Per week, per climber, DELOAD and TAPER apart: an unload week keeps at least
    `_UNLOAD_FLOOR_PCT` of its own block's loading mean. On the ceiling, see that comment."""
    del level
    rows = _unload_ratio(_plan(discipline, system, label, sessions, 0b111_1111), phase)
    assert rows, f"a {label} climber at {sessions}x a week has no {phase.value} week to measure."
    for week, seconds, mean, pct in rows:
        assert mean > 0, (
            f"week {week}'s {phase.value} sits against a loading mean of zero, so the ratio "
            f"below is vacuous rather than passing."
        )
        assert pct >= _UNLOAD_FLOOR_PCT, (
            f"a {label} climber at {sessions}x a week gets {phase.value} week {week} of "
            f"{seconds / 60:.1f} prescribed minutes against its own block's loading mean of "
            f"{mean / 60:.1f} = {pct:.1f}%, under the {_UNLOAD_FLOOR_PCT}% BOTH sources agree "
            f"an unload week keeps. Below this it is a rest week with a plan written on it."
        )


def _base_aspect_seconds(plan: PlanBlueprint) -> tuple[Mapping[str, int], Mapping[str, int]]:
    """Prescribed seconds per aspect over the plan's BASE weeks: all of them, then wall only."""
    every: dict[str, int] = {}
    wall: dict[str, int] = {}
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            if microcycle.phase is not Phase.BASE:
                continue
            for session in microcycle.sessions:
                for block in session.blocks:
                    seconds = _block_seconds(block)
                    every[block.aspect_key] = every.get(block.aspect_key, 0) + seconds
                    if _on_wall(block):
                        wall[block.aspect_key] = wall.get(block.aspect_key, 0) + seconds
    return every, wall


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _BEGINNERS)
@pytest.mark.parametrize("sessions", [1, 2, 3, 5, 7])
def test_a_beginners_base_block_keeps_the_qualities_it_ranks_last_last(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD. The phase's authored emphasis has to be where its minutes actually go, and
    nothing measured that: the emphasis order governed only the supplementary pass."""
    del level
    every, _wall = _base_aspect_seconds(
        generate(_input(discipline, system, label, sessions, 0b111_1111))
    )
    total = sum(every.values())
    assert total, "no base weeks in the plan; the parametrisation is wrong."
    tail = sum(every.get(key, 0) for key in _BASE_WALL_EMPHASIS[-2:])
    assert tail * 100 <= _BASE_TAIL_CEILING_PCT * total, (
        f"a {label} beginner training {sessions}x a week spends {100 * tail / total:.1f}% of "
        f"a base block's prescribed minutes on {' and '.join(_BASE_WALL_EMPHASIS[-2:])}, "
        f"against a ceiling of {_BASE_TAIL_CEILING_PCT}%: {tail // 60} min of "
        f"{total // 60}. Base ranks both of them last and PHASE_GUIDE[base] says so in prose."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _BEGINNERS)
@pytest.mark.parametrize("sessions", [1, 2, 3, 5, 7])
def test_the_quality_a_base_block_ranks_FIRST_takes_the_most_wall_time(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD, the head. A ceiling on the tail says nothing about which quality LEADS, and
    `PHASE_GUIDE[base]` publishes that endurance does. Issue #98 added two aspects to this row
    and one of them, anaerobic capacity, is high priority in base — Kilian's 2026-09-04 call was
    that endurance keeps the wall lead anyway, and this is where that decision is measured.
    ⚠️ Measured slack: endurance survives a demotion to the row's SEVENTH position because its
    exercises are long, and only goes red when it reaches the tail. It proves the lead, not the
    rank."""
    del level
    _every, wall = _base_aspect_seconds(
        generate(_input(discipline, system, label, sessions, 0b111_1111))
    )
    lead = _BASE_WALL_EMPHASIS[0]
    behind = {key: seconds for key, seconds in wall.items() if key != lead}
    assert all(wall.get(lead, 0) >= seconds for seconds in behind.values()), (
        f"a {label} beginner training {sessions}x a week gets {wall.get(lead, 0) // 60} min of "
        f"{lead} on a wall in a base block, against "
        f"{ {key: seconds // 60 for key, seconds in behind.items()} }. The quality base ranks "
        f"first has to take the most wall time, and PHASE_GUIDE[base] says so in prose."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _BEGINNERS)
@pytest.mark.parametrize("sessions", [1, 2, 3, 5, 7])
def test_a_base_block_only_MAINTAINS_the_qualities_the_source_maintains(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD, the maintenance arm. Base is about getting more climbing in, not about power
    (Kilian, 2026-09-04): the source prioritises endurance and anaerobic capacity and MAINTAINS
    aerobic and anaerobic power, so those two together may only take a maintenance share of a
    base block's wall time.

    ⚠️ Coverage GIVEN UP against the pairwise version this replaces, which demanded that the
    row's last aspect take no more wall time than each of the four ahead of it. This no longer
    detects `power` overtaking `technique`, nor `power_endurance` overtaking `power`, nor any
    ordering inside the prioritised pair. That is deliberate: the source distinguishes
    prioritised from maintained and orders neither pair internally, so the pairwise version was
    asserting a ranking nothing publishes — it passed on the old 11-turn wall ring by
    arithmetic luck and went red on the 15-turn one with the distribution still correct.
    """
    del level
    _every, wall = _base_aspect_seconds(
        generate(_input(discipline, system, label, sessions, 0b111_1111))
    )
    maintained = sum(wall.get(key, 0) for key in _BASE_MAINTAINED_ONLY)
    prioritised = sum(wall.get(key, 0) for key in _BASE_PRIORITISED_ON_WALL)
    assert prioritised, "no prioritised base wall time at all; the parametrisation is wrong."
    assert maintained * 100 <= _BASE_MAINTAINED_CEILING_PCT * (maintained + prioritised), (
        f"a {label} beginner training {sessions}x a week spends "
        f"{100 * maintained / (maintained + prioritised):.1f}% of a base block's PRIORITISED-"
        f"plus-MAINTAINED wall minutes on {' and '.join(_BASE_MAINTAINED_ONLY)}, against a "
        f"ceiling of {_BASE_MAINTAINED_CEILING_PCT}%: {maintained // 60} min against "
        f"{prioritised // 60} min of {' and '.join(_BASE_PRIORITISED_ON_WALL)}. Base maintains "
        f"those two qualities and trains these; it is not a power block."
    )
