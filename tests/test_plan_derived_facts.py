"""The band a plan was generated for, at its EDGES, and its arrival on the plan payload.

⚠️ Tested on the boundaries, off the four named ceilings rather than off grade labels: a test in
the middle of a band passes however far the bar has moved. Crossing a boundary is asserted to
MOVE a figure, because a band that changes nothing is the "banding was inert" failure already
shipped once here.

`Level` is never persisted, so a client re-deriving it would put these thresholds in two
languages. DB-free: `PlanOut` is built directly, which also proves the PREVIEW path carries it.
"""

from datetime import date
from typing import Any

import pytest

from server.domain.grades import Discipline
from server.domain.planner.climbing import (
    BEGINNER_CEILING_BOULDER,
    BEGINNER_CEILING_SPORT,
    INTERMEDIATE_CEILING_BOULDER,
    INTERMEDIATE_CEILING_SPORT,
    Level,
    climbing_floor_pct,
    climbing_target_band,
    finger_sessions_for,
    level_for,
)
from server.domain.vocabulary import Phase
from server.plans.routes import PlanOut

_CEILINGS = (
    (Discipline.SPORT, BEGINNER_CEILING_SPORT, Level.BEGINNER, Level.INTERMEDIATE),
    (Discipline.SPORT, INTERMEDIATE_CEILING_SPORT, Level.INTERMEDIATE, Level.ADVANCED),
    (Discipline.BOULDER, BEGINNER_CEILING_BOULDER, Level.BEGINNER, Level.INTERMEDIATE),
    (Discipline.BOULDER, INTERMEDIATE_CEILING_BOULDER, Level.INTERMEDIATE, Level.ADVANCED),
)


def _plan(discipline: Discipline, generator_input: dict[str, Any]) -> PlanOut:
    """A minimal payload — only `discipline` and `generator_input` feed the derived band."""
    return PlanOut(
        generator_version="1.0.0",
        generator_input=generator_input,
        name="Road to 7b",
        discipline=discipline,
        target_grade_id=16,
        current_grade_id=11,
        start_date=date(2026, 9, 7),
        week_count=28,
        grade_gap=5,
        mesocycles=[],
        shortfalls=[],
        notes=[],
    )


@pytest.mark.parametrize(("discipline", "ceiling", "below", "above"), _CEILINGS)
def test_a_ceiling_ordinal_is_INSIDE_the_lower_band(
    discipline: Discipline, ceiling: int, below: Level, above: Level
) -> None:
    """`<=`, so the ceiling grade itself is the last one in the band it names."""
    assert level_for(discipline, ceiling) is below
    assert level_for(discipline, ceiling + 1) is above


@pytest.mark.parametrize(("discipline", "ceiling", "below", "above"), _CEILINGS)
def test_crossing_a_boundary_MOVES_the_figures_keyed_by_the_band(
    discipline: Discipline, ceiling: int, below: Level, above: Level
) -> None:
    """Read through the functions, never off the tables: a boundary that changes no
    prescription is banding that exists on paper only."""
    assert climbing_floor_pct(discipline, ceiling) != climbing_floor_pct(discipline, ceiling + 1)
    assert climbing_target_band(discipline, ceiling) != climbing_target_band(
        discipline, ceiling + 1
    )
    assert finger_sessions_for(discipline, ceiling, Phase.STRENGTH) != finger_sessions_for(
        discipline, ceiling + 1, Phase.STRENGTH
    )


def test_the_payload_carries_the_band_the_PLAN_was_generated_for() -> None:
    """Every figure equal to the domain function's answer, and no number written twice."""
    ordinal = BEGINNER_CEILING_SPORT + 1
    band = _plan(Discipline.SPORT, {"current_ordinal": ordinal}).model_dump()["climbing_band"]
    low, high = climbing_target_band(Discipline.SPORT, ordinal)
    assert band == {
        "level": level_for(Discipline.SPORT, ordinal),
        "climbing_floor_pct": climbing_floor_pct(Discipline.SPORT, ordinal),
        "climbing_target_pct_low": low,
        "climbing_target_pct_high": high,
        "finger_sessions_per_week": finger_sessions_for(Discipline.SPORT, ordinal, Phase.STRENGTH),
        "finger_phases": [Phase.STRENGTH, Phase.POWER],
    }


def test_it_follows_the_STORED_ordinal_and_not_the_grade_ids_on_the_row() -> None:
    """⚠️ The plan explains the band it was BUILT for. `current_grade_id` is identical in both
    payloads below and the band still differs, which is the whole point."""
    beginner = _plan(Discipline.SPORT, {"current_ordinal": BEGINNER_CEILING_SPORT})
    later = _plan(Discipline.SPORT, {"current_ordinal": INTERMEDIATE_CEILING_SPORT + 1})
    assert beginner.current_grade_id == later.current_grade_id
    assert beginner.climbing_band is not None
    assert later.climbing_band is not None
    assert beginner.climbing_band.level is Level.BEGINNER
    assert later.climbing_band.level is Level.ADVANCED


def test_the_beginner_band_owes_ZERO_finger_sessions() -> None:
    """The figure a renderer must OMIT rather than print, so the payload has to state it."""
    plan = _plan(Discipline.BOULDER, {"current_ordinal": BEGINNER_CEILING_BOULDER})
    assert plan.climbing_band is not None
    assert plan.climbing_band.finger_sessions_per_week == 0


@pytest.mark.parametrize(
    "generator_input", [{}, {"current_ordinal": None}, {"current_ordinal": "6c"}]
)
def test_an_unusable_stored_ordinal_degrades_to_null_rather_than_500(
    generator_input: dict[str, Any],
) -> None:
    """`_grade_gap`'s rule: a plan somebody is halfway through must still load."""
    assert _plan(Discipline.SPORT, generator_input).climbing_band is None
