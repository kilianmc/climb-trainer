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

import pytest

from server.domain.exercises import (
    CELLS_WITH_NO_GEARLESS_OPTION,
    DELIBERATELY_UNPRESCRIBED,
    EXERCISES,
    FINGER_LOADING_EQUIPMENT_KEYS,
    ExerciseSpec,
    PrescriptionSpec,
)
from server.domain.planner.generate import _spec_seconds
from server.domain.planner.selection import candidates, on_the_wall
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
    Emptiness is allowed — a taper with no power-endurance work is periodisation, not an
    oversight — but only when it is written down with its reasoning.

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


# `explosive_move_intervals`' shipped instructions call it "the cheapest on-the-wall power work
# in the library in minutes". Measured 9.0 / 10.8 / 9.0 / 5.4 min in the four phases it is in.
CHEAPEST_ON_WALL_POWER_ROW = "explosive_move_intervals"


def test_the_ON_WALL_POWER_SUPERLATIVE_in_the_authored_copy_still_holds() -> None:
    """⚠️ GUARD. A superlative about the library's own contents, shipped to the reader: authoring
    one cheaper on-wall `power` row makes it lie silently. Only 0.8 min of margin at taper."""
    claimant = next(spec for spec in EXERCISES if spec.key == CHEAPEST_ON_WALL_POWER_ROW)
    for prescription in claimant.prescriptions:
        phase = prescription.phase
        mine = _spec_seconds(claimant, phase)
        for rival in on_the_wall(candidates(phase, claimant.aspect_key)):
            if rival.key == claimant.key:
                continue
            assert _spec_seconds(rival, phase) >= mine, (
                f"{claimant.key}'s instructions call it the cheapest on-the-wall "
                f"{claimant.aspect_key} work in the library, but in {phase.value} it costs "
                f"{mine / 60:.1f} min against {rival.key}'s {_spec_seconds(rival, phase) / 60:.1f}."
                f" Reword the instructions or re-dose one of the two — the copy is a claim."
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
