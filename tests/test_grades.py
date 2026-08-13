"""The grade ordinal ladder.

Squarely inside the "WRITE tests for" list in CLAUDE.md: this is critical domain logic
whose failure mode is *silent*. A mis-seated rung does not raise — it produces a plan
for the wrong grade, a send pyramid with a bar in the wrong column, and a "grade gap"
that quietly generates twelve weeks of the wrong training. None of that shows up as an
exception, which is exactly why the invariants are asserted rather than inspected.

No database involved: `server.domain.grades` is pure by design.
"""

import pytest

from server.domain.grades import (
    GRADE_SYSTEMS,
    GRADES,
    CrossDisciplineError,
    Discipline,
    GradeSystemKey,
    NoEquivalentGradeError,
    UnknownGradeError,
    convert,
    grades_for,
    label_at,
    ordinal_of,
    systems_for,
)

_SYSTEM_KEYS = tuple(spec.key for spec in GRADE_SYSTEMS)


@pytest.mark.parametrize("key", _SYSTEM_KEYS)
def test_a_systems_ordinals_strictly_ascend_in_ladder_order(key: GradeSystemKey) -> None:
    """Monotonicity. If this fails, every comparison in the app is wrong."""
    ordinals = [grade.ordinal for grade in grades_for(key)]
    assert ordinals == sorted(ordinals)
    assert len(set(ordinals)) == len(ordinals)


@pytest.mark.parametrize("key", _SYSTEM_KEYS)
def test_labels_are_unique_within_a_system(key: GradeSystemKey) -> None:
    labels = [grade.label for grade in grades_for(key)]
    assert len(set(labels)) == len(labels)


@pytest.mark.parametrize("discipline", list(Discipline))
def test_ordinals_are_contiguous_within_a_discipline(discipline: Discipline) -> None:
    """What makes `target_ordinal - current_ordinal` a usable grade gap.

    A hole in the band would make the gap overstate the number of grades to climb, and
    the plan generator turns that number directly into weeks of training.
    """
    keys = {spec.key for spec in systems_for(discipline)}
    ordinals = sorted({g.ordinal for g in GRADES if g.system in keys})
    assert ordinals == list(range(ordinals[0], ordinals[0] + len(ordinals)))


def test_boulder_and_sport_bands_do_not_overlap() -> None:
    """Cross-discipline comparison must be absurd, not subtly plausible."""
    boulder_keys = {spec.key for spec in systems_for(Discipline.BOULDER)}
    sport_keys = {spec.key for spec in systems_for(Discipline.SPORT)}
    boulder = {g.ordinal for g in GRADES if g.system in boulder_keys}
    sport = {g.ordinal for g in GRADES if g.system in sport_keys}
    assert boulder.isdisjoint(sport)
    assert max(boulder) < min(sport)


def test_label_and_ordinal_round_trip_for_every_grade() -> None:
    """Every seeded grade survives label -> ordinal -> label."""
    for grade in GRADES:
        assert label_at(grade.system, ordinal_of(grade.system, grade.label)) == grade.label
        assert ordinal_of(grade.system, grade.label) == grade.ordinal


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (GradeSystemKey.FONT, GradeSystemKey.V_SCALE),
        (GradeSystemKey.V_SCALE, GradeSystemKey.FONT),
        (GradeSystemKey.FRENCH, GradeSystemKey.YDS),
        (GradeSystemKey.YDS, GradeSystemKey.FRENCH),
    ],
)
def test_conversion_round_trips_wherever_an_equivalent_exists(
    source: GradeSystemKey, target: GradeSystemKey
) -> None:
    converted_any = False
    for grade in grades_for(source):
        try:
            other = convert(grade.label, from_system=source, to_system=target)
        except NoEquivalentGradeError:
            continue  # A rung the target scale does not split. Expected, not a failure.
        converted_any = True
        assert convert(other, from_system=target, to_system=source) == grade.label
    assert converted_any, "the two scales share no rung at all — the ladder is broken"


@pytest.mark.parametrize(
    ("source", "label", "target", "expected"),
    [
        # Anchors from the published conversion tables. These pin the ladder in place:
        # inserting or deleting a rung shifts everything above it, and only fixed
        # reference points catch that.
        (GradeSystemKey.FONT, "6C", GradeSystemKey.V_SCALE, "V5"),
        (GradeSystemKey.FONT, "7A", GradeSystemKey.V_SCALE, "V6"),
        (GradeSystemKey.FONT, "8A", GradeSystemKey.V_SCALE, "V11"),
        (GradeSystemKey.V_SCALE, "V10", GradeSystemKey.FONT, "7C+"),
        (GradeSystemKey.FRENCH, "6c+", GradeSystemKey.YDS, "5.11b"),
        (GradeSystemKey.FRENCH, "7a", GradeSystemKey.YDS, "5.11d"),
        (GradeSystemKey.FRENCH, "9a", GradeSystemKey.YDS, "5.14d"),
        (GradeSystemKey.YDS, "5.12a", GradeSystemKey.FRENCH, "7a+"),
    ],
)
def test_known_cross_scale_anchors(
    source: GradeSystemKey, label: str, target: GradeSystemKey, expected: str
) -> None:
    assert convert(label, from_system=source, to_system=target) == expected


def test_font_and_french_lookalike_labels_are_different_grades() -> None:
    """Case is the ONLY thing separating Font `7A` from French `7a`.

    Which is why nothing in this module case-folds. A lenient lookup here would map a
    boulder grade onto a rope ladder without complaining.
    """
    assert ordinal_of(GradeSystemKey.FONT, "7A") != ordinal_of(GradeSystemKey.FRENCH, "7a")
    with pytest.raises(UnknownGradeError):
        ordinal_of(GradeSystemKey.FONT, "7a")
    with pytest.raises(UnknownGradeError):
        ordinal_of(GradeSystemKey.FRENCH, "7A")


def test_cross_discipline_conversion_is_refused() -> None:
    """Boulder <-> rope is not a fact we have; it must not be guessed."""
    with pytest.raises(CrossDisciplineError):
        convert("7A", from_system=GradeSystemKey.FONT, to_system=GradeSystemKey.FRENCH)
    with pytest.raises(CrossDisciplineError):
        convert("5.12a", from_system=GradeSystemKey.YDS, to_system=GradeSystemKey.V_SCALE)


def test_unlabelled_rung_raises_instead_of_rounding_to_a_neighbour() -> None:
    """Silently rounding would be a plausible-looking lie about the user's grade."""
    # Font splits 6B+ where the V-scale does not.
    with pytest.raises(NoEquivalentGradeError):
        convert("6B+", from_system=GradeSystemKey.FONT, to_system=GradeSystemKey.V_SCALE)
    # YDS splits 5.11c where French does not.
    with pytest.raises(NoEquivalentGradeError):
        convert("5.11c", from_system=GradeSystemKey.YDS, to_system=GradeSystemKey.FRENCH)


def test_invalid_input_raises_unknown_not_no_equivalent() -> None:
    """The two error types mean different things and callers branch on them."""
    with pytest.raises(UnknownGradeError):
        ordinal_of(GradeSystemKey.V_SCALE, "V99")
    with pytest.raises(UnknownGradeError):
        ordinal_of(GradeSystemKey.FONT, "")
    with pytest.raises(UnknownGradeError):
        label_at(GradeSystemKey.FONT, 0)
    with pytest.raises(UnknownGradeError):
        label_at(GradeSystemKey.FONT, 999_999)


def test_v_scale_covers_vb_through_v17_with_no_gaps() -> None:
    """The scale users actually pick from in the UI — a missing rung is a missing option."""
    labels = [grade.label for grade in grades_for(GradeSystemKey.V_SCALE)]
    assert labels == ["VB", *[f"V{n}" for n in range(18)]]
