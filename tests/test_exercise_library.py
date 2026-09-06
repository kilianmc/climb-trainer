"""The guards the exercise library exists to keep, plus its contract integrity.

DB-free: it reads `server/domain/exercises.py`, so it runs in the local gate. These are domain
rules and silently-rotting invariants, not a mirror of the content — nothing here asserts an
exercise's name or set count, which a copy edit would break and which would catch nothing.

The grid: every (phase, aspect) cell is either populated or named in
`DELIBERATELY_UNPRESCRIBED`, asserted equal in **both** directions, because an empty cell is a
block the generator cannot fill. It uses the GENERATOR's own `candidates()` — a private copy
would keep passing after the generator's filter changed. The finger-loading safety boundary
prevents a pulley injury, not a broken build, and its matcher is word-boundary based with a
positive control (the naive substring version found "door" inside "outdoor"). Every equipment
row must be reachable, or it is a checkbox that changes nothing.

⚠️ **Deleting a row from `DELIBERATELY_UNPRESCRIBED` no longer reaches a test here.**
`selection.py::_validate_aspect_emphasis()` raises at import, and `tests/conftest.py` imports
`server.app`, so it aborts conftest import and therefore the whole suite. Louder and a truer
diagnosis, but it is not this file going red; that function's message points here for that
reason.
"""

import re
from collections import Counter
from dataclasses import dataclass

import pytest

from server.domain.exercises import (
    CELLS_WITH_NO_GEARLESS_OPTION,
    DELIBERATELY_UNPRESCRIBED,
    EXERCISES,
    FINGER_LOADING_EQUIPMENT_KEYS,
    OPEN_CLIMBING_KEYS,
    ExerciseSpec,
    PrescriptionSpec,
)
from server.domain.planner.generate import _spec_seconds
from server.domain.planner.selection import ASPECT_NAMES, candidates, on_the_wall
from server.domain.vocabulary import (
    CLIMBING_ASPECTS,
    EQUIPMENT,
    INJURY_AREAS,
    Phase,
    ProtocolKind,
)
from server.models import SUBSTITUTION_HINT_MAX

# ⚠️ PUBLIC because `tests/test_planner_gearless.py` imports it: a shortfall message is the
# other place an improvised-edge suggestion could appear, and the two must be checked by the
# SAME matcher. A second copy there would drift, and the copy that drifts is the one that
# stops catching things.
#
# Word STEMS that only appear in a hint if someone is suggesting an improvised edge. Matched
# against `substitution_hint` **only**, and not against `instructions`: the no-equipment
# finger option names a door frame and a towel precisely in order to rule them out, and a
# match cannot tell a prohibition from a suggestion. The hint field is where a suggestion
# would actually live, which is what makes the narrow scope the right one.
#
# ⚠️ Matched on a **word boundary**, and that is not a refinement. As a plain substring,
# `"door"` sits inside `"outdoor"` and `"indoor"`, so the library's honest outdoor hints
# ("Nothing outdoors? Indoor rope laps train the same base.") would have failed a safety
# test — and the tempting fix is to delete the entry, which is the one change that must
# never be made here. A leading `\b` with no trailing one keeps `doorway`, `doors`,
# `improvised`, `edges` and `rungs` caught.
IMPROVISED_EDGE_STEMS = (
    "door",
    "towel",
    "improvis",
    "home-made",
    "homemade",
    "diy",
    "ledge",
    "edge",
    "frame",
    "beam",
    "rung",
    "joist",
)
IMPROVISED_EDGE_RE = re.compile(r"\b(?:" + "|".join(IMPROVISED_EDGE_STEMS) + ")", re.IGNORECASE)


def test_every_aspect_has_an_exercise_that_needs_no_equipment() -> None:
    """The zero-equipment floor, at the strength it is actually promised at: per ASPECT.

    An exercise with no `exercise_equipment` rows requires nothing and is always
    prescribable, which is what replaces the `bodyweight` equipment row that deliberately
    does not exist (CLAUDE.md). Note `outdoor_boulders` and `outdoor_routes` ARE equipment
    rows, so "go climbing on rock" does not satisfy this: the floor is met by the body alone.

    ⚠️ This does **not** promise a gearless option in every *phase*, and must not be
    reworded as if it did — see `CELLS_WITH_NO_GEARLESS_OPTION` for the decision and the
    seventeen cells where a gearless user has nothing.
    """
    aspects_with_a_floor = {spec.aspect_key for spec in EXERCISES if not spec.equipment_keys}
    missing = sorted(spec.key for spec in CLIMBING_ASPECTS if spec.key not in aspects_with_a_floor)
    assert not missing, (
        f"these aspects have no exercise at all that requires zero equipment: {missing}. "
        f"There is no `bodyweight` equipment row on purpose, so an exercise with no "
        f"`exercise_equipment` rows is the ONLY way a climber with no gear meets an aspect "
        f"anywhere in their plan. Add one to server/domain/exercises.py."
    )


def test_every_phase_and_aspect_pair_is_prescribable_or_deliberately_not() -> None:
    """The coverage contract: no silent holes in the 70-cell grid.

    An exercise with no `prescription_template` row for a phase cannot be prescribed in that
    phase, so a cell with no candidate is a block the generator cannot fill for that aspect.
    Emptiness is allowed — a strength block with no power-endurance work is periodisation,
    not an oversight — but only when it is written down with its reasoning.

    Asserted in **both** directions, because a one-way assertion rots: an exemption for a
    cell somebody has since filled is a stale claim about the library, and the next reader
    would trust it.
    """
    exempt = {(cell.phase, cell.aspect_key) for cell in DELIBERATELY_UNPRESCRIBED}
    empty = {
        (phase, spec.key)
        for spec in CLIMBING_ASPECTS
        for phase in Phase
        if not candidates(phase, spec.key)
    }
    undocumented = sorted((phase.value, aspect) for phase, aspect in empty - exempt)
    assert not undocumented, (
        f"these (phase, aspect) cells have no exercise at all: {undocumented}. The generator "
        f"cannot fill that aspect in that phase. Either author an exercise prescribed in the "
        f"phase, or add an `UnprescribedCell` to DELIBERATELY_UNPRESCRIBED saying why the "
        f"emptiness is correct."
    )
    stale = sorted((phase.value, aspect) for phase, aspect in exempt - empty)
    assert not stale, (
        f"DELIBERATELY_UNPRESCRIBED still exempts cells that now have exercises: {stale}. "
        f"Delete those rows — the reasoning on them is no longer what the library does."
    )


def test_the_gearless_gap_inventory_matches_the_library() -> None:
    """`CELLS_WITH_NO_GEARLESS_OPTION` is an inventory, and a stale one is worse than none.

    It is what PR #11 reads to know where it must fall back, or refuse and name the missing
    equipment (issue #61), rather than emit an empty session. So it
    is compared with the library in both directions: a cell that quietly loses its last
    no-equipment candidate has to appear here, and one that gains an option has to leave.
    """
    computed = {
        (phase, spec.key)
        for spec in CLIMBING_ASPECTS
        for phase in Phase
        if (cell := candidates(phase, spec.key))
        and not any(not candidate.equipment_keys for candidate in cell)
    }
    recorded = set(CELLS_WITH_NO_GEARLESS_OPTION)
    assert computed == recorded, (
        "CELLS_WITH_NO_GEARLESS_OPTION no longer matches the library. Missing from the "
        f"list: {sorted((p.value, a) for p, a in computed - recorded)}; listed but no longer "
        f"true: {sorted((p.value, a) for p, a in recorded - computed)}. It is an inventory "
        "PR #11 depends on, not a floor — update the tuple in server/domain/exercises.py."
    )


def test_every_equipment_row_is_used_by_at_least_one_exercise() -> None:
    """An equipment row no exercise requires is a checkbox that changes nothing.

    Worse than dead weight, because `equipment_keys` is an AND set: a user whose whole
    practice is the unused row gets a candidate pool that ignores them entirely. That is the
    exact dead end `outdoor_boulders` and `outdoor_routes` were added to the vocabulary to
    fix (Kilian, 2026-08-21), and it reappears one layer down the moment the library has no
    exercise on the far side of a row.
    """
    required = {key for spec in EXERCISES for key in spec.equipment_keys}
    unused = [spec.key for spec in EQUIPMENT if spec.key not in required]
    assert not unused, (
        f"no exercise requires these equipment rows: {unused}. Either author one that does, "
        f"or delete the row from server/domain/vocabulary.py — an option the plan generator "
        f"can never act on is worse than an absent one."
    )


def test_no_finger_loading_exercise_offers_a_substitution() -> None:
    """⚠️ SAFETY. A real edge or nothing — never an improvised one.

    Every substitute for a hangboard, a campus board or a no-hang device is something
    rigged at home, and improvised finger loading is the most injury-prone thing a climber
    can do. Finger protocols are left out of a plan rather than downgraded.
    """
    offenders = {
        spec.key: spec.substitution_hint
        for spec in EXERCISES
        if spec.substitution_hint is not None
        and set(spec.equipment_keys) & FINGER_LOADING_EQUIPMENT_KEYS
    }
    assert not offenders, (
        f"finger-loading exercises must carry NO substitution hint: {offenders}. A hint "
        f"here can only point at a home-made hangboard, a door frame or a towel hang. "
        f"Delete the hint; the exercise is dropped from the plan instead."
    )


def test_no_substitution_hint_suggests_improvising_an_edge() -> None:
    """⚠️ SAFETY, the other direction: a hint on a NON-finger exercise saying it anyway.

    Improvised *load* is fine and the library uses it — a packed backpack, a bottle, a
    broom handle. Improvised *edges* are not, wherever the hint sits.
    """
    offenders = {
        spec.key: spec.substitution_hint
        for spec in EXERCISES
        if spec.substitution_hint is not None and IMPROVISED_EDGE_RE.search(spec.substitution_hint)
    }
    assert not offenders, (
        f"these substitution hints read as improvised finger loading: {offenders}. Adding "
        f"weight with whatever is to hand is fine; hanging from whatever is to hand is not."
    )


def test_the_improvised_edge_matcher_reads_words_not_substrings() -> None:
    """The positive control for the matcher above, in both directions.

    The negative arm passes on an empty set, so without this a matcher that had been
    weakened to nothing would look identical to a clean library. The false-positive arm is
    just as load-bearing: `"door"` inside `"outdoor"` is what would push someone into
    deleting the entry rather than fixing the match.
    """
    for safe in (
        "Nothing outdoors? Indoor rope laps train the same base.",
        "No dumbbell? A packed backpack or a full bottle is load enough.",
        "No band? Hold a broom handle wide and trace the same arc.",
    ):
        assert not IMPROVISED_EDGE_RE.search(safe), f"false positive on {safe!r}"
    for unsafe in (
        "No hangboard? A door frame works at the same depth.",
        "Hang from a ceiling joist or an exposed beam.",
        "A towel over a bar gives the same grip.",
        "Improvise a rung from a broom handle.",
        "Any edge or ledge around the house will do.",
        "A home-made hangboard costs nothing.",
    ):
        assert IMPROVISED_EDGE_RE.search(unsafe), f"missed {unsafe!r}"


def test_keys_are_unique() -> None:
    """`key` is the data contract the seed upserts on.

    A duplicate is not a cosmetic problem: `ON CONFLICT DO UPDATE` cannot touch the same
    row twice in one statement, so the content seed would abort mid-transaction.
    """
    duplicates = sorted(
        key for key, count in Counter(s.key for s in EXERCISES).items() if count > 1
    )
    assert not duplicates, f"duplicate exercise keys: {duplicates}"


def test_every_referenced_vocabulary_key_exists() -> None:
    """The `__post_init__` check, asserted rather than assumed.

    `ExerciseSpec` validates its keys at import, so this can only fail if that validation
    is removed — which is exactly the change worth catching, because the symptom without it
    is a seed run that dies partway through a production transaction.
    """
    aspects = {spec.key for spec in CLIMBING_ASPECTS}
    equipment = {spec.key for spec in EQUIPMENT}
    injuries = {spec.key for spec in INJURY_AREAS}
    for spec in EXERCISES:
        assert spec.aspect_key in aspects, f"{spec.key}: unknown aspect {spec.aspect_key}"
        assert not set(spec.equipment_keys) - equipment, f"{spec.key}: unknown equipment"
        assert not set(spec.contraindication_keys) - injuries, f"{spec.key}: unknown injury area"


def test_an_unknown_key_is_refused_at_import_time() -> None:
    """The positive control for the check above: a typo must not be constructible."""
    with pytest.raises(ValueError, match="not a equipment key"):
        ExerciseSpec(
            key="typo",
            name="Typo",
            aspect_key="mobility",
            protocol_kind=ProtocolKind.OTHER,
            instructions="x",
            prescriptions=(PrescriptionSpec(Phase.BASE, sets=1),),
            equipment_keys=("hangbaord",),
        )


def test_every_exercise_is_prescribed_in_at_least_one_phase() -> None:
    """An exercise with no `prescription_template` row can never be prescribed.

    It would be seeded, returned by the API, and silently unusable by the generator.
    """
    unprescribed = sorted(spec.key for spec in EXERCISES if not spec.prescriptions)
    assert not unprescribed, f"no prescription template for: {unprescribed}"


def test_a_phase_is_prescribed_at_most_once_per_exercise() -> None:
    """Mirrors `UNIQUE (exercise_id, phase)` — caught here, not by an IntegrityError."""
    for spec in EXERCISES:
        phases = [prescription.phase for prescription in spec.prescriptions]
        duplicates = sorted(phase for phase, count in Counter(phases).items() if count > 1)
        assert not duplicates, f"{spec.key} prescribes {duplicates} twice"


def test_prescription_values_satisfy_the_database_checks() -> None:
    """The three CHECKs on `prescription_template`, in a pure test.

    They exist in the database as the last line of defence; catching a violation here
    means a bad prescription is a red local gate rather than an IntegrityError halfway
    through a production seed run.
    """
    for spec in EXERCISES:
        for prescription in spec.prescriptions:
            where = f"{spec.key}/{prescription.phase.value}"
            assert prescription.sets >= 1, f"{where}: sets_positive"
            assert prescription.intensity_pct is None or 1 <= prescription.intensity_pct <= 200, (
                f"{where}: intensity_pct_sane"
            )
            assert prescription.target_rpe is None or 1 <= prescription.target_rpe <= 10, (
                f"{where}: target_rpe_in_range"
            )
            # SMALLINT, and every one of these is a duration or a count.
            for field, value in (
                ("reps", prescription.reps),
                ("work_seconds", prescription.work_seconds),
                ("rest_seconds", prescription.rest_seconds),
                ("rest_between_sets_seconds", prescription.rest_between_sets_seconds),
            ):
                assert value is None or 1 <= value <= 32767, f"{where}: {field} = {value}"


def test_boulder_four_by_four_prescribes_NO_REST_BETWEEN_THE_BOULDERS() -> None:
    """⚠️ GUARD. "No rest between them" IS the 4x4 and only an ABSENCE can say it: the column's
    CHECK is `1 <= rest_seconds`, so zero is inexpressible and omission is how it is written."""
    row = next(spec for spec in EXERCISES if spec.key == "boulder_four_by_four")
    filled = [
        (prescription.phase.value, prescription.rest_seconds)
        for prescription in row.prescriptions
        if prescription.rest_seconds is not None
    ]
    assert not filled, (
        f"boulder_four_by_four prescribes a rest between the boulders in {filled}. Its "
        f"instructions say the four go 'back to back with no rest between them', and because "
        f"the column's CHECK is 1 <= rest_seconds an ABSENT value is the only way to write "
        f"the zero that rule means. Put the rest in rest_between_sets_seconds instead."
    )


# §7's Aero Cap row is "sustained light pump, never fail" and `CLIMBING_ASPECTS`' own endurance
# copy is "a submaximal intensity", so 6 is the ceiling both allow (ruling 39, 2026-09-06).
AEROBIC_CAPACITY_RPE_CEILING = 6

# The four aspects §7's dose table covers, through the aspect <-> attribute mapping: Aero Cap,
# Aero Pow, An Cap and An Pow. The other five aspects are Strength or have no §7 row at all.
SECTION_7_ASPECTS = frozenset({"endurance", "power_endurance", "anaerobic_capacity", "power"})


def test_no_ENDURANCE_row_is_DOSED_OVER_THE_AEROBIC_CAPACITY_RPE_CEILING() -> None:
    """⚠️ GUARD, ruling 39. F19: four `endurance` rows shipped at RPE 7-8 against §7's "never
    fail", and the aspect's own user-facing copy promises submaximal. Aspect-wide, so a new row
    cannot reintroduce it in a cell the boulder-reachability guard's dose arm does not reach."""
    over = [
        (spec.key, prescription.phase.value, prescription.target_rpe)
        for spec in EXERCISES
        if spec.aspect_key == "endurance"
        for prescription in spec.prescriptions
        if prescription.target_rpe is not None
        and prescription.target_rpe > AEROBIC_CAPACITY_RPE_CEILING
    ]
    assert not over, (
        f"{over} dose `endurance` above RPE {AEROBIC_CAPACITY_RPE_CEILING}. §7 doses aerobic "
        f"capacity as a sustained light pump that never reaches failure, and the aspect ships "
        f"to the client as 'staying on the wall for minutes at a submaximal intensity' — an "
        f"RPE 7 row makes that copy false. Re-dose the row, or file it under the aspect whose "
        f"dose it actually is; do not raise this ceiling."
    )


@dataclass(frozen=True, slots=True)
class _DoseShape:
    """One (aspect, protocol kind) the library authors, with §7's rest:work window for it or
    `None` where the sources dose that shape by something other than a ratio."""

    aspect_key: str
    kind: ProtocolKind
    band: tuple[float, float] | None
    source: str


# §7's dose table and §5's protocol list, as one register. Keyed on `protocol_kind` and never on
# `aspect_key` alone (ruling 43) — the measurement is in the guard's docstring below.
SECTION_7_SHAPES: tuple[_DoseShape, ...] = (
    _DoseShape(
        "anaerobic_capacity",
        ProtocolKind.INTERVALS,
        (2.0, 4.0),
        "§7 An Cap: rest 2-4x the work. §5.2 progresses it by harder or longer circuits and "
        "names a shorter rest as the thing not to do, so the 2x floor is the load-bearing edge.",
    ),
    _DoseShape(
        "anaerobic_capacity",
        ProtocolKind.CIRCUIT,
        (2.0, 4.0),
        "The same window, and §5.2 doses this shape by name: 'long boulders 12-15 moves, rest "
        "fixed at 2-4x climb time'.",
    ),
    _DoseShape(
        "power_endurance",
        ProtocolKind.INTERVALS,
        (1.0, 2.0),
        "§7 Aero Pow: rest about equal to the work, 1-2x. §5.3's on-the-minute is the shape — "
        "a 6-8 move boulder, ~20 s climbing against 40 s of rest.",
    ),
    _DoseShape(
        "power_endurance",
        ProtocolKind.LAPS,
        (1.0, 2.0),
        "The same Aero Pow window: a timed lap with a measured rest is on-the-minute over a "
        "longer climb, and `up_down_boulder_laps`' instructions state the 1x shape themselves.",
    ),
    _DoseShape(
        "power_endurance",
        ProtocolKind.CIRCUIT,
        None,
        "⚠️ OUT OF SCOPE. §5.3 doses the Aero Pow circuit by MOVES and shakeouts — '~30-move "
        "circuits, no shakeouts, don't exceed 30' — and gives no rest figure, where §5.2's An "
        "Cap circuit carries one by name. F25 is the declared divergence this leaves standing.",
    ),
    _DoseShape(
        "power",
        ProtocolKind.INTERVALS,
        None,
        "⚠️ OUT OF SCOPE. `power` is An Pow AND alactic max-effort work, which no source doses: "
        "the two exercises here are one 6 s / 48 s alactic burst, correct at 8x, and F18's "
        "declared divergence. An Pow's own §7 row is a within-set rest and the shape that "
        "matches it, `short_rest_boulder_sets`, carries no `work_seconds` to read.",
    ),
    _DoseShape(
        "power",
        ProtocolKind.CIRCUIT,
        None,
        "⚠️ OUT OF SCOPE. §5.4 doses the An Pow broken circuit and the redpoint circuit by "
        "sections and attempts, not by a ratio. F26 registers `broken_circuit_redpoint` at "
        "4.67-12.00x and this guard does not close it.",
    ),
    _DoseShape(
        "endurance",
        ProtocolKind.LAPS,
        None,
        "⚠️ OUT OF SCOPE. §7 gives Aero Cap no rest period at all — the column reads 'n/a' — so "
        "its dose is 10+ min of work and a ratio is not the claim. `long_boulder_link_ups`' "
        "300 s against that floor is ruling 45's declared divergence, recorded at the row.",
    ),
    _DoseShape(
        "endurance",
        ProtocolKind.OTHER,
        None,
        "The same Aero Cap 'n/a', and nothing to read either way: these eleven rows are "
        "continuous machine and mileage sessions and not one of them carries a rest field.",
    ),
)

# Measured 2026-09-06 over the readable set: 24 rows, and a within-set-only reading left all 24
# unreadable, so the guard below would have been vacuous rather than strict.
SECTION_7_DOSED_ROWS = 24


def _operative_rest(prescription: PrescriptionSpec) -> int | None:
    """The LONGER of the two rest fields. The library writes an interval's rest in whichever one
    fits the shape, and ruling 44 reads the longer of the two as the operative one."""
    rests = [
        seconds
        for seconds in (prescription.rest_seconds, prescription.rest_between_sets_seconds)
        if seconds is not None
    ]
    return max(rests, default=None)


def _section_7_dose_rows() -> list[tuple[ExerciseSpec, PrescriptionSpec, int]]:
    """The readable set: rows in the four §7 aspects carrying `work_seconds`, less the filler.
    The work seconds come out with the row, because a ratio is the only thing anything wants."""
    return [
        (spec, prescription, prescription.work_seconds)
        for spec in EXERCISES
        if spec.aspect_key in SECTION_7_ASPECTS and spec.key not in OPEN_CLIMBING_KEYS
        for prescription in spec.prescriptions
        if prescription.work_seconds is not None
    ]


def test_every_DOSED_row_sits_inside_its_SECTION_7_REST_TO_WORK_BAND() -> None:
    """⚠️ GUARD, ruling 43. A dose row's rest:work ratio must sit inside the band §7 gives for
    the KIND of protocol it is; a kind the sources do not dose by a ratio is out of scope and
    `SECTION_7_SHAPES` says which and why. There is NO exemption register (ruling 34): the four
    rows that would have needed one are declared divergences recorded at the rows themselves.

    Scope, measured 2026-09-06: 136 rows sit in the four §7 aspects, 60 carry `work_seconds`,
    6 of those are `OPEN_CLIMBING_KEYS` — exempt BY NAME, since ruling 29 gives the filler no
    dose progression — leaving 54 readable and 24 in a banded shape.
    ⚠️ Keying the band on `aspect_key` alone was measured and refused: under an An Pow <=1x read
    on `aspect_key == "power"`, 10 of 10 `power` rows carrying `work_seconds` breach, including
    `explosive_move_intervals` at 6 s / 48 s = 8.00x, which is correct alactic dosing.
    ⚠️ THE BLIND SPOT: only a row with `work_seconds` has a readable ratio, and
    `short_rest_boulder_sets` — the one An Pow row the audit certifies as matching §7 exactly,
    20 s rest inside a set against 480-600 s between them — has none. What is readable in
    `power` is therefore biased toward the rows that are wrong.
    """
    bands = {(shape.aspect_key, shape.kind): shape for shape in SECTION_7_SHAPES if shape.band}
    inspected = 0
    for spec, prescription, work in _section_7_dose_rows():
        shape = bands.get((spec.aspect_key, spec.protocol_kind))
        if shape is None:
            continue
        assert shape.band is not None
        inspected += 1
        where = f"{spec.key}/{prescription.phase.value}"
        rest = _operative_rest(prescription)
        assert rest is not None, (
            f"{where} is a dosed {spec.aspect_key} {spec.protocol_kind.value} row with "
            f"{work} s of work and no rest at all. {shape.source}"
        )
        ratio = rest / work
        low, high = shape.band
        assert low <= ratio <= high, (
            f"{where} rests {rest} s against {work} s of work = "
            f"{ratio:.2f}x, outside §7's {low}-{high}x for a {spec.aspect_key} "
            f"{spec.protocol_kind.value}. {shape.source} Re-dose the row, or file it under the "
            f"aspect whose dose it actually is — there is no exemption register here."
        )
    assert inspected >= SECTION_7_DOSED_ROWS, (
        f"the band arm read {inspected} rows against the {SECTION_7_DOSED_ROWS} measured, so it "
        f"has quietly narrowed. A guard nobody's rows reach is the failure mode this number "
        f"exists to catch — a within-set-only reading of the rest scored 0 of 24."
    )


def test_the_SECTION_7_SHAPE_REGISTER_names_every_shape_the_library_actually_HAS() -> None:
    """⚠️ GUARD, both directions, on the idiom of `DELIBERATELY_UNPRESCRIBED`. An unnamed shape
    is a row no band reads — an authored `endurance` INTERVALS row would pass unchecked — and a
    named shape the library no longer carries is a stale exemption."""
    present = {(spec.aspect_key, spec.protocol_kind) for spec, _, _ in _section_7_dose_rows()}
    named = {(shape.aspect_key, shape.kind) for shape in SECTION_7_SHAPES}
    assert present == named, (
        f"unnamed in SECTION_7_SHAPES: {sorted((a, k.value) for a, k in present - named)}; "
        f"named but no longer in the library: "
        f"{sorted((a, k.value) for a, k in named - present)}. Every (aspect, protocol kind) "
        f"the four §7 aspects author with `work_seconds` needs a row there — with a band if the "
        f"sources dose that shape by a ratio, and with the reason they do not if they don't."
    )


# `CLIMBING_ASPECTS["power_endurance"]`'s published sentence, verbatim. Pinned rather than
# paraphrased, so a reword arrives at the arms its own number is derived from.
POWER_ENDURANCE_COPY = (
    "Making hard moves while already pumped — around thirty of them, on rests at "
    "least as long as the work."
)
# "on rests at least as long as the work": the FLOOR the sentence puts under rest, as a multiple
# of the work. Two arms read it — one per row, one on the tightest row the aspect ships.
COPY_CLAIMS_REST_TO_WORK_FLOOR = 1.0
# Measured 2026-09-06: `power_endurance` authors 21 prescriptions, 12 carry no `work_seconds` and
# 1 is the open-climbing filler, leaving 8 rows a rest:work ratio can be read from.
POWER_ENDURANCE_DOSED_ROWS = 8


def _power_endurance_dose_rows() -> list[tuple[ExerciseSpec, PrescriptionSpec, int]]:
    """The aspect's readable set, on `_section_7_dose_rows()`' own filtering and exemptions."""
    return [row for row in _section_7_dose_rows() if row[0].aspect_key == "power_endurance"]


def test_the_ASPECT_COPYS_REST_TO_WORK_FLOOR_is_TRUE_OF_EVERY_DOSED_ROW() -> None:
    """⚠️ GUARD on `CLIMBING_ASPECTS["power_endurance"]`, the sentence a climber reads
    when they rate this aspect. Per `(exercise, phase)` ROW, never pooled and never per aspect:
    an aspect-wide mean sits inside the claim while the row in front of them breaks it.

    Denominator: 8 of the aspect's 21 prescriptions. 12 carry no `work_seconds`, so no ratio can
    be read from them at all, and `open_climbing_power_endurance` is exempt by name (ruling 34).
    Rest is the LONGER of the two fields, which is ruling 44's reading.

    ⚠️ The sentence claimed rests "no longer than the work" until 2026-09-06 and 6 of
    these 8 rows broke it — 1.50x, 2.00x and four at 3.00-4.00x. It is NOT re-authored to
    §7's 1-2x Aero Pow band either: `bodyweight_anaerobic_circuit` is filed here at
    3.00-4.00x and ruling 44 keeps that filing, so a 1-2x sentence would move the mismatch
    rather than end it. The floor is the one edge the whole shipped set supports.
    """
    aspect = next(spec for spec in CLIMBING_ASPECTS if spec.key == "power_endurance")
    assert aspect.description == POWER_ENDURANCE_COPY, (
        f"the published power_endurance sentence now reads {aspect.description!r}. Its rest "
        f"claim is what the arms below assert — re-derive them against the library here, or "
        f"the reword ships a number nothing checks."
    )
    ratios: dict[str, float] = {}
    for spec, prescription, work in _power_endurance_dose_rows():
        where = f"{spec.key}/{prescription.phase.value}"
        rest = _operative_rest(prescription)
        assert rest is not None, (
            f"{where} is a dosed power_endurance row with {work} s of work and no rest at all, "
            f"so the sentence's floor cannot be read of it. Dose the rest, or drop the claim."
        )
        ratios[where] = rest / work
        assert ratios[where] >= COPY_CLAIMS_REST_TO_WORK_FLOOR, (
            f"{where} rests {rest} s against {work} s of work = {ratios[where]:.2f}x, under the "
            f"{COPY_CLAIMS_REST_TO_WORK_FLOOR:.1f}x the published sentence promises the climber. "
            f"Reword the copy or re-dose the row — never leave the sentence standing."
        )
    assert len(ratios) == POWER_ENDURANCE_DOSED_ROWS, (
        f"the floor arm read {len(ratios)} rows against the {POWER_ENDURANCE_DOSED_ROWS} "
        f"measured, so the readable set has moved. A row that stopped carrying `work_seconds` "
        f"leaves the sentence unchecked over it rather than failing."
    )
    tightest = min(ratios, key=lambda where: ratios[where])
    assert ratios[tightest] == COPY_CLAIMS_REST_TO_WORK_FLOOR, (
        f"the shortest rest in the aspect is now {ratios[tightest]:.2f}x the work "
        f"({tightest}), so telling the climber the rests are at least as long as the work "
        f"understates what they are given and the copy owes the stronger claim. Reword the "
        f"sentence — never loosen this arm."
    )


# `explosive_move_intervals`' shipped instructions call it "the cheapest on-the-wall power work
# in the library in minutes". Measured 9.0 / 10.8 / 9.0 / 5.4 min in the four phases it is in.
CHEAPEST_ON_WALL_POWER_ROW = "explosive_move_intervals"

# #117 gives the loading weeks of a block three different doses, so a superlative about the
# library's own contents is three claims and the copy ships all three.
LOADING_WEEKS_OF_A_BLOCK = (1, 2, 3)


def test_the_ON_WALL_POWER_SUPERLATIVE_in_the_authored_copy_still_holds() -> None:
    """⚠️ GUARD. A superlative about the library's own contents, shipped to the reader: authoring
    one cheaper on-wall `power` row makes it lie silently. Only 0.8 min of margin at taper."""
    claimant = next(spec for spec in EXERCISES if spec.key == CHEAPEST_ON_WALL_POWER_ROW)
    for prescription in claimant.prescriptions:
        phase = prescription.phase
        for week_no in LOADING_WEEKS_OF_A_BLOCK:
            mine = _spec_seconds(claimant, phase, week_no)
            for rival in on_the_wall(candidates(phase, claimant.aspect_key)):
                if rival.key == claimant.key:
                    continue
                theirs = _spec_seconds(rival, phase, week_no)
                assert theirs >= mine, (
                    f"{claimant.key}'s instructions call it the cheapest on-the-wall "
                    f"{claimant.aspect_key} work in the library, but in {phase.value} week "
                    f"{week_no} it costs {mine / 60:.1f} min against {rival.key}'s "
                    f"{theirs / 60:.1f}. Reword the instructions or re-dose one of the two — "
                    f"the copy is a claim, and #117's progression moves both sides of it."
                )


def test_authored_strings_fit_their_columns() -> None:
    """A too-long string is an `IntegrityError` at seed time, i.e. in production.

    The columns are `exercise.name` String(96), `instructions` String(2000) and
    `substitution_hint` String(SUBSTITUTION_HINT_MAX).
    """
    for spec in EXERCISES:
        assert len(spec.name) <= 96, f"{spec.key}: name is {len(spec.name)} characters"
        assert len(spec.instructions) <= 2000, f"{spec.key}: instructions too long"
        if spec.substitution_hint is not None:
            assert len(spec.substitution_hint) <= SUBSTITUTION_HINT_MAX, (
                f"{spec.key}: substitution_hint is {len(spec.substitution_hint)} characters"
            )


def test_progression_links_name_a_real_exercise() -> None:
    """A dangling link renders as an empty "easier version" in a browse UI.

    The two columns are independent and each direction is authored separately, so a
    rename has to be followed in both — which is what this catches.
    """
    keys = {spec.key for spec in EXERCISES}
    for spec in EXERCISES:
        for field, target in (
            ("progression_of_key", spec.progression_of_key),
            ("regression_of_key", spec.regression_of_key),
        ):
            assert target is None or target in keys, f"{spec.key}.{field} -> unknown {target!r}"


def test_no_progression_link_points_at_itself() -> None:
    """The cheapest cycle there is, and the one a copy-pasted spec creates."""
    for spec in EXERCISES:
        assert spec.progression_of_key != spec.key, f"{spec.key} is a progression of itself"
        assert spec.regression_of_key != spec.key, f"{spec.key} is a regression of itself"


# Ruling 30's first invariant, Kilian 2026-09-06: "add what is the intention on the block, so if
# it was power endurance, we can say, focus on boulders that test your power-endurance the most."
# ⚠️ MEMBERSHIP ALONE WOULD PROVE NOTHING HERE: "power endurance" contains "power", so a `power`
# filler whose cue only ever said "power endurance" would read green. Every OTHER aspect name is
# deleted from the text first, longest first, and only where it is not part of the row's own name.
def _cue_names_its_own_quality(text: str, aspect_key: str) -> bool:
    """Whether this cue names the quality the block it fills is FOR, and not a rival's name."""
    own = ASPECT_NAMES[aspect_key].lower()
    residue = text.lower()
    others = sorted(
        (name.lower() for key, name in ASPECT_NAMES.items() if key != aspect_key),
        key=len,
        reverse=True,
    )
    for other in others:
        if other not in own:
            residue = residue.replace(other, " ")
    return own in residue


def test_every_OPEN_CLIMBING_row_TELLS_THE_CLIMBER_WHAT_THE_BLOCK_IS_FOR() -> None:
    """⚠️ GUARD, ruling 30. The filler is the largest single item in a session and it is the one
    block with no protocol, so its own text is the only place the block's intention can be said.

    Also asserts the two shapes ruling 29 gives the family, both of which are the reason it is a
    FILLER and not a prescription: no dose progression (`intensity_pct` is never set, and every
    phase gets the same one authored chunk, which `generate.py::_place` re-sizes to the gap), and
    a bouldering wall and nothing else, so it is never gated behind rope gear the way the
    `endurance` rows prescribable in POWER_ENDURANCE are.
    """
    family = [spec for spec in EXERCISES if spec.key in OPEN_CLIMBING_KEYS]
    assert len(family) == len(OPEN_CLIMBING_KEYS), (
        f"OPEN_CLIMBING_KEYS names {len(OPEN_CLIMBING_KEYS)} rows and "
        f"{len(family)} were found; the import-time check in exercises.py should have fired."
    )
    for spec in family:
        assert _cue_names_its_own_quality(spec.instructions, spec.aspect_key), (
            f"{spec.key} fills a block it says is about "
            f"{ASPECT_NAMES[spec.aspect_key]!r} and its own text never names that quality. "
            f"The climber reads this block and nothing else about why they are climbing: "
            f"{spec.instructions!r}"
        )
        assert spec.equipment_keys == ("bouldering_wall",), (
            f"{spec.key} requires {spec.equipment_keys}. Ruling 29's filler has to be reachable "
            f"by both disciplines in a plain bouldering gym; rope gear is what makes the "
            f"POWER_ENDURANCE aerobic rows unreachable for half the profiles."
        )
        assert spec.discipline is None, f"{spec.key} is filed under {spec.discipline}."
        doses = {
            (row.sets, row.work_seconds, row.reps, row.intensity_pct) for row in spec.prescriptions
        }
        assert len(doses) == 1 and doses.pop()[2:] == (None, None), (
            f"{spec.key} carries more than one dose across its phases, or an intensity anchor: "
            f"{sorted((r.phase.value, r.sets, r.work_seconds) for r in spec.prescriptions)}. "
            f"Open climbing is TIME ON THE WALL and not a protocol, which is why it has no "
            f"progression to be week 3 of — the generator sizes the one chunk to the gap."
        )
