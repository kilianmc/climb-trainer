"""How a dose moves week to week inside a block — issue #117, ruling 46.

Keyed on the `(aspect_key, protocol_kind)` PAIR, never on `aspect_key` alone: `power` holds
lactic anaerobic power AND alactic max-effort work, which the sources progress in OPPOSITE
directions, so one rule read off the aspect condemns whichever of the two it was not written for.
`power` x `intervals` is the only cell holding both, so that cell alone reads `work_seconds`.
⚠️ Not a per-phase volume multiplier: a pair with no sourced rule does not progress at all, which
is what keeps `periodisation.py`'s "no per-phase volume multiplier anywhere in this package" true.
"""

import enum
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Final

from server.domain.exercises import OPEN_CLIMBING_KEYS, PrescriptionSpec
from server.domain.planner.climbing import UNLOADING_PHASES
from server.domain.planner.periodisation import LOADING_WEEKS, WEEKS_PER_BLOCK
from server.domain.vocabulary import Phase, ProtocolKind


class WeeklyProgression(enum.Enum):
    """One of the sources' three week-to-week rules, or none for a cell they do not dose."""

    NONE = "none"
    LONGER_WORK = "longer_work"
    SHORTER_REST = "shorter_rest"
    MORE_ROUNDS = "more_rounds"


# ⚠️ DECLARED: neither source gives a FIGURE. Dylan says "progress the weight or time every
# week" and Barrows names a direction per attribute; both are silent on how much.
#
# So 10% a week and one extra round a week are the app's own, chosen small enough that three
# loading weeks move a dose by 20% or two rounds rather than by a training block's worth.
WEEKLY_STEP_PCT: Final = 10
ROUNDS_PER_WEEK: Final = 1

# A zero rest is not a dose, so shortening floors at one second — the app's OWN floor, not a
# column CHECK: `prescription_template` constrains `sets`, `intensity_pct` and `target_rpe` only.
MIN_REST_SECONDS: Final = 1

# The one cell two rows share, and the work duration that tells them apart.
SPLIT_CELL: Final[tuple[str, ProtocolKind]] = ("power", ProtocolKind.INTERVALS)

# `explosive_move_intervals` is 6 s of work and `boulders_on_the_two_minute` is 30 s; 15 s sits
# above every alactic burst in the library and below every lactic interval in it.
ALACTIC_WORK_SECONDS_MAX: Final = 15

# ⚠️ Ruling 46's table, as the pair-keyed register the rule reads. A pair that is ABSENT does not
# progress, and that silence is the invariant: absence is how "not a volume multiplier" is written.
PROGRESSION_RULES: Final[Mapping[tuple[str, ProtocolKind], WeeklyProgression]] = MappingProxyType(
    {
        # An Cap progresses by harder or LONGER work and never by less rest (Barrows §5.2), so
        # the rest scales WITH the work: §7's 2-4x band then holds by construction, not by luck.
        ("anaerobic_capacity", ProtocolKind.INTERVALS): WeeklyProgression.LONGER_WORK,
        ("anaerobic_capacity", ProtocolKind.CIRCUIT): WeeklyProgression.LONGER_WORK,
        # Lactic An Pow progresses by SHORTER rest. `short_rest_boulder_sets` is the shape §7
        # names, and §5.4's broken/redpoint circuit is the same quality dosed by sections.
        ("power", ProtocolKind.CIRCUIT): WeeklyProgression.SHORTER_REST,
        # Alactic max-effort work progresses by load or ROUNDS. Longer work and shorter rest are
        # both named counterproductive, and these fourteen rows carry no `work_seconds` to lengthen.
        ("power", ProtocolKind.STRAIGHT_SETS): WeeklyProgression.MORE_ROUNDS,
        ("power", ProtocolKind.LIMIT_BOULDER): WeeklyProgression.MORE_ROUNDS,
    }
)


def loading_week_of(week_no: int) -> int:
    """This plan week's 1-based ordinal inside its own block: 1-3 loading, then the unload."""
    return (week_no - 1) % WEEKS_PER_BLOCK + 1


def rule_for(
    aspect_key: str, protocol_kind: ProtocolKind, work_seconds: int | None
) -> WeeklyProgression:
    """Ruling 46's key: the pair, and `work_seconds` in the one cell that holds both rules."""
    if (aspect_key, protocol_kind) == SPLIT_CELL:
        if work_seconds is not None and work_seconds <= ALACTIC_WORK_SECONDS_MAX:
            return WeeklyProgression.MORE_ROUNDS
        return WeeklyProgression.SHORTER_REST
    return PROGRESSION_RULES.get((aspect_key, protocol_kind), WeeklyProgression.NONE)


def _longer(seconds: int | None, step: int) -> int | None:
    """One field, `WEEKLY_STEP_PCT` per loading week longer. `None` stays `None`."""
    if seconds is None:
        return None
    return seconds + seconds * WEEKLY_STEP_PCT * step // 100


def _shorter(seconds: int, step: int) -> int:
    """One rest field, `WEEKLY_STEP_PCT` per loading week shorter, floored at the column's CHECK."""
    return max(seconds - seconds * WEEKLY_STEP_PCT * step // 100, MIN_REST_SECONDS)


def _shorten_operative_rest(prescription: PrescriptionSpec, step: int) -> PrescriptionSpec:
    """Shorten the LONGER of the two rest fields — ruling 43's reading, and ruling 44's."""
    rest, between = prescription.rest_seconds, prescription.rest_between_sets_seconds
    if between is not None and (rest is None or between >= rest):
        return replace(prescription, rest_between_sets_seconds=_shorter(between, step))
    if rest is not None:
        return replace(prescription, rest_seconds=_shorter(rest, step))
    return prescription


def progressed(
    prescription: PrescriptionSpec,
    *,
    exercise_key: str,
    aspect_key: str,
    protocol_kind: ProtocolKind,
    phase: Phase,
    week_no: int,
) -> PrescriptionSpec:
    """The authored row moved on by this week's own progression, or unchanged where none applies."""
    if phase in UNLOADING_PHASES or exercise_key in OPEN_CLIMBING_KEYS:
        return prescription
    step = min(loading_week_of(week_no), LOADING_WEEKS) - 1
    if step <= 0:
        return prescription
    rule = rule_for(aspect_key, protocol_kind, prescription.work_seconds)
    if rule is WeeklyProgression.MORE_ROUNDS:
        return replace(prescription, sets=prescription.sets + ROUNDS_PER_WEEK * step)
    if rule is WeeklyProgression.SHORTER_REST:
        return _shorten_operative_rest(prescription, step)
    if rule is WeeklyProgression.LONGER_WORK and prescription.work_seconds is not None:
        return replace(
            prescription,
            work_seconds=_longer(prescription.work_seconds, step),
            rest_seconds=_longer(prescription.rest_seconds, step),
            rest_between_sets_seconds=_longer(prescription.rest_between_sets_seconds, step),
        )
    return prescription
