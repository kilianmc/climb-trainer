"""What counts as climbing, how much of a week has to be it, and how long a session runs.

Pure data plus predicates over it — no DB, no clock, no RNG, like the rest of the package.
Three contracts live here because they are one decision: a climbing plan is mostly climbing
(`CLIMBING_FLOOR_PCT`), climbing happens on a wall (`WALL_EQUIPMENT`), and a session is as long
as its *type* deserves rather than as long as the climber is free (`SESSION_WINDOWS`). Issue #84
is what all three exist for: 28% of prescribed minutes were on a wall, whole weeks none. The
bands are Kilian's, set directly, and stored as an **ordinal boundary per discipline** because
`server/domain/grades.py` keeps the two ladders disjoint and a label is not a contract.
"""

import enum
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.vocabulary import Phase, ProtocolKind

# Any block whose exercise needs one of these is wall time; everything else is supplementary.
# `auto_belay` is in the set although issue #84's own measurement omitted it: it is a wall you
# climb without a partner, and leaving it out would have the app tell an auto-belay-only
# climber to go and get somewhere to climb.
WALL_EQUIPMENT: Final[frozenset[str]] = frozenset(
    {
        "bouldering_wall",
        "lead_wall",
        "top_rope_wall",
        "auto_belay",
        # A spray wall is climbing too, which is why `system_board` says so in `EQUIPMENT`.
        # `campus_board` is OUT (Kilian, 2026-08-29): the rule is MOVEMENT versus APPARATUS,
        # not the word "board" — rungs for explosive contact strength sit with `hangboard`
        # and `no_hang_device`, and counting them would let the climbing floor be satisfied
        # by apparatus work, which is the substitution issue #84 exists to prevent.
        "system_board",
        "outdoor_boulders",
        "outdoor_routes",
    }
)

# The aspects a climbing session can be *about* — i.e. that may DEFINE its type and therefore its
# window. `requires_wall()` answers "do these minutes count?" and this answers "may this quality
# name the session?"; conflating them made three wall drills unprescribable. `core_tension` is out
# because a tension drill cannot define a session (Kilian, 2026-08-29). Both #98 aspects are IN:
# `wall_led_aspects()` filters this to on-wall candidates, so no gym lift can lead a session.
WALL_LED_ASPECTS: Final[frozenset[str]] = frozenset(
    {"endurance", "technique", "power", "general_strength", "power_endurance", "anaerobic_capacity"}
)

# Extra time becomes extra volume only here, and only in a loading phase. Everywhere else the low
# volume *is* the protocol, so neither #98 aspect joins: padding them makes another quality.
EXPANDABLE_ASPECTS: Final[frozenset[str]] = frozenset({"endurance", "technique"})

# And even there, at most this multiple of the AUTHORED set count: without the cap a 4-minute
# technique drill reached the window minimum at fifteen sets, which is a fabricated prescription.
MAX_EXPANSION_FACTOR: Final = 2
EXPANDABLE_PROTOCOLS: Final[frozenset[ProtocolKind]] = frozenset(
    {ProtocolKind.LAPS, ProtocolKind.CIRCUIT, ProtocolKind.OTHER}
)
UNLOADING_PHASES: Final[frozenset[Phase]] = frozenset({Phase.DELOAD, Phase.TAPER})


class Level(enum.StrEnum):
    """The climber's band, by CURRENT grade. Never persisted — derived on every generate."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


# One named constant per discipline per boundary, so moving a bar is a one-line change. Kilian's
# labels are French, so the boulder bar sits a rung or two higher — a choice, not a conversion.
BEGINNER_CEILING_SPORT: Final = ordinal_of(GradeSystemKey.FRENCH, "6a+")
INTERMEDIATE_CEILING_SPORT: Final = ordinal_of(GradeSystemKey.FRENCH, "7a+")
BEGINNER_CEILING_BOULDER: Final = ordinal_of(GradeSystemKey.FONT, "6A+")
INTERMEDIATE_CEILING_BOULDER: Final = ordinal_of(GradeSystemKey.FONT, "7A+")

_CEILINGS: Final[Mapping[Discipline, tuple[int, int]]] = MappingProxyType(
    {
        Discipline.SPORT: (BEGINNER_CEILING_SPORT, INTERMEDIATE_CEILING_SPORT),
        Discipline.BOULDER: (BEGINNER_CEILING_BOULDER, INTERMEDIATE_CEILING_BOULDER),
    }
)

# Percent of a week's prescribed minutes that must be wall time. Integer, so the check is exact
# integer arithmetic and no float ever decides whether a week meets its floor.
CLIMBING_FLOOR_PCT: Final[Mapping[Level, int]] = MappingProxyType(
    {Level.BEGINNER: 85, Level.INTERMEDIATE: 75, Level.ADVANCED: 50}
)

# Where the allocator AIMS; the floor above is only the hard lower bound it may never breach.
# Allocating climbing to exhaustion instead put every band at 84-91% and made banding inert.
CLIMBING_TARGET_PCT: Final[Mapping[Level, tuple[int, int]]] = MappingProxyType(
    {Level.BEGINNER: (85, 90), Level.INTERMEDIATE: (75, 82), Level.ADVANCED: (50, 62)}
)

# Wall blocks a session spends by choice — the lever the target band actually moves, because a
# session is three blocks and an advanced climber's second one is where supplementary work goes.
CLIMBING_BLOCKS: Final[Mapping[Level, int]] = MappingProxyType(
    {Level.BEGINNER: 3, Level.INTERMEDIATE: 2, Level.ADVANCED: 1}
)

# Real hangboard sessions a loading week owes, by band. Beginner is zero deliberately: the
# sources want 6-12 months of consistent climbing first and no column records that history.
FINGER_SESSIONS_PER_WEEK: Final[Mapping[Level, int]] = MappingProxyType(
    {Level.BEGINNER: 0, Level.INTERMEDIATE: 1, Level.ADVANCED: 2}
)
FINGER_ASPECT: Final = "finger_strength"
FINGER_PHASES: Final[frozenset[Phase]] = frozenset({Phase.STRENGTH, Phase.POWER})
FINGER_PROTOCOLS: Final[frozenset[ProtocolKind]] = frozenset(
    {ProtocolKind.MAX_HANG, ProtocolKind.REPEATERS}
)

# Quality of effort decides the adaptation, so this work LEADS its session: a max hang sitting
# behind 35 minutes of climbing is the "turn up subpar and set your training back" failure.
PRIORITY_PROTOCOLS: Final[frozenset[ProtocolKind]] = frozenset(
    {ProtocolKind.MAX_HANG, ProtocolKind.REPEATERS, ProtocolKind.LIMIT_BOULDER}
)

# Minutes of prescribed work in a session led by a block of this protocol kind, warm-up
# excluded because the warm-up is not a block. The maximum binds always; the minimum is only
# pursued, and only in a loading phase — `Phase` in `server/domain/vocabulary.py` is explicit
# that a deload has its own prescriptions rather than being a scaled block, so topping one back
# up to a loading week's length would contradict the schema's own definition of it.
SESSION_WINDOWS: Final[Mapping[ProtocolKind, tuple[int, int]]] = MappingProxyType(
    {
        ProtocolKind.MAX_HANG: (20, 45),
        ProtocolKind.REPEATERS: (20, 45),
        ProtocolKind.LIMIT_BOULDER: (40, 90),
        ProtocolKind.INTERVALS: (40, 75),
        ProtocolKind.CIRCUIT: (30, 75),
        ProtocolKind.LAPS: (30, 90),
        ProtocolKind.STRAIGHT_SETS: (20, 60),
        ProtocolKind.HOLD: (15, 45),
        ProtocolKind.OTHER: (20, 60),
    }
)


def level_for(discipline: Discipline, current_ordinal: int) -> Level:
    """The band this climber trains in, from the ordinal boundaries above."""
    beginner_ceiling, intermediate_ceiling = _CEILINGS[discipline]
    if current_ordinal <= beginner_ceiling:
        return Level.BEGINNER
    if current_ordinal <= intermediate_ceiling:
        return Level.INTERMEDIATE
    return Level.ADVANCED


def climbing_floor_pct(discipline: Discipline, current_ordinal: int) -> int:
    """The share of a week's minutes that has to be wall time, for this climber."""
    return CLIMBING_FLOOR_PCT[level_for(discipline, current_ordinal)]


def meets_floor(*, wall_seconds: int, other_seconds: int, floor_pct: int) -> bool:
    """Whether a week's mix is climbing-dominant enough. Exact, integer, no rounding."""
    return wall_seconds * 100 >= floor_pct * (wall_seconds + other_seconds)


def requires_wall(equipment_keys: tuple[str, ...]) -> bool:
    """Whether an exercise's AND set of equipment puts the climber on a wall."""
    return not WALL_EQUIPMENT.isdisjoint(equipment_keys)


def session_window(protocol_kind: ProtocolKind) -> tuple[int, int]:
    """The minutes window for a session led by this protocol kind."""
    return SESSION_WINDOWS[protocol_kind]


def is_expandable(aspect_key: str, protocol_kind: ProtocolKind, phase: Phase) -> bool:
    """Whether extra sets of this block are more training rather than a worse session."""
    return (
        aspect_key in EXPANDABLE_ASPECTS
        and protocol_kind in EXPANDABLE_PROTOCOLS
        and phase not in UNLOADING_PHASES
    )


def climbing_target_band(discipline: Discipline, current_ordinal: int) -> tuple[int, int]:
    """The share of a week's minutes that should be climbing, low and high, for this climber."""
    return CLIMBING_TARGET_PCT[level_for(discipline, current_ordinal)]


def climbing_block_budget(discipline: Discipline, current_ordinal: int) -> int:
    """How many of a session's blocks this band spends on the wall by choice. Not a hard cap: a
    session may take another if it could not otherwise reach its own type's window floor."""
    return CLIMBING_BLOCKS[level_for(discipline, current_ordinal)]


def finger_sessions_for(discipline: Discipline, current_ordinal: int, phase: Phase) -> int:
    """Sessions this week that owe a real hangboard block. Loading phases only."""
    if phase not in FINGER_PHASES:
        return 0
    return FINGER_SESSIONS_PER_WEEK[level_for(discipline, current_ordinal)]


def is_priority(protocol_kind: ProtocolKind) -> bool:
    """Whether this is the quality work a session must not bury behind volume."""
    return protocol_kind in PRIORITY_PROTOCOLS
