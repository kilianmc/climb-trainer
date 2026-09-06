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
from server.domain.planner.selection import (
    ASPECT_EMPHASIS,
    MAX_WALL_TURNS,
    candidates,
    open_climbing_fill,
    prescribable,
    wall_aspect_turns,
    wall_led_aspects,
)
from server.domain.vocabulary import CLIMBING_ASPECTS, Phase

_ALL_EQUIPMENT = ("hangboard", "resistance_bands", "weight_belt")
# Everything the library asks for anywhere: the gym-access case, where nothing is filtered
# out for want of gear and the only filters left are discipline and injury.
_FULLY_EQUIPPED = tuple(sorted({key for spec in EXERCISES for key in spec.equipment_keys}))
_MONDAY = date(2026, 8, 24)


def test_candidates_are_exactly_the_exercises_prescribed_in_that_cell() -> None:
    """`prescription_template` is one row per (exercise, phase), so the phase filter is real.

    The positive control is the pair of cells: `finger_strength` has twelve exercises in the
    library and eight prescribed in `strength`, while the *same aspect* in `taper` has none —
    Kilian's injury call, declared, and not the sources' doctrine. That emptiness is the phase
    filter doing its job, the one thing a filter matching only `aspect_key` would get wrong.
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

    The first loop can never be the red: `conftest.py` imports `server.app`, so `selection.py`'s
    import-time validator aborts COLLECTION. Kept only to name the cell a reader would look for.
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


# F11 / ruling 38's DECLARED DIVERGENCE, as the numbers that declare it. `MAX_WALL_TURNS` caps a
# wall-led aspect's turns at 4, which flattens the head of the authored order, and the cap STAYS:
# seven readings were measured (cap 5, 6, 8, uncapped, dense, dense doubled, and proportional at
# today's exact ring length) and every one turns a shipped ruling's guard red. `selection.py`'s
# `wall_aspect_turns` docstring is the register of which ruling each reading breaks.
#
# ⚠️ Restated as LITERALS, on `test_the_expandability_table_cannot_widen_without_a_decision`'s
# idiom, and both directions are asserted: a reordered `ASPECT_EMPHASIS` row, a lifted cap or a
# new on-wall row in a flat phase all move these, and each of those is a training decision.
_MAX_WALL_TURNS = 4
_PAIRS_AT_THE_WALL_TURN_CAP = 21
_WALL_LED_PAIRS = 30
# Ruling 41's `endurance` row is why this is two and not the three F11 was filed against: it
# gives `power` an aspect with rank 3, so that phase's ring stopped being flat when the row landed.
_PHASES_WITH_A_FLAT_RING = ("strength", "taper")


def test_the_WALL_TURN_CAP_FLATTENS_EXACTLY_THESE_PAIRS_AND_THESE_PHASES() -> None:
    """⚠️ GUARD, F11 / ruling 38 as a declared divergence. The cap is not a bug to be fixed
    silently and not a number to be lifted casually: it decides which qualities a 2-3 session
    week gets at all, because such a week visits only six of a 16-long ring's rotations.

    Both directions. A pair leaving the cap, a phase becoming flat or a phase ceasing to be flat
    is a change to what a phase IS, and this arm makes each of them arrive as a decision.
    """
    assert MAX_WALL_TURNS == _MAX_WALL_TURNS, (
        f"MAX_WALL_TURNS is {MAX_WALL_TURNS}, not {_MAX_WALL_TURNS}. Seven readings were "
        f"measured against this number and only this one has a green suite — see "
        f"selection.py::wall_aspect_turns for which ruling each of the other six breaks."
    )
    at_cap: list[str] = []
    pairs = 0
    flat: list[str] = []
    for phase in Phase:
        aspects = wall_led_aspects(phase)
        row = ASPECT_EMPHASIS[phase]
        pairs += len(aspects)
        at_cap += [
            f"{phase.value}/{key}"
            for key in aspects
            if len(row) - row.index(key) >= _MAX_WALL_TURNS
        ]
        counts = {aspect: wall_aspect_turns(phase).count(aspect) for aspect in aspects}
        if len(aspects) > 1 and len(set(counts.values())) == 1:
            flat.append(phase.value)
    assert pairs == _WALL_LED_PAIRS, (
        f"{pairs} wall-led phase/aspect pairs exist, not {_WALL_LED_PAIRS}. The cap's cost is "
        f"reported as a fraction of this, so the denominator cannot move quietly."
    )
    assert len(at_cap) == _PAIRS_AT_THE_WALL_TURN_CAP, (
        f"{len(at_cap)} of {pairs} pairs sit at or above the {_MAX_WALL_TURNS}-turn cap, not "
        f"{_PAIRS_AT_THE_WALL_TURN_CAP}: {at_cap}. That count IS F11 — it is how much of the "
        f"authored order the cap throws away."
    )
    assert tuple(flat) == _PHASES_WITH_A_FLAT_RING, (
        f"the phases whose wall ring is perfectly flat are {tuple(flat)}, not "
        f"{_PHASES_WITH_A_FLAT_RING}. In a flat phase the authored emphasis decides nothing "
        f"about climbing, so `_wall_picks` may not call itself rank-weighted there."
    )


def test_BOTH_of_F11s_SURFACES_RANK_BY_THE_SAME_AUTHORED_ORDER() -> None:
    """⚠️ GUARD, ruling 38's "a fix to one surface only is not a fix". Two independent code paths
    read `ASPECT_EMPHASIS` — `wall_aspect_turns` weights turns by it, `open_climbing_fill` orders
    the filler family by it — and before this they each computed "rank" for themselves.

    The rank is restated here from `ASPECT_EMPHASIS` directly and NOT imported from
    `selection.aspect_rank`, for `_THE_BLOCKS_OWN_FILLER`'s reason: a test that asks the code
    what its own ordering is agrees with any ordering, including a reversed one.

    ⚠️ `open_climbing_fill` is rank-ORDERED and must not become rank-WEIGHTED. A weight there is
    a frequency, and frequency is what ruling 30 fixes: rotating a rank-weighted ring of that
    pool measured 1242 of 6000 fills credited to a quality the block is not named after on a day
    that still carried hard energy-system work, against the 0 that
    `test_the_LENGTH_FILL_is_ONE_block_carrying_THE_BLOCKS_OWN_INTENTION` pins.
    """
    for phase in Phase:
        row = ASPECT_EMPHASIS[phase]
        fill = [spec.aspect_key for spec in open_climbing_fill(phase)]
        ranks = [len(row) - row.index(key) for key in fill]
        assert ranks == sorted(ranks, reverse=True), (
            f"open_climbing_fill({phase.value}) offers {fill} at authored ranks {ranks}, which "
            f"is not the phase's own order. Ruling 30 credits the filled minutes to the quality "
            f"the block is most named after, and that is the FIRST row this returns."
        )
        turns = wall_aspect_turns(phase)
        led = wall_led_aspects(phase)
        counts = [turns.count(key) for key in led]
        assert counts == sorted(counts, reverse=True), (
            f"wall_aspect_turns({phase.value}) gives {led} the turn counts {counts}, which is "
            f"not weakly descending in the authored order. Whatever the cap flattens, a "
            f"LOWER-ranked wall quality may never take more turns than a higher-ranked one."
        )
