"""Periodisation and the plan's date maths — the one length, the phase order, the spans.

DB-free: it reads `server/domain/planner/`, so it runs in the local gate. The testing policy's
"plan generation (phase spans, deloads, taper, volume allocation)" and "date and timezone
maths". Nothing else is here — no snapshot of a generated plan. The length and the phase list
are asserted as **literals**, not by re-deriving them: a test that recomputes them agrees with
any typo in the implementation. They are the decision. The arms that `generate()` a plan
sabotage it rather than snapshot it: a plan's own shape cannot be shown to bite on a hand-built
fixture.
"""

import sys
from dataclasses import replace
from datetime import date, timedelta
from itertools import pairwise
from types import ModuleType

import pytest

from server.domain.grades import GRADES, Discipline, system
from server.domain.planner.blueprint import (
    MAX_WEEK_COUNT,
    MIN_WEEK_COUNT,
    NoteKind,
    PlanBlueprint,
)
from server.domain.planner.contract import CannotPlanError, PlannerInput, RefusalReason
from server.domain.planner.generate import generate
from server.domain.planner.periodisation import (
    BLOCK_PHASES,
    LOADING_WEEKS,
    WEEK_COUNT,
    WEEKS_PER_BLOCK,
    MesocycleSpan,
    mesocycle_spans,
)
from server.domain.planner.schedule import microcycle_start, session_date, week_start_on_or_after
from server.domain.vocabulary import Phase

# 2026-08-31 is a Monday. A plan's start date is always one — the client normalises it,
# because the domain has no timezone.
_MONDAY = date(2026, 8, 31)

# Rulings 49 and 51, RESTATED rather than imported. What they replaced — `clamp(2 + gap, 2, 8)`
# blocks — was an app invention, and the arm that pinned it called it "verbatim from the plan".
_AUTHORED_WEEK_COUNT = 16
_AUTHORED_PHASES = (Phase.BASE, Phase.STRENGTH, Phase.POWER_ENDURANCE, Phase.PERFORMANCE)

# The library's authored cycle, restated: whichever middle blocks a plan carries must appear in
# this relative order, or a quality is previewed before its own block. D2 drops `POWER`.
_AUTHORED_MIDDLE_CYCLE = (Phase.STRENGTH, Phase.POWER, Phase.POWER_ENDURANCE)

# Every gap that used to buy a different length (0 -> 8 weeks, 1 -> 12, 2 -> 16, 3 -> 20,
# 4 -> 24, 5 -> 28, 6 -> 32), plus both ends of the widest ladder, where it clamped.
_GAPS_THAT_USED_TO_CHANGE_THE_LENGTH = (-29, 0, 1, 2, 3, 4, 5, 6, 29)


def test_the_length_LITERAL_and_the_SPAN_DERIVATION_are_the_same_number() -> None:
    """The two sources of the length, checked against each other and against the decision:
    `generate()` reads the spans and `tests/test_plans_api.py` reads `WEEK_COUNT`."""
    assert WEEK_COUNT == _AUTHORED_WEEK_COUNT
    assert mesocycle_spans()[-1].end_week == _AUTHORED_WEEK_COUNT
    assert len(BLOCK_PHASES) * WEEKS_PER_BLOCK == _AUTHORED_WEEK_COUNT
    assert MIN_WEEK_COUNT <= WEEK_COUNT <= MAX_WEEK_COUNT, "ck_plan_week_count_in_range"


def test_every_reachable_gap_is_inside_the_plan_check_constraint() -> None:
    """`ck_plan_week_count_in_range` is `week_count BETWEEN 1 AND 52` and a violation is an
    `IntegrityError` at insert — a long way from the arithmetic that caused it."""
    for discipline in Discipline:
        ordinals = sorted(
            {grade.ordinal for grade in GRADES if system(grade.system).discipline is discipline}
        )
        assert ordinals, f"{discipline} has no ladder"
    assert MIN_WEEK_COUNT <= WEEK_COUNT <= MAX_WEEK_COUNT
    assert WEEK_COUNT % WEEKS_PER_BLOCK == 0


def test_a_cross_ladder_pair_refuses_instead_of_producing_a_nonsense_gap() -> None:
    """The disjoint bands make a cross-discipline mistake loud; this is the thing that looks.

    Without the check the gap is ~1000, which clamps to the longest plan we build and looks
    entirely plausible in the response.
    """
    with pytest.raises(CannotPlanError) as raised:
        PlannerInput(
            discipline=Discipline.SPORT,
            current_ordinal=1005,  # a boulder rung under a sport target
            target_ordinal=2008,
            sessions_per_week=3,
            available_weekdays=0b010_0101,
            strength_aspect_key=None,
            weakness_aspect_key=None,
            open_injury_keys=(),
            equipment_keys=(),
            start_date=_MONDAY,
        )
    assert raised.value.reason is RefusalReason.CROSS_DISCIPLINE_GRADES


def test_the_FOUR_BLOCKS_are_the_ones_that_were_authored() -> None:
    """Ruling 51's phase list, and the properties that make it the right four: the ends
    `PHASE_GUIDE` is written against, and the library's own cycle order in the middle."""
    assert BLOCK_PHASES == _AUTHORED_PHASES
    assert BLOCK_PHASES[0] is Phase.BASE
    assert BLOCK_PHASES[-1] is Phase.PERFORMANCE
    assert len(set(BLOCK_PHASES)) == len(BLOCK_PHASES), "a repeated block is a different plan"
    middle = BLOCK_PHASES[1:-1]
    assert set(middle) <= set(_AUTHORED_MIDDLE_CYCLE)
    positions = [_AUTHORED_MIDDLE_CYCLE.index(phase) for phase in middle]
    assert positions == sorted(positions), (
        f"{[phase.value for phase in middle]} is not in the library's authored cycle order "
        f"{[phase.value for phase in _AUTHORED_MIDDLE_CYCLE]}, so a quality is previewed "
        f"before its own block."
    )


def test_spans_tile_the_plan_exactly_once_starting_at_week_one() -> None:
    spans = mesocycle_spans()
    assert len(spans) == 2 * len(BLOCK_PHASES), (
        "two mesocycles per block: the phase, then its unload week"
    )
    assert spans[0].start_week == 1
    assert spans[-1].end_week == WEEK_COUNT
    assert len({span.start_week for span in spans}) == len(spans), (
        "UNIQUE (plan_id, start_week) on `mesocycle` makes a repeat uninsertable"
    )
    for earlier, later in pairwise(spans):
        assert later.start_week == earlier.end_week + 1, "no gap and no overlap between blocks"


_SPORT_RUNGS = sorted(
    {grade.ordinal for grade in GRADES if system(grade.system).discipline is Discipline.SPORT}
)


def _plan(rungs: int = 2) -> PlanBlueprint:
    """A real generated plan, `rungs` up the sport ladder from its foot and gearless. Generated
    rather than hand-built: a shape invariant cannot be shown to bite a fixture built to fit it."""
    return generate(
        PlannerInput(
            discipline=Discipline.SPORT,
            current_ordinal=_SPORT_RUNGS[0],
            target_ordinal=_SPORT_RUNGS[rungs],
            sessions_per_week=3,
            available_weekdays=0b010_0101,
            strength_aspect_key=None,
            weakness_aspect_key=None,
            open_injury_keys=(),
            equipment_keys=(),
            start_date=_MONDAY,
        )
    )


def _plan_at_gap(gap: int) -> PlanBlueprint:
    """A real plan at an EXACT grade gap, taken from whichever end of the sport ladder can
    reach it. The ladder is contiguous, so a gap is a rung count."""
    current = _SPORT_RUNGS[-1] if gap < 0 else _SPORT_RUNGS[0]
    return generate(
        PlannerInput(
            discipline=Discipline.SPORT,
            current_ordinal=current,
            target_ordinal=current + gap,
            sessions_per_week=3,
            available_weekdays=0b010_0101,
            strength_aspect_key=None,
            weakness_aspect_key=None,
            open_injury_keys=(),
            equipment_keys=(),
            start_date=_MONDAY,
        )
    )


def _weeks_carried(plan: PlanBlueprint) -> int:
    """Microcycles actually in the tree, which is what the plan PRESCRIBES."""
    return sum(len(mesocycle.microcycles) for mesocycle in plan.mesocycles)


def test_a_plan_whose_mesocycles_do_not_tile_its_week_count_cannot_construct() -> None:
    """Every value below is inside `ck_plan_week_count_in_range`, so that CHECK passes and only
    the tiling check stands between a plan and reporting one length while prescribing another."""
    plan = _plan()
    assert plan.week_count == _weeks_carried(plan) > 0
    for bad in (MIN_WEEK_COUNT, plan.week_count - 1, plan.week_count + 1, MAX_WEEK_COUNT):
        with pytest.raises(ValueError, match="must tile"):
            replace(plan, week_count=bad)


def test_the_week_count_range_check_still_fires_on_its_own_terms() -> None:
    """The control: the tiling check must not have swallowed the CHECK it sits behind, or a
    0-week plan would fail for the wrong reason and 53 weeks would still insert."""
    plan = _plan()
    for bad in (MIN_WEEK_COUNT - 1, MAX_WEEK_COUNT + 1):
        with pytest.raises(ValueError, match="ck_plan_week_count_in_range"):
            replace(plan, week_count=bad)


def test_a_mesocycle_must_carry_exactly_the_weeks_its_span_claims() -> None:
    """The other half of "tile": without it every span could claim weeks 1-3 while the microcycles
    still ran 1..N. The empty arm is the anti-vacuity one — a pairwise loop would pass on it."""
    first = _plan().mesocycles[0]
    for broken in (
        {"end_week": first.end_week + 1},
        {"start_week": first.start_week + 1},
        {"microcycles": first.microcycles[:-1]},
        {"microcycles": ()},
        {"microcycles": tuple(reversed(first.microcycles))},
    ):
        with pytest.raises(ValueError, match="must carry exactly those microcycles"):
            replace(first, **broken)


def _one_more_block() -> tuple[MesocycleSpan, ...]:
    """`mesocycle_spans()` with a fifth block bolted on: the old last block's taper becomes a
    deload, and a fresh performance block and taper run after it. The sabotage below."""
    spans = list(mesocycle_spans())
    taper = spans[-1]
    spans[-1] = MesocycleSpan(Phase.DELOAD, taper.start_week, taper.end_week)
    first = taper.end_week + 1
    spans.append(MesocycleSpan(Phase.PERFORMANCE, first, first + LOADING_WEEKS - 1))
    spans.append(MesocycleSpan(Phase.TAPER, first + LOADING_WEEKS, first + LOADING_WEEKS))
    return tuple(spans)


def test_the_length_is_read_once_so_a_plan_cannot_misreport_it() -> None:
    """Sabotage the ONE read and both halves move together. The patch has to reach the module
    through `sys.modules` — the arm below is why."""
    module = sys.modules[generate.__module__]
    monkeypatched = pytest.MonkeyPatch()
    monkeypatched.setattr(module, "mesocycle_spans", _one_more_block)
    try:
        plan = _plan()
    finally:
        monkeypatched.undo()
    expected = WEEK_COUNT + WEEKS_PER_BLOCK
    assert plan.week_count == expected, "the extra block did not reach the length it reports"
    assert _weeks_carried(plan) == expected
    assert plan.name.startswith(f"{expected}-week"), "the name is the length the user reads"


def test_the_package_reexport_shadows_the_generate_submodule() -> None:
    """Why the arm above patches through `sys.modules`: `server/domain/planner/__init__.py`
    re-exports the FUNCTION, so patching the shadowed name is a silent no-op."""
    from server.domain import planner

    assert planner.generate is generate, "the attribute is the function, not the submodule"
    assert not isinstance(planner.generate, ModuleType)
    assert isinstance(sys.modules[generate.__module__], ModuleType)


def test_deloads_land_on_every_fourth_week_and_the_taper_is_the_last_one() -> None:
    """A deload is a mesocycle with its own prescriptions, and the taper is the one at the
    end — so they are told apart by phase, never by a flag or a multiplier."""
    blocks = len(BLOCK_PHASES)
    spans = mesocycle_spans()
    deloads = [span for span in spans if span.phase is Phase.DELOAD]
    tapers = [span for span in spans if span.phase is Phase.TAPER]
    assert [span.start_week for span in deloads] == [
        block * WEEKS_PER_BLOCK for block in range(1, blocks)
    ]
    assert all(span.start_week == span.end_week for span in deloads + tapers)
    assert len(tapers) == 1
    assert tapers[0].end_week == spans[-1].end_week == WEEK_COUNT


@pytest.mark.parametrize("gap", _GAPS_THAT_USED_TO_CHANGE_THE_LENGTH)
def test_the_GRADE_GAP_BUYS_THE_SAME_SIXTEEN_WEEKS_whatever_it_is(gap: int) -> None:
    """⚠️ GUARD, ruling 49 and the whole of F1. Read off a GENERATED PLAN: the length is a
    constant in `periodisation.py`, so asserting it there proves nothing about the gap."""
    plan = _plan_at_gap(gap)
    assert plan.grade_gap == gap, "the fixture did not produce the gap it claims to test"
    assert plan.week_count == _AUTHORED_WEEK_COUNT
    assert _weeks_carried(plan) == _AUTHORED_WEEK_COUNT
    assert plan.name.startswith(f"{_AUTHORED_WEEK_COUNT}-week")
    assert [
        mesocycle.phase for mesocycle in plan.mesocycles if mesocycle.phase in _AUTHORED_PHASES
    ] == list(_AUTHORED_PHASES)


def test_NO_NOTE_TELLS_THE_USER_THE_PLAN_WAS_CUT_SHORT() -> None:
    """`TARGET_BEYOND_ONE_PLAN` went with the clamp — nothing is truncated now. Pinned as the
    CLOSED set, not by name: a note kind is the client's styling contract."""
    assert {kind.value for kind in NoteKind} == {"fewer_sessions_than_requested"}


@pytest.mark.parametrize("offset", range(7))
def test_week_start_on_or_after_lands_on_a_monday_and_is_idempotent(offset: int) -> None:
    """Idempotent on a Monday is the property that matters: the edge applies this, and
    `PlannerInput` then asserts the result, so a drifting implementation would move every
    session in the plan by a day."""
    day = _MONDAY + timedelta(days=offset)
    monday = week_start_on_or_after(day)
    assert monday.weekday() == 0
    assert monday >= day
    assert week_start_on_or_after(monday) == monday


def test_microcycle_starts_are_seven_days_apart_and_all_mondays() -> None:
    starts = [microcycle_start(_MONDAY, week_no) for week_no in range(1, 33)]
    assert starts[0] == _MONDAY
    assert all(start.weekday() == 0 for start in starts)
    assert all((later - earlier).days == 7 for earlier, later in pairwise(starts))


@pytest.mark.parametrize("weekday", range(7))
def test_a_sessions_date_agrees_with_the_weekday_it_is_stored_against(weekday: int) -> None:
    """`planned_session` stores `weekday` AND `scheduled_on`; no constraint there enforces the
    agreement today and the Python check fails earlier, naming the day, so it stays here."""
    scheduled = session_date(microcycle_start(_MONDAY, 5), weekday)
    assert scheduled.weekday() == weekday
    assert (scheduled - _MONDAY).days == 28 + weekday
