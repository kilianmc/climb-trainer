"""The exercise library — authored content, not derived data.

Pure Python, like every module under `server/domain/`. `server/contentseed.py` upserts these
specs and `key` is what it upserts on, so renaming one is a data migration; every other field
may be reworded freely. Aspect, equipment and injury keys are checked against
`server/domain/vocabulary.py` at import time, so a typo cannot reach the seed.
The zero-equipment floor is per ASPECT, not per phase — `CELLS_WITH_NO_GEARLESS_OPTION` is the
exhaustive list of where that bites, and `DELIBERATELY_UNPRESCRIBED` names the empty
(phase, aspect) cells that are periodisation rather than oversight. Both are asserted in BOTH
directions by `tests/test_exercise_library.py`. A thin cell is *named* as a shortfall by the
generator; it is never a refusal for lack of gear (issue #61, Kilian 2026-08-24).

⚠️ **SAFETY BOUNDARY: `substitution_hint` must never point at an improvised finger edge.** A
home-made hangboard, a door frame or a towel hang is the most injury-prone thing a climber can
rig, and suggesting one would contradict the reason `exercise_contraindication` exists.
Improvised load is fine where an exercise merely ADDS weight (backpack, bottle, rock).
`FINGER_LOADING_EQUIPMENT_KEYS` is what the guard test reads.
"""

from dataclasses import dataclass
from typing import Final

from server.domain.grades import Discipline
from server.domain.vocabulary import (
    CLIMBING_ASPECTS,
    EQUIPMENT,
    INJURY_AREAS,
    Phase,
    ProtocolKind,
)

_ASPECT_KEYS: Final[frozenset[str]] = frozenset(spec.key for spec in CLIMBING_ASPECTS)
_EQUIPMENT_KEYS: Final[frozenset[str]] = frozenset(spec.key for spec in EQUIPMENT)
_INJURY_KEYS: Final[frozenset[str]] = frozenset(spec.key for spec in INJURY_AREAS)


def _require(key: str, valid: frozenset[str], vocabulary: str) -> str:
    """Return `key` if the vocabulary has it, else raise — at import, not at INSERT.

    Loud and early on purpose: the alternative is a seed run that dies partway through a
    production transaction, or (worse, if anyone ever "helpfully" skips unknown keys) a
    library quietly missing a requirement nobody notices until a plan prescribes an
    exercise the user cannot do.
    """
    if key not in valid:
        raise ValueError(
            f"{key!r} is not a {vocabulary} key. The authority is "
            f"server/domain/vocabulary.py — add the row there (the seed upserts on `key`, "
            f"so it needs no migration) or fix the spelling here."
        )
    return key


# The three equipment rows that load the fingers directly. Read by the safety guard in
# `tests/test_exercise_library.py`, and resolved through `_require` so this tuple cannot
# drift into naming a row the vocabulary does not have.
FINGER_LOADING_EQUIPMENT_KEYS: Final[frozenset[str]] = frozenset(
    _require(key, _EQUIPMENT_KEYS, "equipment")
    for key in ("hangboard", "campus_board", "no_hang_device")
)


@dataclass(frozen=True, slots=True)
class PrescriptionSpec:
    """One (exercise, phase) row of `prescription_template`.

    `reps` and `work_seconds` are independent and both optional: a repeater has seconds
    and no reps, a pull-up set has reps and no seconds, and a circuit legitimately has
    neither. `rest_seconds` is the rest *within* a set (between repeaters or intervals);
    `rest_between_sets_seconds` is the rest between them.
    """

    phase: Phase
    sets: int
    reps: int | None = None
    work_seconds: int | None = None
    rest_seconds: int | None = None
    rest_between_sets_seconds: int | None = None
    intensity_pct: int | None = None
    target_rpe: int | None = None


@dataclass(frozen=True, slots=True)
class ExerciseSpec:
    """One library exercise, with everything the seed writes for it.

    `equipment_keys` is an **AND set**: every row is a requirement, so an empty tuple
    means the exercise requires nothing and is always prescribable. `discipline` is NULL
    for most of the library — a hangboard protocol serves boulderers and rope climbers
    alike — and set only where the exercise makes no sense on the other one.

    `progression_of_key` / `regression_of_key` mirror the two independent columns on
    `Exercise`: "X is a progression of Y" and "X is a regression of Z" are authored
    separately, in both directions, because neither is inferable from the other at a
    branch point.
    """

    key: str
    name: str
    aspect_key: str
    protocol_kind: ProtocolKind
    instructions: str
    prescriptions: tuple[PrescriptionSpec, ...]
    discipline: Discipline | None = None
    equipment_keys: tuple[str, ...] = ()
    contraindication_keys: tuple[str, ...] = ()
    substitution_hint: str | None = None
    progression_of_key: str | None = None
    regression_of_key: str | None = None

    def __post_init__(self) -> None:
        _require(self.aspect_key, _ASPECT_KEYS, "climbing aspect")
        for key in self.equipment_keys:
            _require(key, _EQUIPMENT_KEYS, "equipment")
        for key in self.contraindication_keys:
            _require(key, _INJURY_KEYS, "injury area")


@dataclass(frozen=True, slots=True)
class UnprescribedCell:
    """One (phase, aspect) pair the library deliberately does not prescribe.

    The reason is the payload: an empty cell with no row here is an oversight, and the guard
    test cannot tell the two apart without being told. Written as data rather than as a
    comment so the test can assert the exemption list has not gone stale.
    """

    phase: Phase
    aspect_key: str
    reason: str

    def __post_init__(self) -> None:
        _require(self.aspect_key, _ASPECT_KEYS, "climbing aspect")


EXERCISES: Final[tuple[ExerciseSpec, ...]] = (
    # ------------------------------------------------------------- finger_strength
    ExerciseSpec(
        key="max_hangs_20mm",
        name="Max hangs on a 20 mm edge",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("hangboard",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Warm up thoroughly first. Hang a 20 mm edge in a half-crimp with the "
            "shoulders engaged, elbows slightly bent, for the prescribed seconds. Add or "
            "remove load so the last two seconds are hard but the grip never opens. Stop "
            "the set the moment the position collapses."
        ),
        # No substitution hint, and that is the safety boundary — see the module docstring.
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=4,
                work_seconds=7,
                rest_between_sets_seconds=120,
                intensity_pct=80,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=5,
                work_seconds=10,
                rest_between_sets_seconds=180,
                intensity_pct=90,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=4,
                work_seconds=10,
                rest_between_sets_seconds=180,
                intensity_pct=95,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=3,
                work_seconds=7,
                rest_between_sets_seconds=180,
                intensity_pct=80,
                target_rpe=6,
            ),
        ),
    ),
    ExerciseSpec(
        key="hangboard_repeaters",
        name="Hangboard repeaters",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.REPEATERS,
        equipment_keys=("hangboard",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Seven seconds on, three seconds off, six times through without stepping "
            "away from the board. Pick an edge and a load you can hold for the whole set "
            "with the same grip position; if the last repetition is a fight to stay on, "
            "the load is too high for this protocol."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=3,
                reps=6,
                work_seconds=7,
                rest_seconds=3,
                rest_between_sets_seconds=180,
                intensity_pct=60,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=4,
                reps=6,
                work_seconds=7,
                rest_seconds=3,
                rest_between_sets_seconds=180,
                intensity_pct=65,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=2,
                reps=6,
                work_seconds=7,
                rest_seconds=3,
                rest_between_sets_seconds=180,
                # Same intensity as BASE, two sets instead of three: `Phase` defines a
                # deload as lower volume at unchanged intensity, and dropping the load too
                # is how a deload block quietly becomes a detraining one.
                intensity_pct=60,
                target_rpe=6,
            ),
        ),
    ),
    ExerciseSpec(
        key="self_resisted_finger_isometrics",
        name="Self-resisted finger isometrics",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.HOLD,
        # The finger-strength floor: no gear at all. See the module docstring.
        contraindication_keys=("fingers",),
        instructions=(
            "Press the fingertips of one hand into the palm of the other and pull as if "
            "closing a crimp, holding the shape for the prescribed seconds. The opposing "
            "hand is the load, so it can never spike. This is a floor for weeks with no "
            "access to a board, not a replacement for one: real progression needs a real "
            "edge, and improvising an edge from a door frame or a towel is how pulleys "
            "get injured."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, work_seconds=10, rest_between_sets_seconds=60, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, work_seconds=10, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, work_seconds=10, rest_between_sets_seconds=60, target_rpe=5
            ),
        ),
    ),
    ExerciseSpec(
        key="hangboard_min_edge_hangs",
        name="Minimum-edge hangs",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("hangboard",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Bodyweight only, on the smallest edge you can hold in a half-crimp for the "
            "prescribed seconds without the grip opening. The edge depth is the load, so "
            "there is no percentage to chase: drop one size only when the last second of "
            "every set is still controlled."
        ),
        # No substitution hint, and no `intensity_pct` — the edge IS the intensity here.
        progression_of_key="max_hangs_20mm",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=5, work_seconds=7, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=4, work_seconds=5, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=4,
                work_seconds=7,
                rest_between_sets_seconds=180,
                target_rpe=9,
            ),
        ),
    ),
    ExerciseSpec(
        key="weighted_max_hangs",
        name="Weighted max hangs",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("hangboard", "weight_belt"),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "A comfortable edge, a half-crimp, and enough hung weight that the prescribed "
            "seconds are all you could hold. Add load in small steps across a block rather "
            "than in one jump, and end the set the moment the fingers start to open — the "
            "last repetition of a hang protocol is where pulleys go."
        ),
        # No substitution hint: added load belongs on a belt or a harness, and the rest of
        # the safety boundary is in the module docstring.
        progression_of_key="max_hangs_20mm",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=5,
                work_seconds=10,
                rest_between_sets_seconds=180,
                intensity_pct=90,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=4,
                work_seconds=8,
                rest_between_sets_seconds=180,
                intensity_pct=95,
                target_rpe=9,
            ),
        ),
    ),
    ExerciseSpec(
        key="open_hand_drag_hangs",
        name="Open-hand drag hangs",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("hangboard",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "The same hang with the fingers straight and the thumb off — a drag, not a "
            "crimp. It is the grip position climbing uses most and the one boards train "
            "least, so keep the load lower than your half-crimp hangs and let the position "
            "be the point."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=4,
                work_seconds=10,
                rest_between_sets_seconds=120,
                intensity_pct=70,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=4,
                work_seconds=10,
                rest_between_sets_seconds=180,
                intensity_pct=80,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=3,
                work_seconds=7,
                rest_between_sets_seconds=180,
                intensity_pct=70,
                target_rpe=6,
            ),
        ),
    ),
    ExerciseSpec(
        key="hangboard_density_hangs",
        name="Density hangs",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.HOLD,
        equipment_keys=("hangboard",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Long hangs on a big edge at a load you could hold for twice the time, "
            "accumulating minutes rather than chasing a maximum. Deliberately dull: it "
            "builds tissue tolerance for the blocks where the hangs get heavy, and it is "
            "the finger session that fits a week already full of hard climbing."
        ),
        regression_of_key="max_hangs_20mm",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=4,
                work_seconds=30,
                rest_between_sets_seconds=120,
                intensity_pct=55,
                target_rpe=6,
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=5,
                work_seconds=30,
                rest_between_sets_seconds=90,
                intensity_pct=55,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=3,
                work_seconds=30,
                rest_between_sets_seconds=120,
                intensity_pct=55,
                target_rpe=5,
            ),
        ),
    ),
    ExerciseSpec(
        key="no_hang_edge_lifts",
        name="No-hang edge lifts",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("no_hang_device",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Set the device on the floor, take a half-crimp on the edge and lift until the "
            "load leaves the ground, holding for the prescribed seconds with the arm nearly "
            "straight. Nothing is suspended, so a failing grip sets the weight down instead "
            "of dropping you — which is what makes this the protocol to use around a shaky "
            "elbow or a return from a finger injury."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=4,
                work_seconds=10,
                rest_between_sets_seconds=120,
                intensity_pct=70,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=5,
                work_seconds=10,
                rest_between_sets_seconds=180,
                intensity_pct=85,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=3,
                work_seconds=7,
                rest_between_sets_seconds=120,
                intensity_pct=70,
                target_rpe=6,
            ),
        ),
    ),
    ExerciseSpec(
        key="no_hang_pinch_lifts",
        name="No-hang pinch lifts",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("no_hang_device",),
        contraindication_keys=("fingers", "wrist", "elbow"),
        instructions=(
            "Pinch the block between thumb and fingers and lift it to the prescribed hold "
            "time, one hand at a time. The thumb is the muscle climbing trains least and "
            "pinches ask for most, so keep the wrist neutral and the load honest — a pinch "
            "that slips through the fingers is not a rep."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=3,
                work_seconds=10,
                rest_between_sets_seconds=90,
                intensity_pct=70,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=4,
                work_seconds=10,
                rest_between_sets_seconds=120,
                intensity_pct=85,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=2,
                work_seconds=10,
                rest_between_sets_seconds=90,
                intensity_pct=70,
                target_rpe=5,
            ),
        ),
    ),
    ExerciseSpec(
        key="no_hang_recruitment_pulls",
        name="No-hang recruitment pulls",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("no_hang_device",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Against an immovable load, pull as hard as you possibly can for three to five "
            "seconds, then rest completely. Intent is the whole stimulus: nothing moves, "
            "the fingers never reach failure, and a set that lasts longer than five seconds "
            "has become a strength hold instead of a recruitment pull."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER, sets=6, work_seconds=5, rest_between_sets_seconds=180, target_rpe=10
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=5,
                work_seconds=5,
                rest_between_sets_seconds=180,
                target_rpe=10,
            ),
        ),
    ),
    ExerciseSpec(
        key="one_arm_assisted_hangs",
        name="One-arm assisted hangs",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.MAX_HANG,
        equipment_keys=("hangboard", "resistance_bands"),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "Hang one hand on a comfortable edge with a band taking just enough weight that "
            "the prescribed seconds are all you have. Take the band down a size across a "
            "block rather than removing it in one step, and keep the shoulder pulled in — "
            "a one-arm hang punishes a passive shoulder faster than a two-arm one."
        ),
        # No substitution hint: the band is assistance on a real edge, and everything else
        # would be an improvised one. See the module docstring.
        progression_of_key="max_hangs_20mm",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=6, work_seconds=7, rest_between_sets_seconds=150, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=5, work_seconds=5, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=4,
                work_seconds=7,
                rest_between_sets_seconds=180,
                target_rpe=9,
            ),
        ),
    ),
    ExerciseSpec(
        key="no_hang_repeaters",
        name="No-hang repeaters",
        aspect_key="finger_strength",
        protocol_kind=ProtocolKind.REPEATERS,
        equipment_keys=("no_hang_device",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Seven on, three off, six times through, lifting the device from the floor "
            "instead of hanging off a board. Nothing is suspended, so the load comes off the "
            "moment the grip fades and the elbows take none of the shock — which is what "
            "makes this the density session to run when the boards have been busy."
        ),
        regression_of_key="hangboard_repeaters",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=3,
                reps=6,
                work_seconds=7,
                rest_seconds=3,
                rest_between_sets_seconds=180,
                intensity_pct=60,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=4,
                reps=6,
                work_seconds=7,
                rest_seconds=3,
                rest_between_sets_seconds=150,
                intensity_pct=65,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=2,
                reps=6,
                work_seconds=7,
                rest_seconds=3,
                rest_between_sets_seconds=180,
                intensity_pct=60,
                target_rpe=6,
            ),
        ),
    ),
    # ------------------------------------------------------------ general_strength
    ExerciseSpec(
        key="weighted_pull_ups",
        name="Weighted pull-ups",
        aspect_key="general_strength",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("pull_up_bar", "weight_belt"),
        contraindication_keys=("elbow", "shoulder"),
        instructions=(
            "Low reps with enough added weight that the last one is slow but never ugly. "
            "Full hang at the bottom with the shoulders engaged, chin past the bar at the "
            "top, and no kick — the point is force through a locked-in shoulder, which is "
            "what a hard first move off the ground actually asks for."
        ),
        substitution_hint="No belt? A packed backpack carries the same load.",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=5, reps=5, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=4, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="split_squats",
        name="Split squats",
        aspect_key="general_strength",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        # The general-strength floor: no gear at all. See the module docstring.
        contraindication_keys=("knee", "hip"),
        instructions=(
            "Long stance, back knee tracking down towards the floor, front foot flat, and "
            "stand back up through the front leg. Reps are per leg, so a set of five is five "
            "each side. Every hard step-through in climbing is loaded on one leg with the hips "
            "off-centre and a two-legged squat never trains that. Depth first, load second: "
            "put the rear foot on a step when bodyweight alone stops being hard, and only add "
            "weight once the full range is easy."
        ),
        substitution_hint="Bodyweight too easy? A packed backpack adds load with no kit at all.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=8, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=5, rest_between_sets_seconds=120, target_rpe=8
            ),
            # Maintenance from here: low volume is the protocol, not a shortfall, and heavy
            # legs inside a power or performance week cost more than they return.
            PrescriptionSpec(
                Phase.POWER, sets=2, reps=5, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=5, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=8, rest_between_sets_seconds=90, target_rpe=5
            ),
        ),
    ),
    ExerciseSpec(
        key="one_arm_lockoff_negatives",
        name="One-arm lock-offs and negatives",
        aspect_key="general_strength",
        protocol_kind=ProtocolKind.HOLD,
        equipment_keys=("pull_up_bar",),
        contraindication_keys=("elbow", "shoulder"),
        instructions=(
            "Hold a one-arm lock-off at the top with the other hand assisting as little as "
            "it must, then lower under control for the count. The slow half is the point: "
            "most people can pull past a hold they cannot stop at, and the moves that get "
            "dropped are the ones that need stopping."
        ),
        substitution_hint="No bar? Rings work, with the shoulder free to rotate.",
        progression_of_key="weighted_pull_ups",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=5, work_seconds=8, rest_between_sets_seconds=150, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=4, work_seconds=5, rest_between_sets_seconds=180, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="single_leg_squats",
        name="Single-leg squats",
        aspect_key="general_strength",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        # A second general-strength floor: no gear at all. See the module docstring.
        contraindication_keys=("knee", "hip", "ankle"),
        instructions=(
            "Stand on one leg and lower under control as far as the position holds, then "
            "press back up with no wobble and no hop; hold a pole or the back of a chair for "
            "balance while you are learning it. Reps are per leg, so a set of five is five "
            "each side. This is the high step — the deepest single-leg pressing position a "
            "climber ever has to stand out of — and it is the one leg exercise every source "
            "agrees on. Depth first, load second."
        ),
        substitution_hint=(
            "Not there yet? Sit back to a low box and stand out of that, lowering the box as "
            "the range comes."
        ),
        progression_of_key="split_squats",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=5, rest_between_sets_seconds=120, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=4, rest_between_sets_seconds=150, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=5, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=6, rest_between_sets_seconds=120, target_rpe=5
            ),
        ),
    ),
    ExerciseSpec(
        key="single_leg_hip_thrusts_and_rdls",
        name="Single-leg hip thrusts and Romanian deadlifts",
        aspect_key="general_strength",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        contraindication_keys=("lower_back", "hip", "knee"),
        instructions=(
            "Alternate a slow single-leg hip thrust with a single-leg Romanian deadlift, "
            "keeping the hips level in both. Reps are per leg, so a set of six is six each "
            "side. Hamstrings and glutes are what hold a heel hook in and pull the body into "
            "steep ground, and they are the muscles climbers train least — controlled beats "
            "heavy here, because the tissue you want is the bit that cramps on a hard heel."
        ),
        substitution_hint=(
            "Bodyweight stopped being enough? A weight held at the chest or in the free hand "
            "loads either half."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=10, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=6, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=2, reps=8, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=8, rest_between_sets_seconds=90, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=10, rest_between_sets_seconds=90, target_rpe=4
            ),
        ),
    ),
    ExerciseSpec(
        key="deadlifts",
        name="Deadlifts",
        aspect_key="general_strength",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("free_weights",),
        contraindication_keys=("lower_back", "hip"),
        instructions=(
            "Hinge at the hips with a flat back and stand up with the load one rep at a "
            "time, resetting the brace before each. Low reps and heavy: this is the whole "
            "posterior chain learning to produce force through a locked spine, which is what "
            "a rock-over, a mantel and a high heel hook all ask for. Add load a little at a "
            "time, and stop the set when the back rounds rather than when the legs give out. "
            "Whether a climber needs this at all is genuinely contested — the plan keeps the "
            "volume low for that reason."
        ),
        substitution_hint=(
            "No barbell? A heavy kettlebell or a packed pack held between the hands hinges "
            "the same way, and single-leg Romanian deadlifts are the no-load version."
        ),
        progression_of_key="single_leg_hip_thrusts_and_rdls",
        # No base row: `PHASE_GUIDE[BASE]` promises strength gets its own block and that base
        # leg work is unilateral, and a bilateral hinge here would falsify both.
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=3,
                reps=3,
                rest_between_sets_seconds=180,
                intensity_pct=85,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=2,
                reps=6,
                rest_between_sets_seconds=120,
                intensity_pct=60,
                target_rpe=5,
            ),
        ),
    ),
    ExerciseSpec(
        key="heavy_single_arm_rows",
        name="Heavy single-arm rows",
        aspect_key="general_strength",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("free_weights",),
        contraindication_keys=("shoulder", "elbow", "lower_back"),
        instructions=(
            "Brace on a bench or a knee, row the weight to the hip, and lower it slowly. "
            "Reps are per side, so a set of four is four each arm. Low reps with real load: "
            "climbing pulls overhead and almost never horizontally, so the mid-back only "
            "ever gets strong in one direction. The higher-rep balance version of this lives "
            "in antagonist and prehab work — this one is meant to be heavy."
        ),
        substitution_hint=(
            "No dumbbells? A packed backpack rowed off a knee is load enough, and inverted "
            "rows under a bar are the bodyweight version."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=3,
                reps=8,
                rest_between_sets_seconds=90,
                intensity_pct=65,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=3,
                reps=4,
                rest_between_sets_seconds=120,
                intensity_pct=85,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=8, rest_between_sets_seconds=90, target_rpe=5
            ),
        ),
    ),
    # ------------------------------------------------------------------------ power
    ExerciseSpec(
        key="limit_boulders",
        name="Limit boulders",
        aspect_key="power",
        protocol_kind=ProtocolKind.LIMIT_BOULDER,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder"),
        instructions=(
            "Pick a boulder of two to five moves that takes several attempts, and give "
            "each attempt everything with a full rest in between. Quality over quantity: "
            "when the attempts stop looking like the good ones, the session is done."
        ),
        substitution_hint=(
            "No wall available? Standing broad and squat jumps train the same explosive "
            "intent with no gear at all."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=8, reps=1, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=10, reps=1, rest_between_sets_seconds=240, target_rpe=10
            ),
            # A maintenance dose, not a block: max power is kept through the
            # power-endurance weeks rather than rebuilt afterwards.
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=5, reps=1, rest_between_sets_seconds=240, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=8, reps=1, rest_between_sets_seconds=240, target_rpe=10
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=5, reps=1, rest_between_sets_seconds=180, target_rpe=7
            ),
            # Three attempts at full intent cost almost nothing to recover from and are
            # what stops a taper week feeling like a week off.
            PrescriptionSpec(
                Phase.TAPER, sets=3, reps=1, rest_between_sets_seconds=300, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="campus_ladders",
        name="Campus board ladders",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("campus_board",),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "Ladder up the rungs one hand at a time, matching nothing, and step off at "
            "the top rather than dropping. Large rungs only, and only on a day the "
            "fingers feel fresh — this is a contact-strength stimulus, so three crisp "
            "sets beat six tired ones."
        ),
        # No substitution hint: see the safety boundary in the module docstring.
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER, sets=6, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=2, rest_between_sets_seconds=180, target_rpe=6
            ),
        ),
    ),
    ExerciseSpec(
        key="standing_jumps",
        name="Standing broad and squat jumps",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        contraindication_keys=("knee", "ankle"),
        instructions=(
            "Alternate a maximal broad jump and a maximal squat jump, landing softly "
            "through the whole foot. Every repetition is an all-out effort with a full "
            "reset between, because a tired jump trains something else entirely."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=6, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER, sets=5, reps=5, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=5, rest_between_sets_seconds=120, target_rpe=8
            ),
            # Full intent, almost no volume: short maximal efforts with complete rest keep
            # the snap through a taper week without costing anything to recover from.
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=3, rest_between_sets_seconds=180, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="explosive_ring_pull_ups",
        name="Explosive ring pull-ups",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("gymnastic_rings",),
        contraindication_keys=("elbow", "shoulder", "wrist"),
        instructions=(
            "Pull as fast as you can and try to leave the rings at the top, landing back "
            "into a controlled hang rather than dropping onto straight arms. The rings let "
            "the shoulders rotate as they want to, which is why this is the explosive "
            "pulling drill to use if a fixed bar bothers an elbow."
        ),
        substitution_hint=(
            "No rings? The same fast pull works on a bar, with less shoulder freedom."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=5, rest_between_sets_seconds=150, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=5, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=3, rest_between_sets_seconds=150, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="campus_board_bumps",
        name="Campus board bumps",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("campus_board",),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "From a matched start, drive one hand up two rungs and immediately bump it up "
            "one more, then step off. Large rungs, fresh fingers, and long rests: this is "
            "the most concentrated contact-strength stimulus in the library and the easiest "
            "one to overdose."
        ),
        # No substitution hint: see the safety boundary in the module docstring.
        progression_of_key="campus_ladders",
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER, sets=5, reps=2, rest_between_sets_seconds=240, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=2, rest_between_sets_seconds=240, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="single_move_boulder_repeats",
        name="Single-move repeats",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder"),
        instructions=(
            "Pick one hard move you can just do, and do it again and again with a full rest "
            "between attempts, stopping the set when it stops feeling identical. Repeating "
            "a move you already have is how the movement becomes fast rather than merely "
            "possible."
        ),
        regression_of_key="limit_boulders",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=6, reps=2, rest_between_sets_seconds=120, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=6, reps=1, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=8, reps=1, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=1, rest_between_sets_seconds=240, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=4, reps=1, rest_between_sets_seconds=180, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=3, reps=1, rest_between_sets_seconds=180, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="outdoor_boulder_projecting",
        name="Outdoor boulder projecting",
        aspect_key="power",
        protocol_kind=ProtocolKind.LIMIT_BOULDER,
        discipline=Discipline.BOULDER,
        equipment_keys=("outdoor_boulders",),
        contraindication_keys=("fingers", "shoulder", "ankle"),
        instructions=(
            "Attempts on a boulder at your limit, with the pads set and the landing checked "
            "before the first pull. Real rock gives fewer attempts per session than a wall "
            "does — skin and conditions decide the count — so rest hard between them and "
            "stop while the attempts still look like the good ones."
        ),
        substitution_hint="Nothing dry to climb on? Indoor limit boulders train the same thing.",
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER, sets=8, reps=1, rest_between_sets_seconds=300, target_rpe=10
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=6, reps=1, rest_between_sets_seconds=420, target_rpe=10
            ),
        ),
    ),
    ExerciseSpec(
        key="dyno_and_swing_practice",
        name="Dyno and swing catches",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder", "ankle"),
        instructions=(
            "Jumping moves and swinging catches on big holds: commit fully, catch with the "
            "shoulders engaged, and step off rather than riding a failed attempt to the mat. "
            "Coordination is the trainable part here, not force, so stop the set when the "
            "timing goes rather than when the arms do."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=4, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER, sets=6, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=4, reps=3, rest_between_sets_seconds=180, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="loaded_jump_squats",
        name="Loaded jump squats",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("free_weights",),
        contraindication_keys=("knee", "ankle", "lower_back"),
        instructions=(
            "Light load held close, dip fast and jump as high as the weight allows, resetting "
            "fully between repetitions. Legs drive every high step, mantel and rock-over, and "
            "they are the part of a climber that almost never gets trained fast."
        ),
        substitution_hint="No weights? Unloaded squat jumps with the same full reset.",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=5, rest_between_sets_seconds=150, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=5, reps=4, rest_between_sets_seconds=180, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="boulders_on_the_two_minute",
        name="Boulders on the two-minute",
        aspect_key="power",
        protocol_kind=ProtocolKind.INTERVALS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder"),
        instructions=(
            "Pick problems at around three-quarters of the hardest you can climb first try, "
            "and start a new one every two minutes on the clock: climb, step off, wait out "
            "the rest, go again. Every other power option here is a maximum effort and this "
            "one deliberately is not — a dozen or more fast, clean problems cost far less to "
            "recover from than a dozen limit attempts, which is what makes this the power "
            "session you can put in a week that already has hard sessions in it. Stop when "
            "the movement stops looking crisp rather than when the clock runs out."
        ),
        substitution_hint=(
            "No wall? Standing broad and squat jumps on the same two-minute clock keep the "
            "intent, without the climbing."
        ),
        regression_of_key="limit_boulders",
        # No base row: both sources maintain anaerobic power through a base block rather than
        # training it, and `PHASE_GUIDE[BASE]` publishes that power sits last there.
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=12,
                work_seconds=30,
                rest_seconds=90,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.POWER,
                sets=16,
                work_seconds=30,
                rest_seconds=90,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=8,
                work_seconds=30,
                rest_seconds=90,
                target_rpe=5,
            ),
        ),
    ),
    ExerciseSpec(
        key="explosive_move_intervals",
        name="Explosive move intervals",
        aspect_key="power",
        protocol_kind=ProtocolKind.INTERVALS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder"),
        instructions=(
            "One big fast move, or a two-move burst, then step off and wait out a rest eight "
            "times as long as the work. Six seconds on and forty-eight off is what keeps "
            "every repetition genuinely explosive, and the rest is not generosity: it is "
            "what an all-out effort costs. This is the cheapest on-the-wall power work in the "
            "library in minutes and the easiest to spoil — progress it by moving on harder "
            "holds or adding intervals, never by shortening the gaps."
        ),
        substitution_hint=(
            "No wall? A maximal standing jump on the same clock trains the same intent."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=10,
                work_seconds=6,
                rest_seconds=48,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.POWER,
                sets=12,
                work_seconds=6,
                rest_seconds=48,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=10,
                work_seconds=6,
                rest_seconds=48,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.TAPER,
                sets=6,
                work_seconds=6,
                rest_seconds=48,
                target_rpe=8,
            ),
        ),
    ),
    ExerciseSpec(
        key="big_move_power_problems",
        name="Big-move power problems",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder"),
        instructions=(
            "Choose problems whose difficulty is the size of the moves rather than the size "
            "of the holds — long reaches and hard pulls between holds you can actually keep "
            "— and take a full rest before each attempt. Picking for span instead of for "
            "skin is what makes this a power session you can repeat later in the week, and "
            "it is where a power block belongs on a day the fingers are tired but the arms "
            "are not."
        ),
        substitution_hint=(
            "Nothing with the reach? The same intent on the steepest wall you have, feet "
            "deliberately low."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=5, reps=2, rest_between_sets_seconds=180, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=6, reps=2, rest_between_sets_seconds=240, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=2, rest_between_sets_seconds=240, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="short_rest_boulder_sets",
        name="Short-rest boulder sets",
        aspect_key="power",
        protocol_kind=ProtocolKind.CIRCUIT,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "Four boulders of five to seven moves, climbed with a rest no longer than the "
            "climb between them, then a long rest before the next set. This is not a 4x4: "
            "these are hard and short, and the target is being powered out rather than "
            "pumped. Progress it by cutting the rest between the boulders until all four run "
            "with no rest at all, and leave the boulders themselves where they are while you "
            "do."
        ),
        substitution_hint=(
            "Only easier problems available? Add a move or two to each rather than more boulders."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=3,
                reps=4,
                rest_seconds=20,
                rest_between_sets_seconds=480,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.POWER,
                sets=4,
                reps=4,
                rest_seconds=20,
                rest_between_sets_seconds=600,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=3,
                reps=4,
                rest_seconds=20,
                rest_between_sets_seconds=480,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=3,
                reps=4,
                rest_seconds=20,
                rest_between_sets_seconds=600,
                target_rpe=9,
            ),
        ),
    ),
    ExerciseSpec(
        key="latch_repeats_on_big_holds",
        name="Latch repeats on big holds",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder", "elbow"),
        instructions=(
            "One committing move to a big hold, caught with the shoulders already engaged, "
            "repeated from the same start with a full rest between attempts. This is the "
            "high-force half of a jumping move and it is not the coordination drill: dyno "
            "and swing catches are done at a moderate effort to learn the timing, and these "
            "are done near your maximum to train the catch itself. Big holds only, because "
            "the whole load arrives on the fingers at the worst moment of the move."
        ),
        progression_of_key="dyno_and_swing_practice",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=5, reps=3, rest_between_sets_seconds=180, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=6, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="broken_circuit_redpoint",
        name="Broken circuit redpoint",
        aspect_key="power",
        protocol_kind=ProtocolKind.CIRCUIT,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "Set yourself a hard circuit of around twenty-five moves, split it into three or "
            "four sections, and work the sections one at a time before ever trying the whole "
            "thing. Then link them: two sections, then three, then the lot. It is redpointing "
            "as a training method rather than as an outcome, and the reason it belongs in a "
            "gym is that you can build the circuit to be exactly what you are bad at."
        ),
        substitution_hint=(
            "Nothing long enough set? Build the circuit out of holds from three problems "
            "that share a panel."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=4,
                work_seconds=25,
                rest_between_sets_seconds=240,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.POWER,
                sets=4,
                work_seconds=25,
                rest_between_sets_seconds=300,
                target_rpe=9,
            ),
            # The linking stage: fewer, longer pieces on a longer rest, which is what turns
            # the worked sections into one continuous effort.
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=3,
                work_seconds=90,
                rest_between_sets_seconds=420,
                target_rpe=9,
            ),
        ),
    ),
    ExerciseSpec(
        key="system_board_limit_moves",
        name="System board limit moves",
        aspect_key="power",
        protocol_kind=ProtocolKind.LIMIT_BOULDER,
        equipment_keys=("system_board",),
        contraindication_keys=("fingers", "shoulder", "elbow"),
        instructions=(
            "Two or three moves at your absolute limit on a steep board, tried until they "
            "stop improving. The board removes the reading and the footwork puzzle, so "
            "every attempt is a pure force effort — which is the appeal and also why the "
            "session is short."
        ),
        substitution_hint="No board? A two-move limit boulder on the steepest wall you have.",
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER, sets=8, reps=1, rest_between_sets_seconds=240, target_rpe=10
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=6, reps=1, rest_between_sets_seconds=240, target_rpe=10
            ),
        ),
    ),
    ExerciseSpec(
        key="outdoor_route_crux_repeats",
        name="Outdoor crux repeats",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        discipline=Discipline.SPORT,
        equipment_keys=("outdoor_routes",),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "On a rope, work the two or three hardest moves of a route in isolation, hanging "
            "the bolt between attempts and doing them again. It is the strength session a "
            "rock-only climber actually has access to: the movement is the real thing, the "
            "rests are as long as you make them, and the volume stays low."
        ),
        substitution_hint="Nothing outdoors? Hard linked moves on a steep indoor route.",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=6, reps=2, rest_between_sets_seconds=240, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=6, reps=1, rest_between_sets_seconds=300, target_rpe=10
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=1, rest_between_sets_seconds=300, target_rpe=10
            ),
        ),
    ),
    ExerciseSpec(
        key="outdoor_boulder_move_repeats",
        name="Outdoor single-move repeats",
        aspect_key="power",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        discipline=Discipline.BOULDER,
        equipment_keys=("outdoor_boulders",),
        contraindication_keys=("fingers", "shoulder", "ankle"),
        instructions=(
            "One hard move on rock, repeated from the same start with a full rest between "
            "attempts. Rock holds do not give a second chance at a bad body position, which "
            "is why repeating a single move outdoors teaches more per attempt than a whole "
            "problem does — and why the strength block does not have to move indoors."
        ),
        substitution_hint="Nothing dry? The same single-move repeats on a wall.",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=6, reps=2, rest_between_sets_seconds=240, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.POWER, sets=8, reps=1, rest_between_sets_seconds=300, target_rpe=10
            ),
        ),
    ),
    # ---------------------------------------------------------- anaerobic_capacity
    ExerciseSpec(
        key="route_intervals",
        name="On-the-minute route intervals",
        aspect_key="anaerobic_capacity",
        protocol_kind=ProtocolKind.INTERVALS,
        discipline=Discipline.SPORT,
        equipment_keys=("lead_wall",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Climb hard for a minute, lower, take the prescribed rest, repeat. The rest is "
            "twice the work: long enough to start the next interval able to climb it, short "
            "enough that the burn from the last one is still there. The timer is the "
            "authority, not how recovered you feel. Choose a route sustained enough "
            "that you are pumped at the end of the first interval and have to fight "
            "through the last one."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=6,
                work_seconds=60,
                rest_between_sets_seconds=120,
                target_rpe=8,
            ),
        ),
    ),
    ExerciseSpec(
        key="linked_board_circuit",
        name="Linked board circuit",
        aspect_key="anaerobic_capacity",
        protocol_kind=ProtocolKind.CIRCUIT,
        equipment_keys=("system_board",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Link two or three moderate board problems back to back without coming off, "
            "then rest and repeat. The board's steepness makes the forearms the limit "
            "quickly, so pick problems you could climb twice over on a fresh day."
        ),
        substitution_hint="No board? Four boulders climbed back to back are the same circuit.",
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=4,
                work_seconds=60,
                rest_between_sets_seconds=180,
                target_rpe=9,
            ),
        ),
    ),
    ExerciseSpec(
        key="self_resisted_forearm_intervals",
        name="Self-resisted forearm intervals",
        aspect_key="anaerobic_capacity",
        protocol_kind=ProtocolKind.INTERVALS,
        # The anaerobic-capacity floor: no gear at all. See the module docstring.
        contraindication_keys=("fingers",),
        instructions=(
            "Press the fingertips of one hand into the palm of the other and pull as if "
            "closing a crimp, holding that effort for the whole work interval and taking the "
            "rest exactly on the clock. Sets are per hand: run them on one, then repeat on the "
            "other. The opposing hand is the load, so it can never spike — and there is nothing "
            "external to add, so this progresses by holding the same effort for one more "
            "interval and never by loading it heavier. It is a floor for weeks with no wall and "
            "no board, not a replacement for either: this capacity is trained by climbing, and "
            "improvising an edge from a door frame or a towel is how pulleys get injured."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=6, work_seconds=40, rest_between_sets_seconds=120, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH,
                sets=6,
                work_seconds=40,
                rest_between_sets_seconds=120,
                target_rpe=7,
            ),
            # One a week through the power and power-endurance blocks: 16 weeks or more of work
            # is what this quality asks for, so it is maintained rather than rebuilt.
            PrescriptionSpec(
                Phase.POWER, sets=4, work_seconds=40, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=8,
                work_seconds=40,
                rest_between_sets_seconds=120,
                target_rpe=8,
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, work_seconds=40, rest_between_sets_seconds=120, target_rpe=5
            ),
        ),
    ),
    ExerciseSpec(
        key="auto_belay_interval_laps",
        name="Auto belay interval laps",
        aspect_key="anaerobic_capacity",
        protocol_kind=ProtocolKind.INTERVALS,
        discipline=Discipline.SPORT,
        equipment_keys=("auto_belay",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Climb a sustained route, ride the device down, and go again on the clock. With "
            "nobody to wait for, the rest is exactly what the timer says — which is what "
            "makes an auto belay the most honest interval tool in the building."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=6,
                work_seconds=90,
                rest_between_sets_seconds=180,
                target_rpe=8,
            ),
        ),
    ),
    ExerciseSpec(
        key="machine_anaerobic_intervals",
        name="Machine anaerobic intervals",
        aspect_key="anaerobic_capacity",
        protocol_kind=ProtocolKind.INTERVALS,
        equipment_keys=("cardio_machine",),
        contraindication_keys=("knee", "lower_back"),
        instructions=(
            "Hard forty-second efforts on a bike, rower or treadmill with a short rest "
            "between them, until the last one is a fight. It trains the anaerobic system "
            "without touching the fingers, which is exactly what a week with tired forearms "
            "and a scheduled capacity session needs."
        ),
        substitution_hint="No machine? The same intervals work on a hill or a stairwell.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=6, work_seconds=40, rest_between_sets_seconds=80, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=8,
                work_seconds=40,
                rest_between_sets_seconds=60,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=4, work_seconds=40, rest_between_sets_seconds=80, target_rpe=6
            ),
        ),
    ),
    ExerciseSpec(
        key="two_problem_links",
        name="Two-problem links",
        aspect_key="anaerobic_capacity",
        protocol_kind=ProtocolKind.CIRCUIT,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Link two moderate problems back to back without coming off, aiming for twelve "
            "to fifteen moves and about forty seconds of climbing, then rest three times as "
            "long and go again. Expect to come off on roughly one link in four: this works "
            "at an intensity you cannot always finish. Progress it by linking harder or "
            "longer problems and never by cutting the rest — a shorter rest makes it a "
            "different session, and this is the quality that takes four months to build."
        ),
        substitution_hint=(
            "Problems too short to reach twelve moves? Reverse the first one back down to "
            "the ground before you start the second."
        ),
        # Two authored volumes, both the source's: eight to ten reps where this quality is
        # the point, and a set of three to five where it is tagged onto a strength session.
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=8, work_seconds=40, rest_between_sets_seconds=120, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, work_seconds=40, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=4, work_seconds=40, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=4,
                work_seconds=40,
                rest_between_sets_seconds=120,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=4, work_seconds=40, rest_between_sets_seconds=120, target_rpe=6
            ),
        ),
    ),
    ExerciseSpec(
        key="traverse_intervals",
        name="Traverse intervals",
        aspect_key="anaerobic_capacity",
        protocol_kind=ProtocolKind.INTERVALS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Traverse a line of twelve to fifteen hard enough moves in about forty seconds, "
            "drop off, and take two and a half times that as rest. A traverse is the version "
            "of this you can make any length you like, which is why it sits beside linked "
            "problems: a gym whose problems are all six moves long cannot reach forty "
            "seconds any other way. It is the opposite of ARC traversing — that is a "
            "conversation-pace pump you never fail, and this leaves you powered out."
        ),
        substitution_hint=("Nowhere to traverse? Two linked problems reach the same move count."),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=8, work_seconds=40, rest_between_sets_seconds=100, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=5, work_seconds=40, rest_between_sets_seconds=100, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=4, work_seconds=40, rest_between_sets_seconds=100, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=6,
                work_seconds=40,
                rest_between_sets_seconds=100,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=4, work_seconds=40, rest_between_sets_seconds=100, target_rpe=6
            ),
        ),
    ),
    # -------------------------------------------------------------- power_endurance
    ExerciseSpec(
        key="boulder_four_by_four",
        name="4x4 boulder circuits",
        aspect_key="power_endurance",
        protocol_kind=ProtocolKind.CIRCUIT,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Four boulders you can climb comfortably, back to back with no rest between "
            "them, then a long rest before the next round. Pick them two grades below "
            "your limit — the last round should be ugly from fatigue, not from the moves "
            "being too hard."
        ),
        # `rest_seconds` is omitted in every row, and that omission IS the "no rest between
        # them" rule: the schema's own CHECK forbids a zero, so absence is how zero is written.
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=4, rest_between_sets_seconds=180, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=4, reps=4, rest_between_sets_seconds=150, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=4, rest_between_sets_seconds=120, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="bodyweight_anaerobic_circuit",
        name="Anaerobic bodyweight circuit",
        aspect_key="power_endurance",
        protocol_kind=ProtocolKind.CIRCUIT,
        # Every movement in the circuit is named, so every movement's contraindication is
        # listed: the push-ups are why `wrist` is here and the squat jumps are why `ankle`
        # is, and the library withholds those same two movements elsewhere for those flags.
        contraindication_keys=("lower_back", "wrist", "knee", "ankle"),
        instructions=(
            "Forty seconds of work and twenty of rest through squat jumps, push-ups, "
            "hollow holds and mountain climbers, then a long rest before the next round. "
            "It trains the same anaerobic system a pumped route does, which is what makes "
            "it worth doing on a week with no wall."
        ),
        substitution_hint=(
            "Add a packed backpack once bodyweight rounds stop leaving you breathing hard."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE,
                sets=3,
                work_seconds=40,
                rest_seconds=20,
                rest_between_sets_seconds=120,
                target_rpe=7,
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=5,
                work_seconds=40,
                rest_seconds=20,
                rest_between_sets_seconds=120,
                target_rpe=9,
            ),
            PrescriptionSpec(
                Phase.DELOAD,
                sets=2,
                work_seconds=30,
                rest_seconds=30,
                rest_between_sets_seconds=120,
                target_rpe=6,
            ),
        ),
    ),
    ExerciseSpec(
        key="up_down_boulder_laps",
        name="Up-down boulder laps",
        aspect_key="power_endurance",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Climb an easy boulder up, reverse it down, and keep going for the prescribed "
            "seconds — usually two or three laps — then rest about as long as you climbed. "
            "Downclimbing doubles the time on the wall for the same problem, which is what "
            "turns a boulder into an interval, and roughly thirty moves against a rest of "
            "about the same length is the shape that trains climbing while already pumped."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, work_seconds=60, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=6,
                work_seconds=90,
                rest_between_sets_seconds=90,
                target_rpe=8,
            ),
        ),
    ),
    ExerciseSpec(
        key="lead_route_doubles",
        name="Lead route doubles",
        aspect_key="power_endurance",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("lead_wall",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Lead a route, lower, and lead it again as soon as the rope is pulled — the "
            "second lap is the session. Choose something two or three grades under your "
            "limit, because the second lap on anything harder becomes a hang-and-rest "
            "exercise instead of a continuous one."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=4, reps=2, rest_between_sets_seconds=420, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=3, reps=2, rest_between_sets_seconds=420, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="outdoor_redpoint_burns",
        name="Outdoor redpoint burns",
        aspect_key="power_endurance",
        protocol_kind=ProtocolKind.INTERVALS,
        discipline=Discipline.SPORT,
        equipment_keys=("outdoor_routes",),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "Full-effort attempts on a route near your limit, with a real rest between "
            "them — long enough that the forearms are genuinely back, which outdoors "
            "usually means longer than it feels. Two good burns beat four tired ones, and "
            "the last one of the day is where most trips lose skin for nothing."
        ),
        substitution_hint="Nothing outdoors? Hard lead laps on a sustained indoor route.",
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=1, rest_between_sets_seconds=900, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=3, reps=1, rest_between_sets_seconds=1200, target_rpe=10
            ),
        ),
    ),
    ExerciseSpec(
        key="outdoor_boulder_circuit_laps",
        name="Outdoor circuit laps",
        aspect_key="power_endurance",
        protocol_kind=ProtocolKind.CIRCUIT,
        discipline=Discipline.BOULDER,
        equipment_keys=("outdoor_boulders",),
        contraindication_keys=("fingers", "elbow", "ankle"),
        instructions=(
            "Pick four or five moderate boulders close together and climb them one after "
            "another, walking between them and starting the next before the forearms clear. "
            "A circuit is how a boulderer gets a pumped session out of rock, and the walking "
            "between problems is the rest — do not sit down."
        ),
        substitution_hint="Nothing dry? The same circuit on moderate indoor problems.",
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=4, reps=5, rest_between_sets_seconds=300, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=3, reps=5, rest_between_sets_seconds=300, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=4, rest_between_sets_seconds=300, target_rpe=6
            ),
        ),
    ),
    # -------------------------------------------------------------------- endurance
    ExerciseSpec(
        key="arc_traversing",
        name="ARC traversing",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("elbow",),
        instructions=(
            "Traverse continuously on easy holds for the prescribed minutes, at an "
            "intensity you could hold a conversation at. One unbroken block is the "
            "exercise: twenty to forty minutes without stepping off is what the aerobic "
            "adaptation asks for, and breaking it into rounds with rests makes it a "
            "different session. A light forearm pump that never becomes a real one is the "
            "target; if you have to stop, drop the difficulty rather than the time."
        ),
        prescriptions=(
            # One continuous block, not rounds: the source band is 20-40 minutes unbroken,
            # and progression is more time or more difficulty rather than more rounds.
            PrescriptionSpec(Phase.BASE, sets=1, work_seconds=1800, target_rpe=4),
            PrescriptionSpec(Phase.DELOAD, sets=1, work_seconds=900, target_rpe=3),
            PrescriptionSpec(Phase.TAPER, sets=1, work_seconds=600, target_rpe=3),
        ),
    ),
    ExerciseSpec(
        key="long_easy_boulder_circuits",
        name="Long easy boulder circuits",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("elbow",),
        instructions=(
            "Climb easy problems back to back for the prescribed minutes, stepping off one "
            "and starting the next with barely a pause, at a grade you could keep going at "
            "for half an hour. It is the same aerobic block as ARC traversing and a "
            "different experience of it: traversing is one continuous line at one intensity, "
            "and this is whole problems, so the feet, the reading and the topping out all "
            "keep working. Drop the grade rather than the time if the forearms start to fill."
        ),
        substitution_hint=(
            "Not enough easy problems set? Traverse between them instead of walking."
        ),
        prescriptions=(
            PrescriptionSpec(Phase.BASE, sets=1, work_seconds=1800, target_rpe=4),
            PrescriptionSpec(Phase.DELOAD, sets=1, work_seconds=900, target_rpe=3),
        ),
    ),
    ExerciseSpec(
        key="continuous_rope_laps",
        name="Continuous rope laps",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("top_rope_wall",),
        contraindication_keys=("elbow",),
        instructions=(
            "Climb a route well within your grade, lower, and go straight back up "
            "without sitting down. Two or three laps make one set; the last lap should "
            "feel pumped but never desperate."
        ),
        # No hint on purpose. The honest alternatives are separate exercises the generator
        # can actually prescribe — `auto_belay_endurance_laps` when there is no partner,
        # `arc_traversing` when there is no rope — and `top_rope_wall` is a pre-hung rope,
        # so "no belayer?" was answering a question this requirement does not ask.
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=3, rest_between_sets_seconds=300, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=5, reps=3, rest_between_sets_seconds=240, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=3, rest_between_sets_seconds=240, target_rpe=7
            ),
        ),
    ),
    ExerciseSpec(
        key="aerobic_base_session",
        name="Aerobic base session",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.OTHER,
        contraindication_keys=("knee", "ankle"),
        instructions=(
            "Thirty to forty minutes of continuous easy work at a pace you could talk "
            "through. It is the aerobic floor everything else recovers on, it costs no "
            "skin and no gear, and it is the endurance session that still happens on a "
            "week with no access to a wall."
        ),
        substitution_hint=(
            "Anything continuous and conversational counts — a run, a hike, stairs or a bike."
        ),
        prescriptions=(
            PrescriptionSpec(Phase.BASE, sets=1, work_seconds=2400, target_rpe=4),
            # A short easy dose in the two heaviest blocks. Aerobic work at this intensity
            # is what the hard sessions recover on; leaving it out of `strength` and `power`
            # is how a cycle arrives at its endurance block with no base left.
            PrescriptionSpec(Phase.STRENGTH, sets=1, work_seconds=1800, target_rpe=4),
            PrescriptionSpec(Phase.POWER, sets=1, work_seconds=1500, target_rpe=3),
            PrescriptionSpec(Phase.TAPER, sets=1, work_seconds=1200, target_rpe=3),
        ),
    ),
    ExerciseSpec(
        key="auto_belay_endurance_laps",
        name="Auto belay endurance laps",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("auto_belay",),
        contraindication_keys=("elbow",),
        instructions=(
            "Easy laps on the same route, one after another, with the rest measured rather "
            "than negotiated. This is the endurance session that does not need a partner, "
            "so it is the one that actually happens on a weekday evening."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=3, rest_between_sets_seconds=240, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=5, reps=2, rest_between_sets_seconds=180, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=2, rest_between_sets_seconds=180, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=2, rest_between_sets_seconds=240, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=2, rest_between_sets_seconds=240, target_rpe=4
            ),
        ),
    ),
    ExerciseSpec(
        key="lead_endurance_pyramid",
        name="Lead endurance pyramid",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("lead_wall",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "Work up through easier routes to one near your onsight level and back down "
            "again, one lap each, resting only as long as it takes to pull the rope. The "
            "ladder down is the part that trains endurance; most people stop at the top and "
            "call it a session."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=5, reps=1, rest_between_sets_seconds=300, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=6, reps=1, rest_between_sets_seconds=240, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=1, rest_between_sets_seconds=300, target_rpe=7
            ),
        ),
    ),
    ExerciseSpec(
        key="outdoor_route_mileage",
        name="Outdoor route mileage",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("outdoor_routes",),
        contraindication_keys=("elbow",),
        instructions=(
            "A day of routes well inside your grade, as many as the light and the belayer "
            "allow. Rock rewards volume differently from a wall: the rests are real, the "
            "sequences are never the same twice, and route fitness built this way survives "
            "a week off far better than lap fitness does."
        ),
        substitution_hint="Nothing outdoors? Indoor rope laps train the same base.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=6, reps=1, rest_between_sets_seconds=600, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=1, rest_between_sets_seconds=600, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=3, reps=1, rest_between_sets_seconds=600, target_rpe=4
            ),
        ),
    ),
    ExerciseSpec(
        key="machine_zone_two_session",
        name="Machine aerobic session",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.OTHER,
        equipment_keys=("cardio_machine",),
        contraindication_keys=("knee", "lower_back"),
        instructions=(
            "Steady easy work on a bike, rower or treadmill at a pace you could talk "
            "through the whole way. It costs no skin and no fingers, so it is the aerobic "
            "session that fits beside a heavy climbing week rather than competing with it."
        ),
        substitution_hint="No machine? A run, a hike or a brisk walk does the same job.",
        prescriptions=(
            PrescriptionSpec(Phase.BASE, sets=1, work_seconds=2700, target_rpe=4),
            PrescriptionSpec(Phase.STRENGTH, sets=1, work_seconds=1800, target_rpe=4),
            PrescriptionSpec(Phase.POWER, sets=1, work_seconds=1500, target_rpe=3),
            PrescriptionSpec(Phase.DELOAD, sets=1, work_seconds=1800, target_rpe=3),
            PrescriptionSpec(Phase.TAPER, sets=1, work_seconds=1200, target_rpe=3),
        ),
    ),
    ExerciseSpec(
        key="top_rope_endurance_laps",
        name="Top rope endurance laps",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("top_rope_wall",),
        contraindication_keys=("elbow",),
        instructions=(
            "Laps on a pre-hung rope at a grade you could climb all evening, changing the "
            "route every set to keep the movement varied. Top rope takes the fear out of "
            "the equation, which is what lets the intensity stay genuinely low."
        ),
        regression_of_key="lead_endurance_pyramid",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=5, reps=2, rest_between_sets_seconds=240, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=5, reps=2, rest_between_sets_seconds=180, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=2, rest_between_sets_seconds=240, target_rpe=4
            ),
        ),
    ),
    ExerciseSpec(
        key="machine_recovery_spin",
        name="Recovery spin or row",
        aspect_key="endurance",
        protocol_kind=ProtocolKind.OTHER,
        equipment_keys=("cardio_machine",),
        contraindication_keys=("knee",),
        instructions=(
            "Fifteen to twenty easy minutes on a machine the day after a hard session, at an "
            "effort that feels like nothing. This is not training and is not meant to be: it "
            "moves blood through legs and back without asking the fingers or the shoulders "
            "for anything, which is why it belongs in the weeks where everything else is hard."
        ),
        substitution_hint="No machine? A flat easy walk does the same job.",
        regression_of_key="machine_zone_two_session",
        prescriptions=(
            PrescriptionSpec(Phase.STRENGTH, sets=1, work_seconds=1200, target_rpe=2),
            PrescriptionSpec(Phase.POWER, sets=1, work_seconds=1200, target_rpe=2),
            PrescriptionSpec(Phase.PERFORMANCE, sets=1, work_seconds=900, target_rpe=2),
            PrescriptionSpec(Phase.DELOAD, sets=1, work_seconds=1200, target_rpe=2),
            PrescriptionSpec(Phase.TAPER, sets=1, work_seconds=900, target_rpe=2),
        ),
    ),
    # -------------------------------------------------------------------- technique
    ExerciseSpec(
        key="silent_feet",
        name="Silent feet",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        instructions=(
            "Climb easy terrain placing every foot so quietly that nobody could hear it, "
            "looking at the foothold until the shoe is on it. Any audible slap or "
            "readjustment ends that lap — the point is precision, and it disappears the "
            "moment the climbing gets hard."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=2, rest_between_sets_seconds=120, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=2, rest_between_sets_seconds=120, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=2, rest_between_sets_seconds=120, target_rpe=3
            ),
        ),
    ),
    ExerciseSpec(
        key="system_board_repeats",
        name="System board repeats",
        aspect_key="technique",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("system_board",),
        contraindication_keys=("fingers", "shoulder"),
        instructions=(
            "Pick one steep problem and repeat it until the movement is identical every "
            "time — same feet, same rhythm, no readjustment. The board's symmetry is what "
            "makes a difference between your two sides obvious."
        ),
        substitution_hint=(
            "No board? One steep problem on the wall, repeated to the same standard, does "
            "the same job."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=1, rest_between_sets_seconds=180, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=6, reps=1, rest_between_sets_seconds=180, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=5, reps=1, rest_between_sets_seconds=240, target_rpe=9
            ),
        ),
    ),
    ExerciseSpec(
        key="movement_rehearsal_drills",
        name="Movement rehearsal drills",
        aspect_key="technique",
        protocol_kind=ProtocolKind.OTHER,
        instructions=(
            "Rehearse the shapes climbing asks for with no wall at all: deep step-throughs, "
            "hip turns onto a high foot, slow reaches from one leg, and holding each end "
            "position for a breath. Slow and deliberate — this is a coordination session, "
            "so it should never feel like conditioning."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, work_seconds=180, rest_between_sets_seconds=60, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=2, work_seconds=180, rest_between_sets_seconds=60, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.POWER, sets=2, work_seconds=180, rest_between_sets_seconds=60, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, work_seconds=180, rest_between_sets_seconds=60, target_rpe=2
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, work_seconds=120, rest_between_sets_seconds=60, target_rpe=2
            ),
        ),
    ),
    ExerciseSpec(
        key="downclimb_laps",
        name="Downclimb laps",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        instructions=(
            "Climb an easy problem and reverse it to the ground, matching the same holds on "
            "the way down. Downclimbing forces you to look at feet you cannot see and to "
            "move slowly under control, and it doubles the time on the wall for free."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=3, rest_between_sets_seconds=120, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=2, rest_between_sets_seconds=120, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=2, rest_between_sets_seconds=120, target_rpe=3
            ),
        ),
    ),
    ExerciseSpec(
        key="slab_and_smearing_drills",
        name="Slab and smearing drills",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        instructions=(
            "Easy slab and vertical ground with the worst feet you can find, weighting each "
            "smear until it holds before moving. Nobody trains this and everybody needs it: "
            "trusting a foot with no edge under it is a skill, not a strength."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=2, rest_between_sets_seconds=120, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=2, rest_between_sets_seconds=90, target_rpe=3
            ),
        ),
    ),
    ExerciseSpec(
        key="top_rope_technique_laps",
        name="Top rope technique laps",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("top_rope_wall",),
        instructions=(
            "Easy routes on a pre-hung rope, climbed with one thing to fix each lap — quiet "
            "feet, straight arms, or a breath at every rest. With the fall out of the way "
            "there is nothing left to think about except the movement."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=2, rest_between_sets_seconds=180, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=4, reps=2, rest_between_sets_seconds=150, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=1, rest_between_sets_seconds=180, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=1, rest_between_sets_seconds=180, target_rpe=3
            ),
        ),
    ),
    ExerciseSpec(
        key="onsight_volume_on_rope",
        name="Onsight volume on rope",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.SPORT,
        equipment_keys=("lead_wall",),
        contraindication_keys=("elbow",),
        instructions=(
            "Lead routes you have never touched, one lap each, reading each one from the "
            "ground and committing to the plan. Climbing well while pumped and unsure is "
            "its own skill, and it is the one a redpoint-only diet never trains."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=5, reps=1, rest_between_sets_seconds=300, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=5, reps=1, rest_between_sets_seconds=300, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=1, rest_between_sets_seconds=300, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="outdoor_boulder_mileage",
        name="Outdoor boulder mileage",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        discipline=Discipline.BOULDER,
        equipment_keys=("outdoor_boulders",),
        contraindication_keys=("fingers", "ankle"),
        instructions=(
            "A day of easy and moderate boulders on rock, as many different ones as the skin "
            "allows. Rock does not repeat itself, so an hour of mileage outdoors asks for "
            "more distinct movement than an evening of circuits ever will — and it is where "
            "reading a line stops being a wall skill."
        ),
        substitution_hint="Nothing dry to climb on? Volume on unfamiliar indoor problems.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=8, reps=1, rest_between_sets_seconds=180, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=6, reps=1, rest_between_sets_seconds=240, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=4, reps=1, rest_between_sets_seconds=240, target_rpe=4
            ),
        ),
    ),
    ExerciseSpec(
        key="deadpoint_drills",
        name="Deadpoint drills",
        aspect_key="technique",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder"),
        instructions=(
            "Practise arriving at a hold exactly at the top of the movement, when the body "
            "is weightless for an instant, on moves you can already do. Aim to catch the "
            "hold still rather than swinging into it: a deadpoint that lands early is a "
            "lock-off and one that lands late is a fall, and the timing is what improves."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=4, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=3, rest_between_sets_seconds=150, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.POWER, sets=5, reps=3, rest_between_sets_seconds=150, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=3, rest_between_sets_seconds=150, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="hip_positioning_drills",
        name="Hip positioning drills",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("hip", "knee"),
        instructions=(
            "Climb easy steep ground turning one hip into the wall on every move — drop "
            "knees, backsteps and flags, never square on. Getting the hips close is what "
            "makes a long reach short, and it is a decision rather than a strength, so it "
            "belongs on terrain easy enough to make the decision on."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=2, rest_between_sets_seconds=120, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=2, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=4, reps=2, rest_between_sets_seconds=120, target_rpe=7
            ),
        ),
    ),
    ExerciseSpec(
        key="no_hands_climbing_drill",
        name="No-hands climbing",
        aspect_key="technique",
        protocol_kind=ProtocolKind.LAPS,
        equipment_keys=("bouldering_wall",),
        instructions=(
            "Slab and vertical ground climbed with the hands touching nothing, or resting "
            "flat on the wall for balance only. It is the fastest way to find out how much "
            "of your climbing is arms: with them gone, the feet and the hips have to do the "
            "whole job and they will tell you immediately where the weight is."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=2, rest_between_sets_seconds=90, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=2, rest_between_sets_seconds=90, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, reps=2, rest_between_sets_seconds=90, target_rpe=3
            ),
        ),
    ),
    ExerciseSpec(
        key="board_flash_attempts",
        name="Board flash attempts",
        aspect_key="technique",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("system_board",),
        contraindication_keys=("fingers", "elbow", "shoulder"),
        instructions=(
            "Pick problems you have never touched at a grade you flash most of the time, "
            "read each one from the ground, and give it exactly one attempt before moving "
            "on. One try is the whole discipline: a board offers endless retries, and "
            "retrying is how reading a sequence stops being practised."
        ),
        substitution_hint="No board? Unfamiliar problems on a freshly reset wall.",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=6, reps=1, rest_between_sets_seconds=180, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=6, reps=1, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=5, reps=1, rest_between_sets_seconds=180, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="project_sequence_rehearsal",
        name="Project sequence rehearsal",
        aspect_key="technique",
        protocol_kind=ProtocolKind.OTHER,
        discipline=Discipline.SPORT,
        equipment_keys=("outdoor_routes",),
        contraindication_keys=("fingers", "elbow"),
        instructions=(
            "On a rope, go up a route you are working and rehearse the sequences slowly "
            "rather than trying to link them — every hand, every foot, every clipping "
            "position, twice each. The effort is low and the return is high, which is what "
            "makes it the right thing to do on a rest week or two days before a redpoint."
        ),
        substitution_hint="Nothing outdoors? The same rehearsal works on an indoor project.",
        prescriptions=(
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=2, rest_between_sets_seconds=600, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=1, rest_between_sets_seconds=600, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=1, rest_between_sets_seconds=600, target_rpe=4
            ),
        ),
    ),
    # ------------------------------------------------------------------ core_tension
    ExerciseSpec(
        key="front_lever_progression",
        name="Front lever progression",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.HOLD,
        equipment_keys=("pull_up_bar",),
        contraindication_keys=("shoulder", "lower_back", "elbow"),
        instructions=(
            "Hang with straight arms and lift the hips until the body is horizontal, "
            "choosing the hardest tuck you can hold with a flat lower back. Ribs down and "
            "arms locked straight; the set ends when the back arches, not when the timer does."
        ),
        substitution_hint="No bar? Hollow-body holds on the floor train the same tension.",
        # Authored in both directions on purpose: the two columns are independent, and
        # neither is inferred from the other. See `Exercise` in server/models.py.
        progression_of_key="hollow_body_hold",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, work_seconds=12, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=5, work_seconds=10, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=4, work_seconds=8, rest_between_sets_seconds=150, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, work_seconds=10, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, work_seconds=8, rest_between_sets_seconds=120, target_rpe=6
            ),
        ),
    ),
    ExerciseSpec(
        key="toes_to_bar",
        name="Toes to bar",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("pull_up_bar",),
        contraindication_keys=("lower_back", "shoulder"),
        instructions=(
            "Hang with active shoulders and bring the toes to the bar with control, then "
            "lower slowly rather than dropping. No swing: a kipped repetition trains the "
            "swing, not the tension."
        ),
        substitution_hint="No bar? Lying leg raises are the same movement without the hang.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=10, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=8, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=4, reps=12, rest_between_sets_seconds=90, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="hollow_body_hold",
        name="Hollow body hold",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.HOLD,
        contraindication_keys=("lower_back", "neck"),
        instructions=(
            "Lie on your back, press the lower back into the floor and lift the shoulders "
            "and legs into a shallow dish. The flat back is the exercise: keep the legs "
            "high enough that no gap opens under the spine, and raise them higher the "
            "moment one does. Lowering them towards the floor is what makes the hold "
            "harder, so only go there while the back stays down."
        ),
        regression_of_key="front_lever_progression",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, work_seconds=30, rest_between_sets_seconds=60, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, work_seconds=45, rest_between_sets_seconds=60, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=3, work_seconds=30, rest_between_sets_seconds=60, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, work_seconds=30, rest_between_sets_seconds=60, target_rpe=4
            ),
        ),
    ),
    ExerciseSpec(
        key="ring_rollouts_and_body_saw",
        name="Ring rollouts and body saw",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("gymnastic_rings",),
        contraindication_keys=("lower_back", "shoulder", "elbow"),
        instructions=(
            "From a forearm or straight-arm plank on low rings, let the hands travel out in "
            "front and pull them back without the hips dropping. Shorten the travel before "
            "you let the back arch — the range is negotiable, the flat back is not."
        ),
        substitution_hint="No rings? A hollow body hold trains the same tension in one position.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=10, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=8, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=12, rest_between_sets_seconds=90, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="weighted_hanging_knee_raises",
        name="Weighted hanging knee raises",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("pull_up_bar", "weight_belt"),
        contraindication_keys=("lower_back", "shoulder"),
        instructions=(
            "Hang with active shoulders and draw the knees above the hips against added "
            "load, lowering slowly and letting nothing swing. The load is what makes this "
            "different from the unweighted version — five controlled repetitions is the "
            "session, not fifteen fast ones."
        ),
        substitution_hint="No belt? A packed backpack worn front-to-back adds the same load.",
        progression_of_key="toes_to_bar",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=8, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=3, reps=6, rest_between_sets_seconds=150, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="weighted_suitcase_carries",
        name="Suitcase carries",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.HOLD,
        equipment_keys=("free_weights",),
        contraindication_keys=("lower_back", "shoulder", "wrist"),
        instructions=(
            "Walk with a heavy weight in one hand only, ribs stacked over the hips and the "
            "shoulders level, then swap sides. Resisting the sideways pull is what a heel "
            "hook and a drop knee ask the trunk for, and it costs the fingers nothing."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, work_seconds=45, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, work_seconds=40, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=3,
                work_seconds=40,
                rest_between_sets_seconds=120,
                target_rpe=7,
            ),
        ),
    ),
    ExerciseSpec(
        key="steep_wall_tension_drill",
        name="Steep wall tension drill",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "shoulder", "lower_back"),
        instructions=(
            "On the steepest ground you have, climb easy moves with the feet deliberately "
            "kept on: no cutting loose, no swinging, every foot placed and weighted before "
            "the next hand moves. Tension is what keeps the feet on, so losing them is the "
            "signal to stop the set."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=4, reps=2, rest_between_sets_seconds=120, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=2, rest_between_sets_seconds=150, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=3, reps=2, rest_between_sets_seconds=180, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="board_cut_loose_repeats",
        name="Board cut-loose repeats",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("system_board",),
        contraindication_keys=("fingers", "shoulder", "lower_back"),
        instructions=(
            "On a steep board, pull into a move, let the feet come off, and bring them back "
            "onto the same holds under control before finishing it. Catching your own feet "
            "again is the tension a steep boulder actually demands, and it is trainable."
        ),
        substitution_hint="No board? The same drill works on any steep problem with big holds.",
        prescriptions=(
            PrescriptionSpec(
                Phase.POWER, sets=5, reps=3, rest_between_sets_seconds=180, target_rpe=9
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=4, reps=3, rest_between_sets_seconds=180, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="heel_hook_tension_repeats",
        name="Heel hook tension repeats",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("bouldering_wall",),
        contraindication_keys=("fingers", "knee", "hip"),
        instructions=(
            "On steep ground, set a heel hook and pull through it to move the hips, "
            "repeating the same move on both sides. Build the tension gradually before "
            "loading it — a heel hook pulls hard on the hamstring behind the knee, and the "
            "injuries come from snatching into the position rather than from holding it."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=4, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=6, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=3, reps=4, rest_between_sets_seconds=120, target_rpe=7
            ),
        ),
    ),
    ExerciseSpec(
        key="banded_pallof_and_dead_bug",
        name="Pallof press and dead bug",
        aspect_key="core_tension",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("resistance_bands",),
        contraindication_keys=("lower_back", "shoulder"),
        instructions=(
            "Press a band away from the chest while it tries to rotate you, then lie down "
            "and lower one arm and the opposite leg with the back flat. Both are "
            "anti-movement work: the trunk's job on the wall is to refuse to twist when one "
            "hand is pulling and one foot is pushing, and nothing else in the library trains "
            "that directly."
        ),
        substitution_hint="No band? Hold a heavy pack off to one side and resist the pull.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=10, rest_between_sets_seconds=60, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=12, rest_between_sets_seconds=60, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=10, rest_between_sets_seconds=60, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=10, rest_between_sets_seconds=60, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=10, rest_between_sets_seconds=60, target_rpe=4
            ),
        ),
    ),
    # ------------------------------------------------------------- antagonist_prehab
    ExerciseSpec(
        key="reverse_wrist_curls",
        name="Reverse wrist curls",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("free_weights",),
        contraindication_keys=("wrist", "elbow"),
        instructions=(
            "Forearm resting on a thigh, palm down, curl the wrist up through its full "
            "range and lower slowly. Light and controlled: this is tendon work for the "
            "side of the forearm climbing never trains, not a strength lift."
        ),
        substitution_hint="No dumbbell? A packed backpack or a full bottle is load enough.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=15, rest_between_sets_seconds=60, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=12, rest_between_sets_seconds=60, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=15, rest_between_sets_seconds=60, target_rpe=5
            ),
        ),
    ),
    ExerciseSpec(
        key="band_external_rotation",
        name="Band external rotation",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("resistance_bands",),
        contraindication_keys=("shoulder",),
        instructions=(
            "Elbow at your side and bent to ninety degrees, rotate the forearm outward "
            "against the band and return slowly. Keep the elbow pinned — if it drifts "
            "forward, the band is too strong."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=15, rest_between_sets_seconds=60, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=12, rest_between_sets_seconds=60, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=15, rest_between_sets_seconds=45, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=12, rest_between_sets_seconds=45, target_rpe=4
            ),
        ),
    ),
    ExerciseSpec(
        key="push_ups_with_scapular_control",
        name="Push-ups with scapular control",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        contraindication_keys=("shoulder", "wrist"),
        instructions=(
            "Push-ups with the shoulder blades deliberately spread at the top and pulled "
            "together at the bottom, body in one line throughout. The pushing pattern "
            "climbing never trains, and it needs nothing but the floor."
        ),
        substitution_hint="Add a packed backpack once bodyweight sets stop being hard.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=12, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=10, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=15, rest_between_sets_seconds=60, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=10, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=10, rest_between_sets_seconds=90, target_rpe=5
            ),
        ),
    ),
    ExerciseSpec(
        key="ring_dips_and_push_ups",
        name="Ring dips and push-ups",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("gymnastic_rings",),
        contraindication_keys=("shoulder", "elbow", "wrist"),
        instructions=(
            "Support on the rings, press through a range the shoulders are comfortable in, "
            "and turn the rings out at the top. Start shallow: rings let the joint find its "
            "own path, which is the benefit and also how people go too deep on day one."
        ),
        substitution_hint="No rings? Push-ups with scapular control train the same pattern.",
        progression_of_key="push_ups_with_scapular_control",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=10, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=8, rest_between_sets_seconds=120, target_rpe=8
            ),
        ),
    ),
    ExerciseSpec(
        key="finger_extensor_band_work",
        name="Finger extensor band work",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("resistance_bands",),
        contraindication_keys=("wrist",),
        instructions=(
            "A band looped around the fingers, opening the hand fully against it and closing "
            "slowly. The extensors do nothing but resist everything the forearm does all "
            "session, and this is the cheapest insurance in the library — light load, high "
            "reps, most days of the week."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=20, rest_between_sets_seconds=45, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, reps=20, rest_between_sets_seconds=45, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=25, rest_between_sets_seconds=45, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=20, rest_between_sets_seconds=45, target_rpe=3
            ),
        ),
    ),
    ExerciseSpec(
        key="dumbbell_press_and_row",
        name="Overhead press and row",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("free_weights",),
        contraindication_keys=("shoulder", "elbow", "lower_back"),
        instructions=(
            "Press overhead and row to the hip, alternating, with the ribs down and the "
            "weight honest. Eight to twelve reps a set and both halves in the same block: "
            "this is the balance drill, not a strength lift. Climbing pulls down and in and "
            "never presses up, so overhead strength is the gap, and the row is here so the "
            "pressing does not become its own imbalance. The heavy low-rep row is a "
            "separate exercise under general strength."
        ),
        substitution_hint=(
            "No dumbbells? A packed backpack pressed overhead and rowed is load enough."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=12, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, reps=8, rest_between_sets_seconds=120, target_rpe=8
            ),
            PrescriptionSpec(
                Phase.POWER, sets=3, reps=8, rest_between_sets_seconds=120, target_rpe=7
            ),
        ),
    ),
    ExerciseSpec(
        key="band_pull_aparts_and_face_pulls",
        name="Band pull-aparts and face pulls",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("resistance_bands",),
        contraindication_keys=("shoulder",),
        instructions=(
            "Pull a band apart at chest height, then pull it towards the face with the "
            "elbows high, squeezing the shoulder blades together at the end of both. Light "
            "and frequent beats heavy and rare — this is the upper back holding the "
            "shoulders where climbing keeps dragging them forward from."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=15, rest_between_sets_seconds=45, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.POWER, sets=2, reps=15, rest_between_sets_seconds=45, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=15, rest_between_sets_seconds=45, target_rpe=4
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=12, rest_between_sets_seconds=45, target_rpe=3
            ),
        ),
    ),
    ExerciseSpec(
        key="overhead_carries_and_bottoms_up_holds",
        name="Overhead carries and bottoms-up holds",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.HOLD,
        equipment_keys=("free_weights",),
        contraindication_keys=("shoulder", "wrist", "lower_back"),
        instructions=(
            "Walk with a weight locked out overhead, then hold a dumbbell upside down at "
            "the shoulder and keep it from tipping. Both ask the shoulder to stabilise a "
            "load it cannot hang from, which is the opposite of everything climbing does to "
            "it — start lighter than feels worthwhile."
        ),
        substitution_hint="No dumbbell? A packed backpack held overhead by one strap.",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=4, work_seconds=40, rest_between_sets_seconds=90, target_rpe=7
            ),
            PrescriptionSpec(
                Phase.POWER, sets=3, work_seconds=40, rest_between_sets_seconds=90, target_rpe=6
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=2,
                work_seconds=30,
                rest_between_sets_seconds=90,
                target_rpe=5,
            ),
        ),
    ),
    ExerciseSpec(
        key="scapular_pull_ups_and_active_hangs",
        name="Scapular pull-ups and active hangs",
        aspect_key="antagonist_prehab",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("pull_up_bar",),
        contraindication_keys=("shoulder", "elbow"),
        instructions=(
            "Hang with straight arms and move only the shoulder blades, pulling the chest "
            "up an inch and letting it back down slowly, then finish with a long active "
            "hang. Tiny range, unglamorous, and the single cheapest thing a climber can do "
            "for a shoulder that has to hang all session."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=10, rest_between_sets_seconds=60, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=3, reps=10, rest_between_sets_seconds=60, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=8, rest_between_sets_seconds=60, target_rpe=3
            ),
        ),
    ),
    # --------------------------------------------------------------------- mobility
    ExerciseSpec(
        key="forearm_and_thoracic_rolling",
        name="Forearm and thoracic rolling",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.OTHER,
        equipment_keys=("foam_roller",),
        instructions=(
            "Roll the forearms and the upper back slowly, pausing on anything that feels "
            "tight and breathing there rather than grinding through it. Two or three "
            "minutes each, after climbing rather than before."
        ),
        substitution_hint=(
            "No roller? A rolling pin or a bottle does the forearms and a rolled mat does the back."
        ),
        prescriptions=(
            PrescriptionSpec(Phase.BASE, sets=2, work_seconds=240, target_rpe=2),
            # Soft-tissue work is not exempt from what a deload IS: this row used to
            # prescribe more of it than BASE did.
            PrescriptionSpec(Phase.DELOAD, sets=2, work_seconds=180, target_rpe=2),
            PrescriptionSpec(Phase.TAPER, sets=1, work_seconds=240, target_rpe=2),
        ),
    ),
    ExerciseSpec(
        key="hip_mobility_flow",
        name="Hip mobility flow",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.HOLD,
        contraindication_keys=("hip",),
        instructions=(
            "Move through deep squat, ninety-ninety rotations, a low lunge and a frog "
            "position, holding each for several breaths and loading the end range gently. "
            "High steps and drop knees come from here, and it needs no equipment at all."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=2, work_seconds=300, rest_between_sets_seconds=30, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, work_seconds=300, rest_between_sets_seconds=30, target_rpe=2
            ),
            PrescriptionSpec(Phase.TAPER, sets=1, work_seconds=300, target_rpe=2),
        ),
    ),
    ExerciseSpec(
        key="shoulder_band_arcs",
        name="Shoulder band arcs",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        equipment_keys=("resistance_bands",),
        contraindication_keys=("shoulder",),
        instructions=(
            "Hold a band wide with straight arms and trace it slowly overhead and behind "
            "you, as far as the shoulders allow without the ribs flaring. Widen the grip "
            "if the arc has to shorten."
        ),
        substitution_hint="No band? Hold a broom handle wide and trace the same arc.",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=3, reps=12, rest_between_sets_seconds=45, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, reps=12, rest_between_sets_seconds=45, target_rpe=2
            ),
            PrescriptionSpec(
                Phase.TAPER, sets=2, reps=10, rest_between_sets_seconds=45, target_rpe=2
            ),
        ),
    ),
    ExerciseSpec(
        key="banded_hip_and_hamstring_flow",
        name="Banded hip and hamstring flow",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.HOLD,
        equipment_keys=("resistance_bands",),
        contraindication_keys=("hip", "knee"),
        instructions=(
            "Use a band to add gentle traction to a deep lunge, a hamstring hold and a "
            "figure-four, breathing at the end of each range rather than bouncing. The band "
            "does the holding so the muscle can let go, which is the difference between a "
            "stretch that lasts and one that resets by the next session."
        ),
        substitution_hint="No band? The same positions work without traction, held longer.",
        progression_of_key="hip_mobility_flow",
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=2, work_seconds=300, rest_between_sets_seconds=30, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=2, work_seconds=240, rest_between_sets_seconds=30, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE,
                sets=2,
                work_seconds=240,
                rest_between_sets_seconds=30,
                target_rpe=2,
            ),
            PrescriptionSpec(
                Phase.DELOAD, sets=2, work_seconds=300, rest_between_sets_seconds=30, target_rpe=2
            ),
        ),
    ),
    ExerciseSpec(
        key="roller_thoracic_and_lat_release",
        name="Thoracic and lat release",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.OTHER,
        equipment_keys=("foam_roller",),
        contraindication_keys=("shoulder", "lower_back"),
        instructions=(
            "Lie back over the roller and open the upper back one segment at a time, then "
            "roll the side of the back under the armpit. Overhead reach comes from here, and "
            "a climber's lats are the first thing to shorten — after the session, not before "
            "a hard one."
        ),
        substitution_hint="No roller? A rolled mat under the upper back does most of it.",
        prescriptions=(
            PrescriptionSpec(Phase.STRENGTH, sets=2, work_seconds=240, target_rpe=2),
            PrescriptionSpec(Phase.POWER, sets=2, work_seconds=240, target_rpe=2),
            PrescriptionSpec(Phase.PERFORMANCE, sets=2, work_seconds=180, target_rpe=2),
            PrescriptionSpec(Phase.DELOAD, sets=2, work_seconds=240, target_rpe=2),
        ),
    ),
    ExerciseSpec(
        key="ankle_and_wrist_prep",
        name="Ankle and wrist preparation",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.STRAIGHT_SETS,
        contraindication_keys=("ankle", "wrist"),
        instructions=(
            "Kneeling wrist rotations and loaded palm-down and palm-up rocks, then ankle "
            "rocks driving the knee past the toes with the heel down. Two joints climbing "
            "loads hard and warms up never: the wrists take every mantel and the ankles take "
            "every drop off the wall."
        ),
        prescriptions=(
            PrescriptionSpec(
                Phase.BASE, sets=2, reps=15, rest_between_sets_seconds=30, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.STRENGTH, sets=2, reps=15, rest_between_sets_seconds=30, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.POWER, sets=2, reps=12, rest_between_sets_seconds=30, target_rpe=3
            ),
            PrescriptionSpec(
                Phase.POWER_ENDURANCE, sets=2, reps=12, rest_between_sets_seconds=30, target_rpe=2
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE, sets=2, reps=12, rest_between_sets_seconds=30, target_rpe=2
            ),
        ),
    ),
    ExerciseSpec(
        key="roller_hip_and_quad_release",
        name="Hip and quad release",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.OTHER,
        equipment_keys=("foam_roller",),
        contraindication_keys=("hip", "knee"),
        instructions=(
            "Roll the front of the thigh, the side of the hip and the glute, stopping on "
            "anything sharp and breathing until it eases. Hip flexors shorten from sitting "
            "and from every high step, and a tight one is what stops the hips getting close "
            "to the wall — this goes after climbing, not before."
        ),
        substitution_hint="No roller? A ball or a bottle finds the same spots.",
        prescriptions=(
            PrescriptionSpec(Phase.POWER, sets=2, work_seconds=240, target_rpe=2),
            PrescriptionSpec(Phase.POWER_ENDURANCE, sets=2, work_seconds=240, target_rpe=2),
            PrescriptionSpec(Phase.PERFORMANCE, sets=2, work_seconds=180, target_rpe=2),
            PrescriptionSpec(Phase.DELOAD, sets=2, work_seconds=240, target_rpe=2),
        ),
    ),
    ExerciseSpec(
        key="loaded_overhead_mobility_holds",
        name="Loaded overhead holds",
        aspect_key="mobility",
        protocol_kind=ProtocolKind.HOLD,
        equipment_keys=("free_weights",),
        contraindication_keys=("shoulder", "lower_back", "wrist"),
        instructions=(
            "Hold a light plate or dumbbell straight overhead with the ribs down and the "
            "arm beside the ear, and keep it there for the count. Range you cannot hold "
            "under load is range you do not own, and overhead is where a climber needs to "
            "own it — light enough that the position never breaks to reach the time."
        ),
        substitution_hint="No plate? A packed backpack held overhead does the same.",
        progression_of_key="shoulder_band_arcs",
        prescriptions=(
            PrescriptionSpec(
                Phase.STRENGTH, sets=3, work_seconds=45, rest_between_sets_seconds=60, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.POWER, sets=3, work_seconds=40, rest_between_sets_seconds=60, target_rpe=5
            ),
            PrescriptionSpec(
                Phase.PERFORMANCE,
                sets=2,
                work_seconds=40,
                rest_between_sets_seconds=60,
                target_rpe=4,
            ),
        ),
    ),
)

# The (phase, aspect) pairs the library deliberately leaves unprescribable. The guard test asserts
# the empty cells are EXACTLY these, so a hole opened by accident fails and an exemption for a cell
# somebody has since filled fails too. `ASPECT_EMPHASIS` is the other half of every row here.
DELIBERATELY_UNPRESCRIBED: Final[tuple[UnprescribedCell, ...]] = (
    UnprescribedCell(
        Phase.TAPER,
        "finger_strength",
        (
            "The fingers are the slowest tissue in the body to recover and the most "
            "expensive to overreach on, and a taper is one week from a peak. Sharpness "
            "comes from climbing on the target style in that week, not from a board, so "
            "the taper prescribes no isolated finger loading at all."
        ),
    ),
    UnprescribedCell(
        Phase.STRENGTH,
        "power_endurance",
        (
            "Power endurance is trained in its own block, and it comes back within a "
            "couple of weeks while maximum strength takes months — so the trade is "
            "one-sided."
        ),
    ),
    UnprescribedCell(
        Phase.POWER,
        "power_endurance",
        (
            "Same reason as the strength block: a power block's own attempts already "
            "cost more recovery than a pumped session would repay."
        ),
    ),
    UnprescribedCell(
        Phase.TAPER,
        "power_endurance",
        (
            "A full power-endurance session inside a taper week is the classic way to "
            "arrive at the trip flat: the pump comes back long before the freshness does. "
            "Note the contrast with `power` in the same phase, which IS prescribed — "
            "short maximal efforts with complete rest cost almost nothing to recover."
        ),
    ),
    UnprescribedCell(
        Phase.POWER_ENDURANCE,
        "general_strength",
        (
            "Strength is the quality that persists: it holds comfortably across the four "
            "weeks a power-endurance block lasts, so there is nothing to lose by "
            "leaving it out. A heavy hinge or squat inside these weeks competes for exactly "
            "the recovery the interval sessions need, and the trade is one-sided."
        ),
    ),
    UnprescribedCell(
        Phase.TAPER,
        "general_strength",
        (
            "Same reason, and the taper's own: nothing added in the last week can arrive in "
            "time, while a heavy leg session leaves fatigue that hides the fitness the whole "
            "plan built. Short maximal efforts stay because they cost almost nothing to "
            "recover from; a heavy strength session is not one of those."
        ),
    ),
    UnprescribedCell(
        Phase.PERFORMANCE,
        "anaerobic_capacity",
        (
            "Anaerobic capacity is dropped from four weeks out, and the performance block is "
            "always the final four weeks — so that rule covers all of it. It takes sixteen "
            "weeks or more to build and the weeks before the objective are for converting "
            "what is already there, not for the burn work that costs the most to recover."
        ),
    ),
    UnprescribedCell(
        Phase.TAPER,
        "anaerobic_capacity",
        (
            "The same four-week rule, at its sharpest end. This is the capacity work that "
            "leaves you pumped, and a taper's whole job is to arrive fresh — so it sits at "
            "the tail of the deload row alongside `power` and `power_endurance`, and out of "
            "the taper entirely."
        ),
    ),
)


# ⚠️ **Per-phase gearless coverage is NOT guaranteed, and this is the list of where it is
# missing.** Kilian's call, 2026-08-23: the expected user has climbing-gym access, so one or
# two no-equipment options per aspect is enough and the library spends its breadth on gear
# instead. That is a deliberate narrowing of the older promise, which was "a climber with no
# gear gets a real session out of every aspect" — that promise now holds per *aspect*
# (`tests/test_exercise_library.py` still enforces it) and not per *phase*.
#
# The consequence was owed to PR #11 and is now settled (Kilian, 2026-08-24, closing issue
# #61): **the generator generates, and names the shortfall.** In each cell below a climber
# who has ticked nothing has no candidate, so the slot is displaced to the next aspect in
# `ASPECT_EMPHASIS` that can be filled and the block carries a `Shortfall` listing the
# equipment rows that would have opened this one. It is never a refusal and never a gate.
# ⚠️ `tests/test_planner_gearless.py` asserts every cell below yields a shortfall with a
# non-empty `options`, so a cell added here without an unlocking requirement fails loudly.
#
# It is an inventory, not a floor: when it changes, update it. The guard test compares it
# with the library and fails either way round, which is what stops it going stale.
CELLS_WITH_NO_GEARLESS_OPTION: Final[tuple[tuple[Phase, str], ...]] = (
    (Phase.POWER, "finger_strength"),
    (Phase.POWER_ENDURANCE, "finger_strength"),
    (Phase.PERFORMANCE, "finger_strength"),
    (Phase.STRENGTH, "power"),
    (Phase.POWER_ENDURANCE, "power"),
    (Phase.DELOAD, "power"),
    (Phase.PERFORMANCE, "power_endurance"),
    (Phase.POWER_ENDURANCE, "endurance"),
    (Phase.PERFORMANCE, "endurance"),
    (Phase.DELOAD, "endurance"),
    (Phase.POWER_ENDURANCE, "technique"),
    (Phase.PERFORMANCE, "technique"),
    (Phase.POWER, "core_tension"),
    (Phase.POWER_ENDURANCE, "core_tension"),
    (Phase.PERFORMANCE, "core_tension"),
    (Phase.POWER, "antagonist_prehab"),
    (Phase.TAPER, "antagonist_prehab"),
)
