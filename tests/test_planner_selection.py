"""Equipment and injury filtering, the authored order, and the emphasis table's agreement.

DB-free.

Justified by CLAUDE.md's testing policy under **critical domain rules** — "plan generation
(… equipment/injury filtering)" is named there explicitly — and, for
`test_aspect_emphasis_agrees_with_the_library_in_both_directions`, under **project-wide
invariants that silently rot**: `ASPECT_EMPHASIS` is authored data about a library that is
edited independently of it, so nothing else in the gate can see the two drift apart.

Deliberately NOT written, and each for a reason:

- **No test that `prescribable()` returns the same tuple twice.** A pure filter over a
  module-level tuple is the language, not a behaviour. Determinism is tested where it can
  actually break: `tests/test_planner_reproducibility.py`, over a whole generated tree.
- **No test that "resolved injuries never reach the domain".** `PlannerInput` takes
  `open_injury_keys` and there is no other injury parameter anywhere in the package, so the
  claim is the type signature. The route that reads `user_injury` is R3's to test.
- **No assertion on `ASPECT_EMPHASIS`'s contents beyond that agreement.** Which quality
  leads a phase is a content decision; pinning it here would break on every retune and catch
  nothing.
"""

from datetime import date

import pytest

from server.domain.exercises import DELIBERATELY_UNPRESCRIBED, EXERCISES
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner.contract import PlannerInput
from server.domain.planner.generate import generate
from server.domain.planner.selection import ASPECT_EMPHASIS, candidates, prescribable
from server.domain.vocabulary import CLIMBING_ASPECTS, Phase

_ALL_EQUIPMENT = ("hangboard", "resistance_bands", "weight_belt")
# Everything the library asks for anywhere: the gym-access case, where nothing is filtered
# out for want of gear and the only filters left are discipline and injury.
_FULLY_EQUIPPED = tuple(sorted({key for spec in EXERCISES for key in spec.equipment_keys}))
_MONDAY = date(2026, 8, 24)


def test_candidates_are_exactly_the_exercises_prescribed_in_that_cell() -> None:
    """`prescription_template` is one row per (exercise, phase), so the phase filter is real.

    The positive control is the pair of cells: `finger_strength` has eight exercises in the
    library and eight of them are prescribed in `strength`, while the *same aspect* in
    `taper` has none — that emptiness is the phase filter doing its job, and it is the one
    thing a filter that only matched on `aspect_key` would get wrong.
    """
    trained = candidates(Phase.STRENGTH, "finger_strength")
    assert trained
    assert all(spec.aspect_key == "finger_strength" for spec in trained)
    assert all(
        any(prescription.phase is Phase.STRENGTH for prescription in spec.prescriptions)
        for spec in trained
    )
    assert candidates(Phase.TAPER, "finger_strength") == ()
    assert any(spec.aspect_key == "finger_strength" for spec in EXERCISES)


def test_equipment_is_an_and_set_and_no_equipment_always_passes() -> None:
    """Every row on an exercise is a requirement, so a subset of them is not enough.

    `weighted_max_hangs` needs a hangboard **and** a weight belt. A climber with only the
    hangboard must not be offered it — and the exercise that needs nothing must survive the
    empty set, which is the invariant standing in for the `bodyweight` row that deliberately
    does not exist.
    """
    cell = candidates(Phase.STRENGTH, "finger_strength")
    keys_with_belt = {
        spec.key
        for spec in prescribable(
            cell,
            discipline=Discipline.SPORT,
            equipment_keys=("hangboard", "weight_belt"),
            open_injury_keys=(),
        )
    }
    keys_without = {
        spec.key
        for spec in prescribable(
            cell,
            discipline=Discipline.SPORT,
            equipment_keys=("hangboard",),
            open_injury_keys=(),
        )
    }
    assert "weighted_max_hangs" in keys_with_belt
    assert "weighted_max_hangs" not in keys_without

    gearless = prescribable(
        cell, discipline=Discipline.SPORT, equipment_keys=(), open_injury_keys=()
    )
    assert [spec.key for spec in gearless] == ["self_resisted_finger_isometrics"]


def test_a_contraindicated_exercise_is_never_prescribed() -> None:
    """⚠️ Safety outranks filling a slot. One open flag withholds everything that names it."""
    cell = candidates(Phase.STRENGTH, "finger_strength")
    with_gear = prescribable(
        cell, discipline=Discipline.SPORT, equipment_keys=_ALL_EQUIPMENT, open_injury_keys=()
    )
    assert with_gear

    injured = prescribable(
        cell,
        discipline=Discipline.SPORT,
        equipment_keys=_ALL_EQUIPMENT,
        open_injury_keys=("fingers",),
    )
    assert injured == ()
    assert all("fingers" in spec.contraindication_keys for spec in with_gear)


def test_a_set_discipline_excludes_the_other_ladder_and_none_is_universal() -> None:
    """`None` means the exercise serves both; a set discipline means it serves only one."""
    cell = candidates(Phase.POWER, "power")
    for discipline in Discipline:
        offered = prescribable(
            cell,
            discipline=discipline,
            equipment_keys=("outdoor_boulders", "outdoor_routes"),
            open_injury_keys=(),
        )
        assert all(spec.discipline is None or spec.discipline is discipline for spec in offered)
    boulder_only = {
        spec.key
        for spec in prescribable(
            cell,
            discipline=Discipline.BOULDER,
            equipment_keys=("outdoor_boulders", "outdoor_routes"),
            open_injury_keys=(),
        )
    }
    assert "outdoor_boulder_projecting" in boulder_only
    assert "outdoor_route_crux_repeats" not in boulder_only


@pytest.mark.parametrize("aspect", [spec.key for spec in CLIMBING_ASPECTS])
def test_the_surviving_order_is_the_librarys_authored_order(aspect: str) -> None:
    """Filtering may only remove. The authoring IS the content decision — same argument as
    `/api/library`'s grouping — and selection reads the order, so a filter that reordered
    would silently change every plan."""
    authored = [spec.key for spec in EXERCISES]
    for phase in Phase:
        offered = prescribable(
            candidates(phase, aspect),
            discipline=Discipline.SPORT,
            equipment_keys=_FULLY_EQUIPPED,
            open_injury_keys=(),
        )
        positions = [authored.index(spec.key) for spec in offered]
        assert positions == sorted(positions)


def test_aspect_emphasis_agrees_with_the_library_in_both_directions() -> None:
    """⚠️ GUARD. The emphasis table and `DELIBERATELY_UNPRESCRIBED` are edited separately.

    Both directions, because a one-way check rots. An aspect listed for a phase the library
    declines to prescribe sends the displacement walk to a cell with no candidate under any
    circumstances — a shortfall nobody can act on. An aspect the library *does* prescribe but
    that is missing here is a content decision made by omission: that aspect silently
    disappears from that phase, in every plan, with nothing to read.

    `selection.py` raises this same disagreement at import. That is the mechanism; this is
    the thing that fails in a test run and names the cell.
    """
    unprescribed = {(cell.phase, cell.aspect_key) for cell in DELIBERATELY_UNPRESCRIBED}
    for phase in Phase:
        listed = set(ASPECT_EMPHASIS[phase])
        prescribed = {
            spec.key for spec in CLIMBING_ASPECTS if (phase, spec.key) not in unprescribed
        }
        assert listed == prescribed, (
            f"ASPECT_EMPHASIS[{phase.value}] and the library disagree. Prescribable but not "
            f"listed: {sorted(prescribed - listed)}; listed but deliberately unprescribed: "
            f"{sorted(listed - prescribed)}."
        )
    # The other direction of the same fact: every exempt cell really is absent.
    for phase, aspect in unprescribed:
        assert aspect not in ASPECT_EMPHASIS[phase]
        assert candidates(phase, aspect) == ()


def test_the_prescribed_exercise_rotates_from_week_to_week() -> None:
    """`(week_no - 1 + session_index)` is what stops week 1 and week 2 being the same session.

    Asserted through `generate()` rather than on the index arithmetic, because the arithmetic
    is one expression and what matters is that it reaches the output.
    """
    current = ordinal_of(GradeSystemKey.FRENCH, "6a")
    plan = generate(
        PlannerInput(
            discipline=Discipline.SPORT,
            current_ordinal=current,
            target_ordinal=current + 1,
            sessions_per_week=2,
            available_weekdays=0b0001001,
            strength_aspect_key="technique",
            weakness_aspect_key="finger_strength",
            open_injury_keys=(),
            equipment_keys=_FULLY_EQUIPPED,
            start_date=_MONDAY,
        )
    )
    base = plan.mesocycles[0].microcycles
    first_week = [block.exercise_key for block in base[0].sessions[0].blocks]
    second_week = [block.exercise_key for block in base[1].sessions[0].blocks]
    assert first_week != second_week
    first_session = [block.exercise_key for block in base[0].sessions[0].blocks]
    second_session = [block.exercise_key for block in base[0].sessions[1].blocks]
    assert first_session != second_session
