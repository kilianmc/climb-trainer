"""The guards the exercise library exists to keep, plus its contract integrity.

DB-free: it reads `server/domain/exercises.py`, so it runs in the local gate.

Under CLAUDE.md's testing policy these are **domain rules** and **project-wide invariants
that silently rot**, not a mirror of the content. There is deliberately no test asserting
that a particular exercise is called what it is called, or that a max hang is five sets:
that is content, a copy edit would break it, and it would catch nothing.

The ones that earn their place loudest:

1. **Coverage of the (phase, aspect) grid.** `prescription_template` is one row per
   (exercise, phase), so an exercise with no row for the phase being generated cannot be
   prescribed in it — which makes an empty cell a block the generator cannot fill. Every
   cell is either populated or named in `DELIBERATELY_UNPRESCRIBED` with its reasoning, and
   the test asserts the two sets are exactly equal in both directions.
2. **The finger-loading safety boundary.** No hangboard, campus or no-hang exercise may
   carry a substitution hint, and no hint may point at an improvised edge. The failure it
   prevents is not a broken build, it is a pulley injury. The matcher is word-boundary
   based and carries its own positive control, because the naive substring version found
   `"door"` inside `"outdoor"` and would have gone red on an honest hint.
3. **Every equipment row is reachable.** A vocabulary row no exercise requires is a
   checkbox that changes nothing, which is the dead end `outdoor_boulders` and
   `outdoor_routes` were added to fix in the first place.

The zero-equipment floor is **per aspect, not per phase** — see
`CELLS_WITH_NO_GEARLESS_OPTION` in the library module for the decision and for the list of
cells PR #11 has to handle by fallback.

Each was shown to fail before being trusted (CLAUDE.md, "A guard test must be SHOWN to
fail"): dropping `hip_mobility_flow`'s equipment-free status, adding a hint to
`max_hangs_20mm`, giving `hollow_body_hold` an equipment requirement, emptying the two
`foam_roller` requirements and deleting a row from `DELIBERATELY_UNPRESCRIBED` each turn
the relevant test red, naming the aspect, the exercise or the cell.
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
from server.domain.vocabulary import (
    CLIMBING_ASPECTS,
    EQUIPMENT,
    INJURY_AREAS,
    Phase,
    ProtocolKind,
)
from server.models import SUBSTITUTION_HINT_MAX

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
_IMPROVISED_EDGE_STEMS = (
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
_IMPROVISED_EDGE_RE = re.compile(r"\b(?:" + "|".join(_IMPROVISED_EDGE_STEMS) + ")", re.IGNORECASE)


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


def _candidates(phase: Phase, aspect_key: str) -> list[ExerciseSpec]:
    """Everything the generator could prescribe in one cell of the (phase, aspect) grid."""
    return [
        spec
        for spec in EXERCISES
        if spec.aspect_key == aspect_key
        and any(prescription.phase is phase for prescription in spec.prescriptions)
    ]


def test_every_phase_and_aspect_pair_is_prescribable_or_deliberately_not() -> None:
    """The coverage contract: no silent holes in the 56-cell grid.

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
        if not _candidates(phase, spec.key)
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
        if (candidates := _candidates(phase, spec.key))
        and not any(not candidate.equipment_keys for candidate in candidates)
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
        if spec.substitution_hint is not None and _IMPROVISED_EDGE_RE.search(spec.substitution_hint)
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
        assert not _IMPROVISED_EDGE_RE.search(safe), f"false positive on {safe!r}"
    for unsafe in (
        "No hangboard? A door frame works at the same depth.",
        "Hang from a ceiling joist or an exposed beam.",
        "A towel over a bar gives the same grip.",
        "Improvise a rung from a broom handle.",
        "Any edge or ledge around the house will do.",
        "A home-made hangboard costs nothing.",
    ):
        assert _IMPROVISED_EDGE_RE.search(unsafe), f"missed {unsafe!r}"


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
