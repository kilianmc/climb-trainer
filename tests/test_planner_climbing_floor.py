"""⚠️ GUARD. Climbing is the core of every week of a generated plan, and long enough to be one.
DB-free. Issue #84: the generator prescribed 28% of its minutes on a wall and gave week 19 none at
all, while ruff, mypy and the whole suite stayed green — because nothing recomputed the wall-minutes
matrix from a real plan. Every claim here is therefore MEASURED off `generate()`'s own output, never
restated from `server/domain/planner/climbing.py`: the PR #63 lesson was that 20 exercises landed in
the wrong tuple with 266 tests passing, and only recomputing the matrix caught it. The session
windows are the second half — a fixed-volume protocol must never be padded, because low volume *is*
the protocol — and WHICH climbing is the third: a phase's authored emphasis has to be where its
minutes go. Shown to fail before being trusted.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache

import pytest

from server.domain.exercises import EXERCISES, OPEN_CLIMBING_KEYS, ExerciseSpec, PrescriptionSpec
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner.blueprint import (
    BlockBlueprint,
    MicrocycleBlueprint,
    PlanBlueprint,
    SessionBlueprint,
    SetBlueprint,
)
from server.domain.planner.climbing import (
    ENERGY_SYSTEM_ASPECTS,
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
from server.domain.planner.generate import SECONDS_PER_REP, _Draft, _wall_pref, generate
from server.domain.planner.selection import BLOCKS_PER_SESSION
from server.domain.vocabulary import EQUIPMENT, Phase, ProtocolKind

_MONDAY = date(2026, 8, 24)
_ALL_EQUIPMENT = tuple(sorted(spec.key for spec in EQUIPMENT))
_BY_KEY = {spec.key: spec for spec in EXERCISES}

# Ruling 46's ROUNDS rule, restated here for `_MAY_EXPAND`'s own reason. This is the register that
# replaced this file's old `ceiling = authored` pin, which guarded AGAINST the progression #117
# owes: alactic max-effort work progresses by load or rounds, so its set count is a function of the
# loading week and pinning it to the authored number pinned weeks 1-3 byte-identical.
#
# ⚠️ Keyed on the PAIR and never on `aspect_key`: `power` x `circuit` is lactic anaerobic power and
# progresses by shorter rest instead, so an aspect-level entry here would licence padding it.
_ROUNDS_PER_LOADING_WEEK: Mapping[tuple[str, ProtocolKind], int] = {
    ("power", ProtocolKind.STRAIGHT_SETS): 1,
    ("power", ProtocolKind.LIMIT_BOULDER): 1,
    ("power", ProtocolKind.INTERVALS): 1,
}

# `power` x `intervals` holds one alactic row and one lactic one, and only the alactic one takes
# rounds. 15 s is above every alactic burst in the library and below every lactic interval.
_ALACTIC_WORK_SECONDS_MAX = 15
_WEEKS_PER_BLOCK = 4
_LOADING_WEEKS = 3

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
# ⚠️ Only `[0]` is ever asserted — see `_TARGET_BAND_IS_FLOOR_ONLY`. The high edge is kept
# because it is what the GENERATOR aims below, and deleting it here would hide that it exists.
_TARGET_BAND: Mapping[Level, tuple[int, int]] = {
    Level.BEGINNER: (85, 90),
    Level.INTERMEDIATE: (75, 82),
    Level.ADVANCED: (50, 65),
}

_TARGET_BAND_IS_FLOOR_ONLY = (
    "Ruling 28, Kilian, 2026-09-06, and an EXCEPTION to the rule that a band is asserted at both "
    "edges. Ruling 27's length fill is plain climbing and is now the largest single item in a "
    "session, so the honest measured share is 91.6-93.4 / 88.9-90.8 / 86.7-88.2% by level and the "
    "old ceilings cannot stand. Ruling 14 allows a ceiling to be re-based only if the sabotage it "
    "exists to catch still breaches the new number: re-based to 94/94/92 with `_wall_pref` forced "
    'to "first", 36 of 36 BEGINNER rows stayed GREEN, intermediate breached at gap 0 alone and '
    "advanced by 0.1-1.3 points. A ceiling the sabotage passes catches nothing while looking like "
    "it does, so there is NO ceiling arm here and none is owed. What `_wall_pref` promises is "
    "guarded per SESSION instead, by the test named after it. Ruling 17's unload floor took the "
    "same shape for the same reason, and its name says so too."
)

# Real max-hang / repeater sessions a LOADING week owes, per band. Beginner is zero by KILIAN'S
# DECISION, 2026-09-06: neither source scales hangboarding by level, so never attribute it to them.
# ⚠️ The order is STRICT and `test_the_finger_strength_floor_RISES_WITH_THE_BAND` asserts it off
# the generated plans. Now that the zero is a DECISION rather than the mis-attribution the audit
# found, the strictness owes its own reason (guard 5, ruling 35): both sources agree beginners
# habituate before they load hard, a max hang is the load-hard end of finger work, and the band
# that has earned the tissue tolerance is the one that gets more of it. Only the ZERO diverges.
# ⚠️ Its CONSEQUENCE, and why it costs nothing: the strict `<` forbids any future beginner
# habituation protocol from raising this floor. `_HABITUATION_PROTOCOLS` below is how a beginner
# gets finger work regardless — as scaled CONTENT, which is what the sources scale — and this
# floor counts `_FINGER_PROTOCOLS` only, so a habituation block can neither satisfy nor breach it.
_FINGER_SESSIONS_PER_WEEK: Mapping[Level, int] = {
    Level.BEGINNER: 0,
    Level.INTERMEDIATE: 1,
    Level.ADVANCED: 2,
}
_FINGER_PROTOCOLS = frozenset({ProtocolKind.MAX_HANG, ProtocolKind.REPEATERS})
_FINGER_PHASES = frozenset({Phase.STRENGTH, Phase.POWER})

# Ruling 35's CONTENT half, restated independently of `climbing.py` for `_MAY_EXPAND`'s reason:
# Dylan's weeks-1-4 habituation protocol, which the library authors for BASE and no later phase.
_HABITUATION_PROTOCOLS = frozenset({ProtocolKind.HOLD})
_HABITUATION_ROW = "hangboard_density_hangs"

# (profile, sessions) whose BASE weeks never draw `_HABITUATION_ROW`, with the mechanism and the
# measured cost. Asserted in BOTH directions inline below, on `_ACCEPTED_FINGER_GAPS`' contract:
# a registered pair that starts drawing the row is a stale claim about the generator and goes red.
# ⚠️ The GRADE GAP is NOT a dimension of it — measured identical at all five gaps, where #118's
# own headline was that a beginner draws the row at gap 3-5 and never at 1-2. What decides it is
# how many supplementary slots a BASE week has: `finger_strength` sits fifth in that block's
# emphasis and a beginner's band spends 85-90% of the week's minutes on a wall.
_BASE_HABITUATION_GAPS: Mapping[tuple[str, int], str] = {
    ("beginner sport 6a", 2): "3 BASE weeks of 2 sessions reach the finger slot 0 times",
    ("beginner boulder 6A", 2): "3 BASE weeks of 2 sessions reach the finger slot 0 times",
    ("beginner boulder 6A", 3): "3 BASE weeks of 3 sessions reach the finger slot 0 times",
    ("beginner sport 6a", 3): (
        "1 BASE finger block, and the rotation spends it on the GEARLESS holds row "
        "self_resisted_finger_isometrics; both rows are habituation, only one is BASE's own"
    ),
}


@dataclass(frozen=True, slots=True)
class _AcceptedFingerGap:
    """One (climber, sessions, loading week) that misses its band's hangboard floor. `delivered`
    is the measurement, so the row cannot widen, and the reverse arm fails one that stops firing."""

    profile: str
    sessions: int
    loading_week: int
    delivered: int
    reason: str


# The register, and EMPTY is a MEASUREMENT again: ruling 32 opened the one gate that cost a row.
# §3.4's ordering once repaired BOTH losses ruling 15 ACCEPTED rather than fixed — intermediate
# 2x/week's third loading-week hangboard session, and 420 s / 120 s of climbing on two boulder
# profiles at 2→3. Ruling 25's session length put the hangboard one back; ruling 32 had
# `_fill_finger_strength` read `_block_ceiling` instead of restating three blocks, because that
# session was losing to block COUNT, not to training. ⚠️ The CLIMBING FLOOR never was involved
# and must not be "repaired": it refuses 0 of 216 evaluations over 1176 weeks and a rewrite of
# it measured byte-identical. Registering a row or opening the slot is Kilian's, not done here.
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
# do by 40-60%". Warm-up EXCLUDED on both sides — the flat `WARMUP_MINUTES` is not a block, and
# it inflates the ratio by a session-count-dependent amount: the beginner 2x/week taper read
# 9.8% excluding and 35.6% including before this PR, which would have let a 7-minute taper week
# pass as a third of a loading week.
# ⚠️ The 60% CEILING is deliberately NOT asserted and is SETTLED, not owed (Kilian, 2026-09-05):
# on a recovery week the plan would rather leave work in than take too much out. Measured, 52 of
# 96 deload weeks run to 85.5% and taper weeks 49-68%. Do not add a ceiling arm here, and do not
# file it as a finding — a divergence from both sources normally is one, and this is the ruled
# exception. `PHASE_GUIDE` promises only this floor for the same reason.
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


_BEGINNERS = tuple(row for row in _CLIMBERS if row[0] is Level.BEGINNER)
_HARDER_BANDS = tuple(row for row in _CLIMBERS if row[0] is not Level.BEGINNER)


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

# Ruling 25's per-level session length, warm-up INCLUDED, and ruling 26's flat warm-up. Both
# restated independently of `climbing.py` and `generate.py` for `_MAY_EXPAND`'s reason.
# ⚠️ These are Kilian's numbers, never "the sources'": they are the HIGH end of Horst's per-session
# bands and above Lattice's measured medians. Warm-up is subtracted below because it is not a
# block, so it has no prescribed seconds to measure.
_SESSION_MINUTES_TARGET: Mapping[Level, int] = {
    Level.BEGINNER: 90,
    Level.INTERMEDIATE: 120,
    Level.ADVANCED: 150,
}
_WARMUP_MINUTES = 20
_LENGTH_FILL_MINUTES = 30


def _is_length_fill(block: BlockBlueprint, chunk: int) -> bool:
    """Whether this block IS ruling 27's fill: one of ruling 29's filler rows, in the fill's own
    shape — uniform timed sets, no rest inside one or between them, none longer than one chunk.
    Read off the blueprint and not off a flag, because a flag would be a wire-contract change to
    carry a test.

    ⚠️ **The FAMILY clause is load-bearing and the shape alone was not enough.** `band=None` in
    `_length_pick` draws only from `open_climbing_fill()`, i.e. only from `OPEN_CLIMBING_KEYS`,
    and `ordinary()` keeps those rows out of every other pool, so membership identifies the fill
    exactly. On shape alone, ruling 41's `easy_climbing_flush` (`endurance` × LAPS, 600 s, no
    rest field of any kind) matched the moment expansion gave it a second set, and the arm below
    then read the 30-minute chunk rule against a legitimately expanded authored block — 2 sets
    of 600 s against the 1 that 1200 s implies, red on all six climbers.
    """
    return (
        block.exercise_key in OPEN_CLIMBING_KEYS
        and block.rest_between_sets_seconds is None
        and all(
            item.target_work_seconds is not None
            and item.target_reps is None
            and item.target_rest_seconds is None
            and 0 < item.target_work_seconds <= chunk
            and item.target_work_seconds == block.sets[0].target_work_seconds
            for item in block.sets
        )
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

# ⚠️ Barrows §3.2/§4.2's two WEEKLY FREQUENCY ceilings, restated as this file's own data for
# `_MAY_EXPAND`'s reason: a guard that asks `hard_energy_day_ceiling()` for the number agrees
# with whatever that function returns, including a wrong one.
# ⚠️ The set is the three ENERGY SYSTEMS and deliberately not `INTENSITY_TIERS`' top tier, which
# holds `power` with `finger_strength` and `general_strength`. Strength is not an energy system:
# §4.2's worked base week runs FOUR strength sessions alongside ~3 hard energy days, so counting
# the strength aspects here would assert a ceiling on work the source explicitly prescribes.
_HARD_ENERGY_ASPECTS: frozenset[str] = frozenset({"anaerobic_capacity", "power", "power_endurance"})
_HARD_ENERGY_DAYS_PER_WEEK = 3

# ⚠️ The TAPER is exempt, and this is the SOURCED reason rather than a hole in the guard: §3.3
# makes a taper only hard strength/power and hard An Pow/Aero Pow with An Cap, Aero Cap and ARC
# dropped, so every taper session carries hard energy-system work BY CONSTRUCTION and v8.9.0
# authored it that way. Applying the ceiling here turns
# `test_the_TAPER_CARRIES_hard_strength_and_hard_aerobic_power` red and the displaced slots have
# nowhere to go, because `test_a_TAPER_WEEK_DROPS_every_minute_of_capacity_work` forbids the easy
# aspects. Measured under the ceiling: taper weeks run 4-5 hard days of 5 and 6-7 of 7.
# PERFORMANCE is NOT exempt — Peak 2 is 2x Aero Pow + 1x An Pow, already inside ~3.
_HARD_ENERGY_EXEMPT_PHASES: frozenset[Phase] = frozenset({Phase.TAPER})

# §4.2's worked example is per STAGE, not flat: Base 2x An Cap, Peak 1 1x, Peak 2 dropped.
# `performance` and `taper` are 0 through `DELIBERATELY_UNPRESCRIBED` and not through the
# ceiling, which is why the arm below asserts them and does not re-implement them.
_ANAEROBIC_ASPECT = "anaerobic_capacity"
_ANAEROBIC_SESSIONS_PER_WEEK: Mapping[Phase, int] = {
    Phase.BASE: 2,
    Phase.STRENGTH: 2,
    Phase.POWER: 1,
    Phase.POWER_ENDURANCE: 1,
    Phase.PERFORMANCE: 0,
    Phase.DELOAD: 1,
    Phase.TAPER: 0,
}

# The declared weakness, which is the largest categorical lever in the generator and had no
# number behind it: it overrides one supplementary slot per session (`_intended_aspect` slot 1)
# in every phase whose emphasis row carries the aspect. Both halves of it are guarded below.
_WEAKNESSES: tuple[str, ...] = ("power", "power_endurance")

# ⚠️ A one-session week is EXEMPT from the rise half, measured rather than assumed: a solo week
# has no supplementary pass at all (`_fill_supplementary` returns after the top-up), so slot 1 is
# never reached and the plan is byte-identical at every weakness value — 8804 s of power and
# 4492 s of power endurance whichever is declared. Two sessions is where the lever starts.
_WEAKNESS_NEEDS_A_SUPPLEMENTARY_SLOT = 2

_BEGINNERS = tuple(row for row in _CLIMBERS if row[0] is Level.BEGINNER)

# A plain indoor bouldering gym, which is the equipment column PR C's whole pass condition is
# stated over, and the session counts the monotonicity guard steps through against `n + 1`.
_WALL_ONLY: tuple[str, ...] = ("bouldering_wall",)
_SESSION_STEPS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)

# Ruling 55's two ceilings: the most of one plan any single exercise may take. The measured
# maxima and why the gap to them is this wide are in `test_no_single_exercise_DOMINATES_a_plan`.
_MONOCULTURE_BLOCK_SHARE_PCT = 17
_MONOCULTURE_MINUTE_SHARE_PCT = 23


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


# ⚠️ EMPTY, and that is a MEASUREMENT: ruling 27's length fill repaired every one of the seven
# rows this register held. Ruling 22 accepted three of them and its own reverse arm (below) is
# what deletes them — a row that stops inverting is not left as cover. The seven, with the loss
# each was accepted at: advanced sport 7c full-vocab gap 3 at 1→2 (500 s) and at 6→7 (120 s),
# advanced boulder 7C full-vocab gap 3 at 1→2 (490 s) and at 2→3 (700 s), intermediate sport 6c
# full-vocab gap 3 at 1→2 (184 s), and both intermediate wall-only gap-4 rows at 4→5 (388 s).
# Ruling 4 is unchanged and absolute; this register is its exception list and it now has none.
_ACCEPTED_INVERSIONS: tuple[_AcceptedInversion, ...] = ()


def _input(
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    mask: int,
    gap: int = 3,
    equipment: tuple[str, ...] = _ALL_EQUIPMENT,
    weakness: str | None = None,
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
        weakness_aspect_key=weakness,
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


def _weekly_aspect_sessions(plan: PlanBlueprint) -> list[tuple[int, Phase, Counter[str], int]]:
    """`(week_no, phase, sessions carrying each aspect, sessions carrying hard energy work)`.

    ⚠️ `_weekly_matrix` collapses the aspect dimension away, so this per-week PER-ASPECT view is
    new. A session CARRIES a quality by containing a block of it, never by what its first block
    is: An Cap reaches a session through the rotated wall ring, the length top-up and the
    supplementary fill, and a count keyed on the opener would miss two of the three.
    """
    rows: list[tuple[int, Phase, Counter[str], int]] = []
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            carried: Counter[str] = Counter()
            hard = 0
            for session in microcycle.sessions:
                aspects = {block.aspect_key for block in session.blocks}
                carried.update(aspects)
                hard += 1 if aspects & _HARD_ENERGY_ASPECTS else 0
            rows.append((microcycle.week_no, microcycle.phase, carried, hard))
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


def _heaviest_exercise(plan: PlanBlueprint) -> tuple[tuple[str, int, int], tuple[str, int, int]]:
    """`(key, its blocks, all blocks)` and `(key, its seconds, all seconds)` for the exercise
    taking most of each. Ruling 29's filler family is out of the numerator AND the denominator."""
    blocks: Counter[str] = Counter()
    seconds: Counter[str] = Counter()
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                for block in session.blocks:
                    if block.exercise_key in OPEN_CLIMBING_KEYS:
                        continue
                    blocks[block.exercise_key] += 1
                    seconds[block.exercise_key] += _block_seconds(block)
    block_key, block_count = blocks.most_common(1)[0]
    minute_key, minute_seconds = seconds.most_common(1)[0]
    return (
        (block_key, block_count, sum(blocks.values())),
        (minute_key, minute_seconds, sum(seconds.values())),
    )


@pytest.mark.parametrize("sweep", _MONOTONICITY_SWEEP, ids=lambda sweep: sweep.label)
def test_no_single_exercise_DOMINATES_a_plan(sweep: _Sweep) -> None:
    """⚠️ GUARD, ruling 55. No ONE exercise may take more than its ceiling of a generated plan.

    This is what issue #89 is CLOSED on, and "~36 exercises carry ~80% of every plan" is not the
    metric: that head count is mostly set by the ELIGIBLE POOL, which the climber's equipment
    decides, so it moves on a purchase rather than on a defect, and there is no concentrated head
    in a generated plan to begin with. Ruling 47 already priced the one route to moving the number
    — re-weighting the rotation — as presence and not proportion. What a plan does owe is that
    nothing in it is a MONOCULTURE, and that is a per-plan ceiling on its single largest exercise.

    BOTH halves, because PR #120 fixed a real monoculture at its cause and stated the result in
    MINUTES while the metric #89 tracked is BLOCKS: a ceiling on one leaves the other to regress.
    ⚠️ `OPEN_CLIMBING_KEYS` is out of both shares — those blocks are ruling 27's length fill
    arriving by ruling 29's decision, so counting them would measure a ruling, not a defect.

    Measured over eighteen plans per row here (`_SESSION_STEPS` x `None` and both `_WEAKNESSES`),
    216 across the twelve: the worst plan gives one exercise 14.85% of its blocks
    (`push_ups_with_scapular_control`, advanced wall-only at 5 sessions) and 19.79% of its minutes
    (`outdoor_redpoint_burns` in a one-session week, where block LENGTH rather than repetition is
    what concentrates). Both ceilings are deliberately wider than a rounding on those, and the gap
    is priced at HEAD rather than against a sweep no older commit has: narrow `prescribable()` to
    one row per cell — the pre-#120 condition, and a one-line break — and this same sweep puts
    `limit_boulders` at 17.50% of blocks and 30.78% of minutes, over both. `8edc819`'s own body is
    the historical anchor and needs no measurement of mine: 25.5-27.9% of a plan's minutes.
    """
    for sessions in _SESSION_STEPS:
        for weakness in (None, *_WEAKNESSES):
            plan = generate(
                _input(
                    sweep.discipline,
                    sweep.system,
                    sweep.grade,
                    sessions,
                    0b111_1111,
                    gap=sweep.gap,
                    equipment=sweep.equipment,
                    weakness=weakness,
                )
            )
            where = f"{sweep.label} at {sessions}/wk, weakness {weakness}"
            (key, count, blocks), (minute_key, seconds, total) = _heaviest_exercise(plan)
            assert count * 100 <= _MONOCULTURE_BLOCK_SHARE_PCT * blocks, (
                f"{where} gives {key} {count} of the plan's {blocks} prescribed blocks "
                f"({100 * count / blocks:.1f}%), against a ceiling of "
                f"{_MONOCULTURE_BLOCK_SHARE_PCT}%. One exercise is running the plan."
            )
            assert seconds * 100 <= _MONOCULTURE_MINUTE_SHARE_PCT * total, (
                f"{where} gives {minute_key} {seconds} of the plan's {total} prescribed seconds "
                f"({100 * seconds / total:.1f}%), against a ceiling of "
                f"{_MONOCULTURE_MINUTE_SHARE_PCT}%. One exercise is running the plan."
            )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
def test_every_session_lands_inside_its_types_window_AND_ITS_PHASES_LENGTH(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str
) -> None:
    """Ruling 27, both edges, in EVERY phase — which is the whole of what the fill promises.

    FLOOR: at least the protocols' own window (ruling 3's, the one a top-up chases) and at least
    ruling 25's length for this level, both scaled by the PHASE's volume factor. Ruling 25's half
    was not asserted before because the generator did not reach it; ruling 27's fill does, at
    every session count and in both gyms, so the guard now says so. The floor binds in an unload
    week too, at half — that scaling is what makes ruling 17's ≥40% hold by construction.
    ⚠️ CEILING: the widest block's window OR the floor plus ONE `LENGTH_FILL_MINUTES` chunk,
    whichever is larger. The second term is a real widening of ruling 3's mechanism and it is
    Kilian's (2026-09-06): the fill is one chunk sized to the gap and never smaller than 30
    minutes, so a session 12 minutes short of its length ends up ~18 minutes over it, and a
    plain-climbing block sized by the gap outruns `SESSION_WINDOWS` outright — measured, a
    beginner session of laps + intervals + straight sets + other ran 97 min against LAPS' 90-min
    ceiling and an intermediate one 120 against 100. Reading the LEADING block's window alone is
    the older defect this arm also still catches: a 15-minute limit-boulder block behind a max
    hang took MAX_HANG's 20-minute floor instead of LIMIT_BOULDER's 40.
    """
    plan = generate(_input(discipline, system, label, 5, 0b111_1111))
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            pct = 50 if microcycle.phase in {Phase.DELOAD, Phase.TAPER} else 100
            length = (_SESSION_MINUTES_TARGET[level] - _WARMUP_MINUTES) * pct / 100
            for session in microcycle.sessions:
                if not session.blocks:
                    continue
                minutes = sum(_block_seconds(b) for b in session.blocks) / 60
                kinds = {block.protocol_kind for block in session.blocks}
                window = max(session_window(kind)[0] for kind in kinds) * pct / 100
                floor = max(window, length)
                ceiling = max(
                    max(session_window(kind)[1] for kind in kinds), floor + _LENGTH_FILL_MINUTES
                )
                widest = max(kinds, key=lambda kind: session_window(kind)[1]).value
                held = sorted(kind.value for kind in kinds)
                assert minutes <= ceiling, (
                    f"week {microcycle.week_no}, a session holding {held} runs "
                    f"{minutes:.0f} min against the {ceiling:.0f} min its widest block "
                    f"({widest}) and one {_LENGTH_FILL_MINUTES}-minute fill chunk allow."
                )
                assert minutes >= floor, (
                    f"week {microcycle.week_no} ({microcycle.phase.value}), a session holding "
                    f"{held} runs {minutes:.0f} min against the {floor:.0f} min its protocols "
                    f"({window:.0f}) and its phase's share of its level's length "
                    f"({length:.0f}) owe."
                )


def _rounds_owed(
    spec: ExerciseSpec, prescription: PrescriptionSpec, microcycle: MicrocycleBlueprint
) -> int:
    """The set count this week owes: the authored one, plus ruling 46's rounds where they apply."""
    cell = (spec.aspect_key, spec.protocol_kind)
    lactic = cell == ("power", ProtocolKind.INTERVALS) and (
        prescription.work_seconds is None or prescription.work_seconds > _ALACTIC_WORK_SECONDS_MAX
    )
    if microcycle.phase in UNLOADING_PHASES or lactic or spec.key in OPEN_CLIMBING_KEYS:
        return prescription.sets
    step = min((microcycle.week_no - 1) % _WEEKS_PER_BLOCK + 1, _LOADING_WEEKS) - 1
    return prescription.sets + _ROUNDS_PER_LOADING_WEEK.get(cell, 0) * step


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
def test_a_fixed_volume_protocol_is_never_padded_and_an_expandable_one_is_capped(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str
) -> None:
    """Extra time may not become extra volume where low volume is the protocol. Compared against
    the AUTHORED prescription, so a grown block shows even when the session still fits.

    ⚠️ Ruling 27's length fill is the ONE dose the generator sizes itself, so it is measured
    against ruling 27's rule instead of against the library's: uniform timed sets, no rest
    inside or between them, none longer than one `LENGTH_FILL_MINUTES` chunk, exactly as many
    sets as that chunk size implies, and at most ONE such block in a session.
    ⚠️ Which blocks that arm reads is `OPEN_CLIMBING_KEYS` membership and NOT the shape —
    `_is_length_fill` records the measurement. The earlier claim that the shape "cannot become a
    hole for a padded authored block, because an authored block that grew would have to lose its
    rests and land on an exact chunk count" was wrong in its first clause: it is not a hole, it
    is a false RED, and ruling 41's rest-free `endurance` row walked into it."""
    del level
    plan = generate(_input(discipline, system, label, 5, 0b111_1111))
    chunk = _LENGTH_FILL_MINUTES * 60
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                fills = 0
                for block in session.blocks:
                    spec = _BY_KEY[block.exercise_key]
                    prescription = next(
                        p for p in spec.prescriptions if p.phase is microcycle.phase
                    )
                    authored = _rounds_owed(spec, prescription, microcycle)
                    expandable = (
                        block.aspect_key,
                        block.protocol_kind,
                    ) in _MAY_EXPAND and microcycle.phase not in {Phase.DELOAD, Phase.TAPER}
                    ceiling = authored * MAX_EXPANSION_FACTOR if expandable else authored
                    if len(block.sets) != authored and _is_length_fill(block, chunk):
                        fills += 1
                        seconds = sum(item.target_work_seconds or 0 for item in block.sets)
                        assert len(block.sets) == -(-seconds // chunk), (
                            f"{block.exercise_key} is ruling 27's fill at {seconds} s and spent "
                            f"{len(block.sets)} sets, not the {-(-seconds // chunk)} a "
                            f"{_LENGTH_FILL_MINUTES}-minute chunk implies."
                        )
                        continue
                    assert authored <= len(block.sets) <= ceiling, (
                        f"{block.exercise_key} ({block.protocol_kind.value}, "
                        f"{microcycle.phase.value} week {microcycle.week_no}) owes {authored} "
                        f"sets — its authored count plus the rounds its pair progresses by — and "
                        f"was prescribed {len(block.sets)}; expandable={expandable}."
                    )
                assert fills <= 1, (
                    f"week {microcycle.week_no} has a session carrying {fills} length-fill "
                    f"blocks; ruling 27 is ONE chunk and then it stops."
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
# ⚠️ THE CEILING IS GONE AND THIS IS FLOOR-ONLY BY DESIGN (Kilian, ruling 28, 2026-09-06) — read
# `_TARGET_BAND_IS_FLOOR_ONLY` below before adding one back. `CLIMBING_TARGET_PCT` still carries
# both edges because the GENERATOR aims between them; only the assertion is one-sided.
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
    """FLOOR-ONLY BY DESIGN, and the name says so. DELOAD weeks are out —
    `DELOAD_CLIMBING_FLOOR_PCT` governs them and the per-week test measures it.

    ⚠️ The absent ceiling is a DECISION, not an omission (ruling 28) — `_TARGET_BAND_IS_FLOOR_ONLY`
    holds the measurement it rests on, and `test__wall_pref_WITHHOLDS_THE_WALL_from_a_session_at_
    its_bands_top` is the guard that replaced it. The floor still does the work it was filed for:
    issue #84 opened at a 28% wall share."""
    low = _TARGET_BAND[level][0]
    every = _weekly_matrix(generate(_input(discipline, system, label, sessions, 0b111_1111, gap)))
    matrix = [row for row in every if row[1] is not Phase.DELOAD]
    wall = sum(row[2] for row in matrix)
    other = sum(row[3] for row in matrix)
    share = 100 * wall / (wall + other)
    assert share >= low, (
        f"a {level.value} training {sessions}x a week on a grade gap of {gap} "
        f"({len(matrix)} weeks) gets {share:.1f}% of prescribed minutes "
        f"on a wall, against a floor of {low}%: {wall // 60} min climbing vs "
        f"{other // 60} min of everything else. Below the floor the plan has stopped being a "
        f"climbing plan, which is the state issue #84 was filed in at 28%."
    )


# Ruling 28's replacement guard, and the three regimes are `_wall_pref`'s whole contract. A
# `_Draft` is built by hand rather than generated: the promise is about the candidate ORDER a
# supplementary slot is offered, which no finished plan records, and the week share that used to
# stand in for it stopped separating once the fill became the largest item in a session.
_WALL_PREF_BAND: tuple[int, int] = (50, 62)


# One LAPS block, so `session_window_across` gives the draft a 30-minute window floor and the
# `first` regime is reachable by making the block short. Kind and seconds only — `_wall_pref`
# reads `wall_seconds` off the draft, never off the block's equipment.
def _lapping_draft(work_seconds: int, wall_seconds: int) -> _Draft:
    """A mid-allocation session of one timed LAPS block, at a chosen wall/other split."""
    block = BlockBlueprint(
        order_index=1,
        exercise_key="arc_traversing",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        sets=(SetBlueprint(set_index=1, target_work_seconds=work_seconds),),
    )
    return _Draft(
        weekday=0,
        session_index=0,
        level_target_seconds=90 * 60,
        blocks=[block],
        wall_seconds=wall_seconds,
    )


def test__wall_pref_WITHHOLDS_THE_WALL_from_a_session_at_its_bands_top() -> None:
    """⚠️ GUARD, and the one that replaced the band's ceiling (ruling 28). Three regimes:

    `never` once a session's own wall share has reached the top of its band — more climbing is
    the one thing it does not need, and its supplementary slot is offered off-the-wall
    candidates ONLY. `first` while it is short of its protocols' window floor, so the seconds
    that close that floor are not spent on a pick the band's hard floor then rejects. `last`
    otherwise: prefer supplementary work without letting the preference become a filter.

    ⚠️ Read `_TARGET_BAND_IS_FLOOR_ONLY` for why this exists as its own test. The week-share
    band cannot catch a `_wall_pref` regression any more: 36 of 36 beginner rows stayed green
    under the sabotage. This does catch it — forcing `return "first"` takes both arms below red.
    """
    top = _WALL_PREF_BAND[1]
    at_the_top = _lapping_draft(work_seconds=2000, wall_seconds=1800)
    assert (
        _wall_pref(at_the_top, Phase.BASE, band=_WALL_PREF_BAND, wall_seconds=0, other_seconds=0)
        == "never"
    ), (
        f"a session holding {at_the_top.wall_seconds} s of wall time against "
        f"{at_the_top.other_seconds} s of everything else is already over the {top}% top of its "
        f"band, and `_wall_pref` still offers its supplementary slot on-the-wall candidates. "
        f"That slot is the only room the band reserves for the other work."
    )
    short = _lapping_draft(work_seconds=600, wall_seconds=300)
    assert (
        _wall_pref(short, Phase.BASE, band=_WALL_PREF_BAND, wall_seconds=0, other_seconds=0)
        == "first"
    ), (
        "a session 600 s into a 1800 s window floor must be offered the wall FIRST: the "
        "off-the-wall pick is the one the band's hard floor can reject, and a slot spent on a "
        "rejected pick left a 37-minute limit-bouldering session against a 40-minute floor."
    )
    roomy = _lapping_draft(work_seconds=2000, wall_seconds=1000)
    assert (
        _wall_pref(roomy, Phase.BASE, band=_WALL_PREF_BAND, wall_seconds=0, other_seconds=0)
        == "last"
    ), (
        f"a session past its window floor at a {roomy.wall_seconds * 100 // roomy.seconds}% wall "
        f"share is inside its band with room to spare, so supplementary work goes FIRST and the "
        f"wall stays a fallback. A preference that never yields is the filter that made six "
        f"exercises unreachable."
    )


# Honest 0 of 1632; with `_wall_pref` forced to "first", 14. The ADVANCED band is where this
# separates and the granularity is deliberate: its 50-62% band reserves the most room for the
# other work, so it is the level a lost preference is visible at. Beginner and intermediate
# sessions legitimately end all-climbing (226 and 44 of 1632), so a zero there would be false.
_ADVANCED_SESSIONS_WITH_NO_SUPPLEMENTARY_BLOCK = 0


@pytest.mark.parametrize("gap", [0, 3, 6])
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_an_ADVANCED_loading_session_always_keeps_room_for_work_off_the_wall(
    sessions: int, gap: int
) -> None:
    """⚠️ GUARD. The behavioural half of `_wall_pref`'s contract, and the half a unit test on a
    private function cannot reach: it fails if the preference is computed right and then ignored.
    An advanced session's band leaves 38-50% of it for work that is not climbing, so a session
    with NOTHING off the wall means a supplementary slot went to the wall that should not have.
    DELOAD weeks are out for the band test's reason."""
    lost = []
    for level, discipline, system, label in _CLIMBERS:
        if level is not Level.ADVANCED:
            continue
        plan = generate(_input(discipline, system, label, sessions, 0b111_1111, gap))
        for mesocycle in plan.mesocycles:
            for microcycle in mesocycle.microcycles:
                if microcycle.phase is Phase.DELOAD:
                    continue
                for session in microcycle.sessions:
                    if session.blocks and not any(not _on_wall(block) for block in session.blocks):
                        lost.append(
                            (label, microcycle.week_no, [b.exercise_key for b in session.blocks])
                        )
    assert len(lost) == _ADVANCED_SESSIONS_WITH_NO_SUPPLEMENTARY_BLOCK, (
        f"{len(lost)} advanced loading session(s) at {sessions}x a week on a gap of {gap} hold "
        f"nothing at all off the wall, against {_ADVANCED_SESSIONS_WITH_NO_SUPPLEMENTARY_BLOCK} "
        f"measured: {lost[:3]}. `generate.py::_wall_pref` is what reserves that room, and the "
        f"week-share band can no longer catch its loss — see _TARGET_BAND_IS_FLOOR_ONLY."
    )


# Ruling 29/30. Measured over 6 climbers x sessions 1-7 x gaps 0/3/6 (~9800 sessions): the fill
# placed 9837 open-climbing blocks, NEVER two in one session, and never walked off the phase's
# leading filler in a session that still carried hard energy-system work.
_SESSIONS_WITH_TWO_FILLS = 0
_OFF_LEAD_FILLS_ON_A_HARD_DAY = 0

# What each block is FOR, as ruling 30 states it, restated INDEPENDENTLY of
# `selection.py::open_climbing_fill` for `_MAY_EXPAND`'s reason — and this one is not a
# formality: reading `open_climbing_fill(phase)[0]` here left the arm below GREEN when the
# filler order was reversed against the phase's own emphasis, because the test's idea of
# "leading" reversed with it. The four phases that share a row share an intention: strength,
# power, performance and the taper are all about the hardest moves a climber can make.
_THE_BLOCKS_OWN_FILLER: Mapping[Phase, str] = {
    Phase.BASE: "open_climbing_easy_mileage",
    Phase.STRENGTH: "open_climbing_hard_moves",
    Phase.POWER: "open_climbing_hard_moves",
    Phase.POWER_ENDURANCE: "open_climbing_power_endurance",
    Phase.PERFORMANCE: "open_climbing_hard_moves",
    Phase.DELOAD: "open_climbing_for_fun",
    Phase.TAPER: "open_climbing_hard_moves",
}


@pytest.mark.parametrize("gap", [0, 3, 6])
@pytest.mark.parametrize("sessions", [1, 2, 3, 5, 7])
def test_the_LENGTH_FILL_is_ONE_block_carrying_THE_BLOCKS_OWN_INTENTION(
    sessions: int, gap: int
) -> None:
    """⚠️ GUARD, rulings 29 and 30. Ruling 27's fill is ONE chunk of open climbing, and ruling 30
    makes WHICH open-climbing row a real decision rather than a rotation.

    Arm 1 is ruling 27's "and that is it": one chunk per session, never a loop converging on the
    length. Arm 2 is ruling 30's second invariant, and it is the whole reason the family has four
    rows: the fill is credited to the quality the block is NAMED after, so filling a block cannot
    make a rival out-train it. It walks off that row on exactly one condition — a day ruling 9's
    ~3-hard-days ceiling has already made easy, where crediting the block's own hard quality
    would put the injury ceiling back where round 1 found it. So an off-lead fill in a session
    that DOES carry hard energy-system work means the attribution has stopped following the
    block, and the measured count is zero.
    """
    two_fills, off_lead = [], []
    for _level, discipline, system, label in _CLIMBERS:
        plan = generate(_input(discipline, system, label, sessions, 0b111_1111, gap))
        for mesocycle in plan.mesocycles:
            for microcycle in mesocycle.microcycles:
                lead = _THE_BLOCKS_OWN_FILLER[microcycle.phase]
                for session in microcycle.sessions:
                    fills = [b for b in session.blocks if b.exercise_key in OPEN_CLIMBING_KEYS]
                    if len(fills) > 1:
                        two_fills.append(
                            (label, microcycle.week_no, [b.exercise_key for b in fills])
                        )
                    carries_hard = any(
                        block.aspect_key in ENERGY_SYSTEM_ASPECTS
                        for block in session.blocks
                        if block.exercise_key not in OPEN_CLIMBING_KEYS
                    )
                    off_lead += [
                        (label, microcycle.week_no, microcycle.phase.value, b.exercise_key, lead)
                        for b in fills
                        if b.exercise_key != lead and carries_hard
                    ]
    assert len(two_fills) == _SESSIONS_WITH_TWO_FILLS, (
        f"{len(two_fills)} session(s) at {sessions}x a week on a gap of {gap} hold more than one "
        f"open-climbing block: {two_fills[:3]}. Ruling 27 is ONE chunk of "
        f"max(gap, 30 min) and then stop, not a loop that converges on the length."
    )
    assert len(off_lead) == _OFF_LEAD_FILLS_ON_A_HARD_DAY, (
        f"{len(off_lead)} fill(s) at {sessions}x a week on a gap of {gap} were credited to a "
        f"quality the block is not named after, in a session that was already carrying hard "
        f"energy-system work: {off_lead[:3]}. The fallback exists for the days ruling 9 has made "
        f"easy and for nothing else — off a hard day it is ruling 30's out-training defect back."
    )


# Ruling 23's cause, as the number it repaired: before the boulder-reachable row, all four
# `endurance` rows prescribable in POWER_ENDURANCE were `discipline=sport`, so 12 of 12 boulder
# profiles took ZERO aerobic minutes in that block at every session count. Now 12 of 12 take some.
# ⚠️ PER PROFILE and not per week, deliberately: 12 boulder POWER_ENDURANCE weeks still hold no
# aerobic block at all, and closing THAT is ruling 24's one-block-per-week floor, which is not
# implemented. This guard is ruling 23's claim — reachability — and says so rather than implying
# the floor exists.
_AEROBIC_RPE_CEILING_FOR_A_BOULDERER = 6


@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_a_BOULDERER_GETS_AEROBIC_WORK_in_the_power_endurance_block(sessions: int) -> None:
    """⚠️ GUARD, ruling 23. A boulder-discipline climber was filtered out of every aerobic row
    this block prescribes, so `PHASE_GUIDE[POWER_ENDURANCE]`'s "enough to let the next hard
    session happen two days later" was false for half the profiles for reasons no emphasis index
    could reach. The dose arm is the other half of the ruling: sustained and moderate, never to
    failure. It reads only the rows a BOULDERER draws; the same ceiling over the whole aspect is
    `test_no_ENDURANCE_row_is_DOSED_OVER_THE_AEROBIC_CAPACITY_RPE_CEILING`."""
    for level, discipline, system, label in _CLIMBERS:
        if discipline is not Discipline.BOULDER:
            continue
        plan = generate(_input(discipline, system, label, sessions, 0b111_1111))
        blocks = [
            block
            for mesocycle in plan.mesocycles
            for microcycle in mesocycle.microcycles
            if microcycle.phase is Phase.POWER_ENDURANCE
            for session in microcycle.sessions
            for block in session.blocks
            if block.aspect_key == "endurance"
        ]
        assert blocks, (
            f"a {level.value} {label} boulderer at {sessions}x a week gets NO aerobic block in "
            f"the whole power-endurance block. That was 12 of 12 boulder profiles before ruling "
            f"23 authored a boulder-reachable row, and it is not an emphasis-order problem: "
            f"every other aerobic row this phase prescribes requires rope equipment."
        )
        for block in blocks:
            rpes = [item.target_rpe for item in block.sets]
            assert all(
                rpe is not None and rpe <= _AEROBIC_RPE_CEILING_FOR_A_BOULDERER for rpe in rpes
            ), (
                f"{block.exercise_key} gives a {label} boulderer aerobic work at RPE {rpes} in "
                f"the power-endurance block, over the {_AEROBIC_RPE_CEILING_FOR_A_BOULDERER} "
                f"ruling 23 dosed it at. §7 wants a sustained light pump and never a failure, "
                f"and ruling 39 brought the four rows that breached that down to the same 6."
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


@cache
def _gap_plan(
    discipline: Discipline, system: GradeSystemKey, label: str, sessions: int, gap: int
) -> PlanBlueprint:
    """One plan at a chosen GRADE GAP, cached. Plan LENGTH is a dimension of the two habituation
    guards below because #118's defect had a half that only appeared at the short end."""
    return generate(_input(discipline, system, label, sessions, 0b111_1111, gap=gap))


def _base_finger_blocks(plan: PlanBlueprint) -> tuple[BlockBlueprint, ...]:
    """Every finger-strength block the plan's BASE weeks carry, in order."""
    return tuple(
        block
        for mesocycle in plan.mesocycles
        for microcycle in mesocycle.microcycles
        if microcycle.phase is Phase.BASE
        for session in microcycle.sessions
        for block in session.blocks
        if block.aspect_key == "finger_strength"
    )


@pytest.mark.parametrize("gap", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
@pytest.mark.parametrize(("level", "discipline", "system", "label"), _BEGINNERS)
def test_a_BEGINNERS_BASE_WEEKS_HABITUATE_the_fingers_and_never_load_them(
    level: Level,
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    gap: int,
) -> None:
    """Ruling 35, and it reads PER LEVEL because the claim is about one band: the seven-profile
    union in `test_planner_library_reach.py` was green while this shipped broken.

    The zero above is not what decides this — a beginner's finger work arrives through the
    ordinary supplementary slot, and what it draws there is CONTENT, which is the thing both
    sources scale by level. Measured before the fix over 60 beginner plans: **115 of 115 BASE
    finger blocks were max hangs or repeaters and the row authored for BASE landed in none.**
    """
    del level
    blocks = _base_finger_blocks(_gap_plan(discipline, system, label, sessions, gap))
    loaded = sorted({block.exercise_key for block in blocks} - {_HABITUATION_ROW})
    assert not [b for b in blocks if b.protocol_kind not in _HABITUATION_PROTOCOLS], (
        f"a {label} beginner at {sessions}x, gap {gap} is prescribed {loaded} in BASE. Weeks 1-4 "
        f"are habituation in both sources, and a max hang or a repeater is the load-hard end."
    )
    registered = _BASE_HABITUATION_GAPS.get((_profile(Level.BEGINNER, discipline, label), sessions))
    drawn = {block.exercise_key for block in blocks}
    if registered is None:
        assert _HABITUATION_ROW in drawn, (
            f"a {label} beginner at {sessions}x, gap {gap} draws {sorted(drawn)} in BASE and not "
            f"{_HABITUATION_ROW}, the habituation protocol the library authors for that block. "
            f"If that is a decision it owes a row in _BASE_HABITUATION_GAPS with its mechanism."
        )
    else:
        assert _HABITUATION_ROW not in drawn, (
            f"({_profile(Level.BEGINNER, discipline, label)}, {sessions}) is registered in "
            f"_BASE_HABITUATION_GAPS as {registered!r} and now draws {_HABITUATION_ROW} at gap "
            f"{gap}. Delete the row: the register is a measurement, not documentation."
        )
    later = [
        block.exercise_key
        for mesocycle in _gap_plan(discipline, system, label, sessions, gap).mesocycles
        for microcycle in mesocycle.microcycles
        if microcycle.phase is not Phase.BASE
        for session in microcycle.sessions
        for block in session.blocks
        if block.aspect_key == "finger_strength" and block.protocol_kind in _FINGER_PROTOCOLS
    ]
    assert later, (
        f"a {label} beginner at {sessions}x, gap {gap} is never prescribed a max hang or a "
        f"repeater ANYWHERE. Habituation is scoped to BASE — weeks 1-4 — and loading is what it "
        f"is habituation FOR, so a plan that never loads has turned the rule into a ban."
    )


@pytest.mark.parametrize("gap", [1, 3, 5])
@pytest.mark.parametrize("sessions", [5, 7])
@pytest.mark.parametrize(("level", "discipline", "system", "label"), _HARDER_BANDS)
def test_the_HABITUATION_RULE_IS_THE_BEGINNER_BANDS_ALONE(
    level: Level,
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    gap: int,
) -> None:
    """The other end of the level key, and the arm a pooled read cannot make: an intermediate or
    an advanced climber still LOADS the fingers in BASE. Without it, deleting every max hang from
    the block would read green.

    ⚠️ Sampled at 5 and 7 sessions on purpose. At 2 sessions for every band, and at 3 for the
    advanced one, a BASE week reaches no finger slot at all — 30 of 80 plans — which is the same
    slot scarcity `_BASE_HABITUATION_GAPS` records and says nothing about content.
    """
    del level
    blocks = _base_finger_blocks(_gap_plan(discipline, system, label, sessions, gap))
    assert [block for block in blocks if block.protocol_kind in _FINGER_PROTOCOLS], (
        f"a {label} {sessions}x plan holds {sorted({b.exercise_key for b in blocks})} as its "
        f"whole BASE finger content at gap {gap}. Habituation before loading is the BEGINNER's "
        f"rule; a band past it trains the maximum the aspect is a predictor of."
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


@cache
def _aspect_minutes(
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    weakness: str | None,
) -> Mapping[str, int]:
    """Prescribed seconds per aspect over a WHOLE plan. ⚠️ `weakness` is part of the cache key
    because leaving it out measures the same plan twice and calls the difference zero."""
    plan = generate(_input(discipline, system, label, sessions, 0b111_1111, weakness=weakness))
    seconds: Counter[str] = Counter()
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                for block in session.blocks:
                    seconds[block.aspect_key] += _block_seconds(block)
    return seconds


@cache
def _prescribed_aspect_seconds(
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    weakness: str | None,
) -> Mapping[str, int]:
    """`_aspect_minutes` with ruling 29's elastic filler subtracted, so what a declaration BUYS
    reads apart from what the length fill gives back. Keys from the library, not spelled out."""
    plan = generate(_input(discipline, system, label, sessions, 0b111_1111, weakness=weakness))
    seconds: Counter[str] = Counter()
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                for block in session.blocks:
                    if block.exercise_key not in OPEN_CLIMBING_KEYS:
                        seconds[block.aspect_key] += _block_seconds(block)
    return seconds


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
    `_UNLOAD_FLOOR_PCT` of its own block's loading mean. There is no ceiling, by ruling."""
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


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_at_most_THREE_DAYS_A_WEEK_carry_hard_energy_system_work(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD. Ruling 9, per week and per climber: Barrows gives a 5-day climber at most ~3
    days of hard energy-system work. An overtraining guard and not a tuning knob — a 5-day
    climber got 4 or 5 hard days in 80 of 120 measured weeks, and every strength and power
    loading week of the beginner and intermediate plans was 5 of 5. The TAPER is exempt for
    `_HARD_ENERGY_EXEMPT_PHASES`' sourced reason and the anti-vacuity arm below is why that
    exemption cannot hide a generator that stopped prescribing hard work at all."""
    del level
    rows = _weekly_aspect_sessions(_plan(discipline, system, label, sessions, 0b111_1111))
    assert rows, f"a {label} climber at {sessions}x a week produced no weeks at all."
    for week_no, phase, _carried, hard in rows:
        if phase in _HARD_ENERGY_EXEMPT_PHASES:
            continue
        assert hard <= _HARD_ENERGY_DAYS_PER_WEEK, (
            f"a {label} climber at {sessions}x a week gets {hard} days of hard energy-system "
            f"work in week {week_no} ({phase.value}), against the "
            f"{_HARD_ENERGY_DAYS_PER_WEEK} Barrows §3.2/§4.2 allows. Hard means An Cap, An Pow "
            f"or Aero Pow — {sorted(_HARD_ENERGY_ASPECTS)} — and a day counts by CONTAINING one, "
            f"not by opening with one."
        )
    loaded = [hard for _w, phase, _c, hard in rows if phase not in _HARD_ENERGY_EXEMPT_PHASES]
    assert max(loaded) >= min(sessions, _HARD_ENERGY_DAYS_PER_WEEK), (
        f"the hardest non-taper week a {label} climber gets at {sessions}x a week carries "
        f"{max(loaded)} hard energy days, so the ceiling above is passing on a plan that has "
        f"stopped prescribing hard work rather than on one that respects a ceiling."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", [2, 3, 5, 7])
def test_ANAEROBIC_CAPACITY_sessions_stay_under_the_ceiling_FOR_THAT_PHASE(
    level: Level, discipline: Discipline, system: GradeSystemKey, label: str, sessions: int
) -> None:
    """⚠️ GUARD. Ruling 18, per week and per climber: the An Cap ceiling is per PHASE, off §4.2's
    worked example. Measured before: 136 of 480 weeks carried 3 or more An Cap sessions,
    distribution 3x58 4x44 5x25 6x8 7x1 — seven a week against a ceiling of two — and 206 of
    480 weeks breached their own phase's number. `performance` and `taper` are 0 because the
    library declines those cells, which this asserts rather than re-implements."""
    del level
    rows = _weekly_aspect_sessions(_plan(discipline, system, label, sessions, 0b111_1111))
    assert rows, f"a {label} climber at {sessions}x a week produced no weeks at all."
    for week_no, phase, carried, _hard in rows:
        ceiling = _ANAEROBIC_SESSIONS_PER_WEEK[phase]
        assert carried[_ANAEROBIC_ASPECT] <= ceiling, (
            f"a {label} climber at {sessions}x a week gets {carried[_ANAEROBIC_ASPECT]} "
            f"anaerobic-capacity sessions in week {week_no} ({phase.value}), against the "
            f"{ceiling} §4.2 gives that stage. An Cap is the quality Barrows caps hardest: it "
            f"takes months to build and its sessions are the ones with real injury risk."
        )
    reached = {phase for _w, phase, _c, _h in rows}
    assert reached & set(_ANAEROBIC_SESSIONS_PER_WEEK) == reached, (
        f"{sorted(phase.value for phase in reached - set(_ANAEROBIC_SESSIONS_PER_WEEK))} have "
        f"no row in the ceiling table, so those weeks are unchecked rather than passing."
    )


# The session counts the rise arm sweeps, named rather than repeated so `_WEAKNESS_INVERSIONS`
# can be checked against the parametrisation it claims to except.
_WEAKNESS_SESSION_COUNTS: tuple[int, ...] = (2, 3, 5, 7)

# Ruling 29's filler runs to 84.6% of a profile's tagged total, so the PRESCRIBED half is what a
# declaration answers for: 48 of 48 gain 2220-18014 s of it, and this floor is 90% of that 2220.
_WEAKNESS_PRESCRIBED_GAIN_FLOOR_SECONDS = 1998


@dataclass(frozen=True, slots=True)
class _WeaknessInversion:
    """One (climber, sessions, weakness) whose DECLARATION lowers its own aspect's total, on
    `_AcceptedInversion`'s idiom: DATA, with a leash, asserted in both directions below."""

    label: str
    sessions: int
    weakness: str
    max_loss_seconds: int
    reason: str


_WEAKNESS_INVERSIONS: tuple[_WeaknessInversion, ...] = (
    _WeaknessInversion(
        label="7C",
        sessions=2,
        weakness="power_endurance",
        max_loss_seconds=1262,
        reason=(
            "PERVERSE, not a shortfall, and the only one of the 48 rows that runs backwards: "
            "declaring power endurance LOWERS it, 38554 -> 37292 s (642 -> 621 min, -3.3%). No "
            "reader may take that number as correct-by-design. The declaration is honoured "
            "everywhere else in the plan — base +1680 s, the deloads +960 s — and the whole loss "
            "is inside the power-endurance block itself, -3902 s. MECHANISM, finding F28: "
            "`_intended_aspect`'s slot-1 rotation is keyed on the PLAN-ABSOLUTE week number "
            "(`turn = week_no - 1 + session_index`), so WHERE a block sits decides which turns "
            "its sessions land on. Ruling 51 puts this block at weeks 9-11, whose six sessions "
            "take only four distinct turns at two days a week (8, 9, 9, 10, 10, 11) and hit "
            "ruling 21's yield turn 9 TWICE; on those two, slot 1 goes to `finger_strength` and "
            "the elastic `open_climbing_power_endurance` fill contracts 1302 s and 1600 s to "
            "make room. That fill is 32630 of 38554 s = 84.6% of this profile's tagged total, "
            "so its -4682 s beats the +3420 s of prescribed circuits the declaration buys. NOT "
            "the length and NOT the dropped POWER block: measured control, holding 16 weeks and "
            "four blocks and swapping only the middle two so this block sits at weeks 5-7, the "
            "same row reads 31851 -> 37507 s, +5656 s GREEN. Restoring the POSITION fixes it, "
            "restoring the length does not. The fix — making the rotation's turn BLOCK-RELATIVE "
            "— is UNPRICED and declined inside item 3b: it changes what every user is "
            "prescribed and needs its own 24-profile sweep."
        ),
    ),
)


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _CLIMBERS)
@pytest.mark.parametrize("sessions", _WEAKNESS_SESSION_COUNTS)
@pytest.mark.parametrize("weakness", _WEAKNESSES)
def test_a_DECLARED_WEAKNESS_RAISES_its_own_aspects_minutes(
    level: Level,
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    weakness: str,
) -> None:
    """⚠️ GUARD, the first half of the lever nothing measured: four files pass a weakness and
    all assert strings, widths and determinism rather than its effect. TWO halves now. The
    PRESCRIBED minutes of the declared aspect rise on 48 of 48 rows by 2220-18014 s; the TOTAL
    rises on 47 of 48 at 1.064x-1.282x, because ruling 29's filler runs to 84.6% of a tagged
    total and can give back more than a declaration bought — F28, `_WEAKNESS_INVERSIONS`.

    A one-session week is exempt, which is why this starts at two: see
    `_WEAKNESS_NEEDS_A_SUPPLEMENTARY_SLOT`."""
    del level
    assert sessions >= _WEAKNESS_NEEDS_A_SUPPLEMENTARY_SLOT
    baseline = _aspect_minutes(discipline, system, label, sessions, None)
    declared = _aspect_minutes(discipline, system, label, sessions, weakness)
    assert baseline[weakness], (
        f"a {label} climber at {sessions}x a week gets no {weakness} at all with nothing "
        f"declared, so the comparison below would pass on any positive number."
    )
    base_prescribed = _prescribed_aspect_seconds(discipline, system, label, sessions, None)
    declared_prescribed = _prescribed_aspect_seconds(discipline, system, label, sessions, weakness)
    prescribed_gain = declared_prescribed[weakness] - base_prescribed[weakness]
    assert prescribed_gain >= _WEAKNESS_PRESCRIBED_GAIN_FLOOR_SECONDS, (
        f"a {label} climber at {sessions}x a week who declares {weakness} their weakness gets "
        f"{prescribed_gain} s more of it PRESCRIBED, against a floor of "
        f"{_WEAKNESS_PRESCRIBED_GAIN_FLOOR_SECONDS} s. This is the half no length fill can pay "
        f"back, so it is what the lever answers for: a declaration that buys no prescription is "
        f"a form control wired to nothing, whatever the totals then do."
    )
    accepted = {(row.label, row.sessions, row.weakness): row for row in _WEAKNESS_INVERSIONS}
    row = accepted.get((label, sessions, weakness))
    if row is None:
        assert declared[weakness] > baseline[weakness], (
            f"a {label} climber at {sessions}x a week who declares {weakness} their weakness "
            f"gets {declared[weakness] // 60} min of it against {baseline[weakness] // 60} min "
            f"with nothing declared. Both sources build the whole block around the declared "
            f"weakness. If that is a measured consequence rather than a defect it owes a row in "
            f"_WEAKNESS_INVERSIONS carrying the DIRECTION, the mechanism and the cost."
        )
        return
    loss = baseline[weakness] - declared[weakness]
    assert loss <= row.max_loss_seconds, (
        f"{label} at {sessions}x declaring {weakness} is an ACCEPTED INVERSION, but it now "
        f"loses {loss} s against the {row.max_loss_seconds} s it was accepted at, so the "
        f"exception has grown into a different one. The row reads: {row.reason}"
    )


def test_no_declared_weakness_inversion_has_quietly_become_true() -> None:
    """⚠️ GUARD, reverse arm. A row that has stopped inverting, or that never named a swept
    climber, is cover for the arm above rather than a measurement of the generator."""
    swept = {label: (discipline, system) for _level, discipline, system, label in _CLIMBERS}
    unchecked = sorted(
        f"{row.label} at {row.sessions}x declaring {row.weakness}"
        for row in _WEAKNESS_INVERSIONS
        if row.label not in swept
        or row.sessions not in _WEAKNESS_SESSION_COUNTS
        or row.weakness not in _WEAKNESSES
    )
    assert not unchecked, (
        f"{unchecked} are excepted in _WEAKNESS_INVERSIONS but match no parametrisation of the "
        f"rise arm, so they are unvisited rather than accepted — which is exactly how an "
        f"accepted exception and an unsampled gap look identical in a green suite."
    )
    stale: list[str] = []
    for row in _WEAKNESS_INVERSIONS:
        discipline, system = swept[row.label]
        baseline = _aspect_minutes(discipline, system, row.label, row.sessions, None)
        declared = _aspect_minutes(discipline, system, row.label, row.sessions, row.weakness)
        if declared[row.weakness] > baseline[row.weakness]:
            stale.append(f"{row.label} at {row.sessions}x declaring {row.weakness}")
    assert not stale, (
        f"{stale} are excepted in _WEAKNESS_INVERSIONS and now RAISE the declared aspect like "
        f"every other profile. Delete those rows — the register is a measurement of the "
        f"generator, not documentation of it."
    )


@pytest.mark.parametrize(("level", "discipline", "system", "label"), _BEGINNERS)
@pytest.mark.parametrize("sessions", [1, 2, 3, 5, 7])
@pytest.mark.parametrize("weakness", _WEAKNESSES)
def test_a_DECLARED_WEAKNESS_cannot_push_a_BASE_BLOCKS_TAIL_past_its_ceiling(
    level: Level,
    discipline: Discipline,
    system: GradeSystemKey,
    label: str,
    sessions: int,
    weakness: str,
) -> None:
    """⚠️ GUARD, the second half, and the one that was RED when it was written. The weakness is
    the largest lever in the generator and the base block is where it can do most damage: base
    MAINTAINS power and aerobic power only, and slot 1 puts the declared one in every session.

    Measured before the weekly frequency ceilings landed: a declared `power_endurance` weakness
    took 22.0% and 22.3% of the two beginners' base minutes at 7 sessions a week against this
    ceiling of 20, and 21.6-23.2% across all six climbers. With the ceilings the same sweep
    peaks at 19.2% — `power` at 14.5%, nothing declared at 10.7% — so ruling 9's ceiling is
    what closed this breach, which is why the two land in one PR.
    """
    del level
    every, _wall = _base_aspect_seconds(
        generate(_input(discipline, system, label, sessions, 0b111_1111, weakness=weakness))
    )
    total = sum(every.values())
    assert total, "no base weeks in the plan; the parametrisation is wrong."
    tail = sum(every.get(key, 0) for key in _BASE_WALL_EMPHASIS[-2:])
    assert tail * 100 <= _BASE_TAIL_CEILING_PCT * total, (
        f"a {label} beginner training {sessions}x a week who declares {weakness} their weakness "
        f"spends {100 * tail / total:.1f}% of a base block's prescribed minutes on "
        f"{' and '.join(_BASE_WALL_EMPHASIS[-2:])}, against a ceiling of "
        f"{_BASE_TAIL_CEILING_PCT}%: {tail // 60} min of {total // 60}. A weakness is an "
        f"organising principle, but base still only MAINTAINS both of these."
    )


# Ruling 33's An Cap → Aero Cap co-occurrence claim, which ruling 41's `easy_climbing_flush` is
# what made assertable at all: before that row, `endurance` was absent from `wall_led_aspects()`
# in both of these phases, every `endurance` row they prescribe was OFF the wall, and a 2-session
# week's whole off-wall allowance (~206-1652 s) could not afford the cheapest of them at 1200 s.
#
# ⚠️ SCOPE IS `STRENGTH` AND `POWER` AND NOTHING ELSE. `POWER_ENDURANCE` is out by ruling 24,
# which revoked that block's aerobic floor and left only the floor revoked; CLAUDE.md forbids
# re-filing the weeks that hold none, so a guard whose scope reached them would be a re-file of a
# declined finding however it was worded. BASE and DELOAD are out because they measured 0%.
#
# Restated as literals and not imported, on `_THE_BLOCKS_OWN_FILLER`'s reason.
_ANAEROBIC_ASPECT = "anaerobic_capacity"
_AEROBIC_ASPECT = "endurance"
# ⚠️ `POWER` LEFT this tuple with its block (ruling 51). It is not an exemption: no week of
# any plan carries the phase, so an arm scoped to it reads nothing and passes on emptiness.
_CO_OCCURRENCE_PHASES = (Phase.STRENGTH,)
_CO_OCCURRENCE_WEAKNESSES: tuple[str | None, ...] = (None, "power", "power_endurance")

# From this many sessions a week up, EVERY such week carries aerobic work. Below it the gap is
# real and registered: the residual is slot scarcity in a week with two or three climbing days,
# and 100% of it was a 2-session week before ruling 41's row existed.
_AEROBIC_ALWAYS_FROM_SESSIONS = 5

# The residual, per (sessions, phase), measured over 6 climbers x 3 weakness values with ruling
# 41's row in the tree. Before the row the same sweep read 132/216 STRENGTH (61.1%) and 165/213
# POWER (77.5%) weeks with no aerobic work, at every session count including 7.
# ⚠️ Asserted EXACTLY and in both directions: a number rising is the gap coming back, and a
# number falling is a claim this register has stopped making. Both are decisions.

# ⚠️ The four `POWER` rows were RETIRED with the block, not re-based; the STRENGTH numbers are
# unchanged, because ruling 51 left that block on weeks 5-7 where it already was.
_CO_OCCURRENCE_GAP_BELOW_THAT: Mapping[tuple[int, Phase], int] = {
    (1, Phase.STRENGTH): 0,
    (2, Phase.STRENGTH): 6,
    (3, Phase.STRENGTH): 0,
    (4, Phase.STRENGTH): 0,
}


def _weeks_with_anaerobic_but_no_aerobic(sessions: int) -> Mapping[Phase, list[str]]:
    """Per PHASE, the STRENGTH/POWER weeks that train An Cap and no aerobic capacity.

    ⚠️ PER WEEK, which is the granularity of the claim. Ruling 24's amendment measured the cost
    of getting this wrong: the same claim read per PROFILE was true 18 of 18 and green while 12
    of those profiles' 72 weeks held none. A pooled read cannot see a per-week claim fail.
    """
    found: dict[Phase, list[str]] = {phase: [] for phase in _CO_OCCURRENCE_PHASES}
    for level, discipline, system, label in _CLIMBERS:
        for weakness in _CO_OCCURRENCE_WEAKNESSES:
            plan = generate(
                _input(discipline, system, label, sessions, 0b111_1111, weakness=weakness)
            )
            for mesocycle in plan.mesocycles:
                if mesocycle.phase not in _CO_OCCURRENCE_PHASES:
                    continue
                for microcycle in mesocycle.microcycles:
                    aspects = {
                        block.aspect_key
                        for session in microcycle.sessions
                        for block in session.blocks
                    }
                    if _ANAEROBIC_ASPECT in aspects and _AEROBIC_ASPECT not in aspects:
                        found[mesocycle.phase].append(
                            f"{level.value} {discipline.value} {label}, weakness={weakness}, "
                            f"week {microcycle.week_no}"
                        )
    return found


@pytest.mark.parametrize("sessions", [5, 6, 7])
def test_an_ANAEROBIC_CAPACITY_WEEK_ALSO_TRAINS_AEROBIC_CAPACITY_from_five_sessions(
    sessions: int,
) -> None:
    """⚠️ GUARD, rulings 33 and 41. §3.4 tags Aero Cap and ARC onto the end of anything, and an
    anaerobic-capacity week without any aerobic base under it is the week that buys the least
    from the hard work in it. Scoped to `STRENGTH` and `POWER` — see the register above for why
    `POWER_ENDURANCE` must not be inside this guard, and why BASE and DELOAD need not be.

    The row that makes this green is on the WALL, which is the whole of ruling 41: an off-wall
    aerobic row cannot reach a low-session week at all, and the alternative that forced one into
    the supplementary pass paid for it with 56 `general_strength` blocks, against a strength
    share F14 already declares as short.
    """
    found = _weeks_with_anaerobic_but_no_aerobic(sessions)
    for phase in _CO_OCCURRENCE_PHASES:
        assert not found[phase], (
            f"{len(found[phase])} {phase.value} week(s) at {sessions}x a week train anaerobic "
            f"capacity with no aerobic capacity anywhere in the week: {found[phase][:3]}. From "
            f"{_AEROBIC_ALWAYS_FROM_SESSIONS} sessions up there are enough wall turns for both, "
            f"and ruling 41's on-wall row is what puts the aerobic one within reach."
        )


@pytest.mark.parametrize("sessions", [1, 2, 3, 4])
def test_the_AEROBIC_CO_OCCURRENCE_GAP_BELOW_FIVE_SESSIONS_IS_EXACTLY_THE_REGISTER(
    sessions: int,
) -> None:
    """⚠️ GUARD, the other end. Below `_AEROBIC_ALWAYS_FROM_SESSIONS` the gap is real, and this
    arm is what stops the claim above being read as one the whole plan makes. Exact, both ways:
    the register is the honest limit of ruling 41's row and not a tolerance."""
    found = _weeks_with_anaerobic_but_no_aerobic(sessions)
    for phase in _CO_OCCURRENCE_PHASES:
        expected = _CO_OCCURRENCE_GAP_BELOW_THAT[(sessions, phase)]
        assert len(found[phase]) == expected, (
            f"{len(found[phase])} {phase.value} week(s) at {sessions}x a week train anaerobic "
            f"capacity and no aerobic capacity, against the {expected} registered: "
            f"{found[phase][:3]}. More is the gap coming back; fewer is this register making a "
            f"claim it no longer has to. Re-measure and move the number deliberately."
        )
