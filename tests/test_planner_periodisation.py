"""Periodisation and the plan's date maths — the gap table, the phase order, the spans.

DB-free: it reads `server/domain/planner/`, so it runs in the local gate. The testing policy's
"plan generation (phase spans, deloads, taper, volume allocation)" and "date and timezone
maths". Nothing else is here — no assertion that `MIN_BLOCKS` is 2 (a constant table, explicitly
on the SKIP list) and no snapshot of a generated plan. The gap table is asserted as a
**literal**, not by re-deriving the formula: a test that recomputes it agrees with any typo in
the implementation. The table is the decision.
"""

from datetime import date, timedelta
from itertools import pairwise

import pytest

from server.domain.grades import GRADES, Discipline, system
from server.domain.planner.blueprint import MAX_WEEK_COUNT, MIN_WEEK_COUNT, NoteKind
from server.domain.planner.contract import CannotPlanError, PlannerInput, RefusalReason
from server.domain.planner.periodisation import (
    GAP_BEYOND_ONE_PLAN,
    MAX_BLOCKS,
    WEEKS_PER_BLOCK,
    beyond_one_plan_note,
    block_count_for,
    block_phases,
    mesocycle_spans,
    week_count_for,
)
from server.domain.planner.schedule import microcycle_start, session_date, week_start_on_or_after
from server.domain.vocabulary import Phase

# 2026-08-31 is a Monday. A plan's start date is always one — the client normalises it,
# because the domain has no timezone.
_MONDAY = date(2026, 8, 31)

# The authored decision, verbatim from the approved plan. `gap <= 0` is a consolidation
# pair, not an error: a target already met still gets a plan.
_GAP_TABLE = {
    -5: (2, 8),
    -1: (2, 8),
    0: (2, 8),
    1: (3, 12),
    2: (4, 16),
    3: (5, 20),
    4: (6, 24),
    5: (7, 28),
    6: (8, 32),
    7: (8, 32),
    25: (8, 32),
}


@pytest.mark.parametrize(("gap", "expected"), sorted(_GAP_TABLE.items()))
def test_the_gap_table_is_the_one_that_was_authored(gap: int, expected: tuple[int, int]) -> None:
    assert (block_count_for(gap), week_count_for(gap)) == expected


def test_week_count_never_shrinks_as_the_gap_grows() -> None:
    """Monotonic, so a harder target can never buy a shorter plan."""
    counts = [week_count_for(gap) for gap in range(-10, 30)]
    assert counts == sorted(counts)


def test_every_reachable_gap_on_both_ladders_fits_the_plan_check_constraint() -> None:
    """`ck_plan_week_count_in_range` is `week_count BETWEEN 1 AND 52`, and a violation is an
    `IntegrityError` at insert time in PR #11b — a long way from the arithmetic that caused it.

    The gaps are derived from the ladders rather than from a guessed range: a new rung on
    either ladder widens the reachable set automatically, which is the whole point of not
    hard-coding `range(-30, 30)` here.
    """
    for discipline in Discipline:
        ordinals = sorted(
            {grade.ordinal for grade in GRADES if system(grade.system).discipline is discipline}
        )
        assert ordinals, f"{discipline} has no ladder"
        widest = ordinals[-1] - ordinals[0]
        for gap in range(-widest, widest + 1):
            weeks = week_count_for(gap)
            assert MIN_WEEK_COUNT <= weeks <= MAX_WEEK_COUNT, (
                f"gap {gap} on the {discipline} ladder yields {weeks} weeks, outside "
                f"ck_plan_week_count_in_range"
            )
            assert weeks % WEEKS_PER_BLOCK == 0


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


@pytest.mark.parametrize(
    ("blocks", "expected"),
    [
        (2, (Phase.BASE, Phase.PERFORMANCE)),
        (4, (Phase.BASE, Phase.STRENGTH, Phase.POWER, Phase.PERFORMANCE)),
        (
            8,
            (
                Phase.BASE,
                Phase.STRENGTH,
                Phase.POWER,
                Phase.POWER_ENDURANCE,
                Phase.STRENGTH,
                Phase.POWER,
                Phase.POWER_ENDURANCE,
                Phase.PERFORMANCE,
            ),
        ),
    ],
)
def test_block_phases_run_the_librarys_authored_cycle(
    blocks: int, expected: tuple[Phase, ...]
) -> None:
    """Base first, performance last, the middle rotating in the order
    `server/domain/exercises.py` authored its prescriptions against — which is what makes
    "a quality is maintained after its own block, never previewed before it" true by
    construction rather than by luck."""
    assert block_phases(blocks) == expected


@pytest.mark.parametrize("blocks", range(2, MAX_BLOCKS + 1))
def test_spans_tile_the_plan_exactly_once_starting_at_week_one(blocks: int) -> None:
    spans = mesocycle_spans(blocks)
    assert len(spans) == 2 * blocks, "two mesocycles per block: the phase, then its unload week"
    assert spans[0].start_week == 1
    assert spans[-1].end_week == blocks * WEEKS_PER_BLOCK
    assert len({span.start_week for span in spans}) == len(spans), (
        "UNIQUE (plan_id, start_week) on `mesocycle` makes a repeat uninsertable"
    )
    for earlier, later in pairwise(spans):
        assert later.start_week == earlier.end_week + 1, "no gap and no overlap between blocks"


@pytest.mark.parametrize("blocks", range(2, MAX_BLOCKS + 1))
def test_deloads_land_on_every_fourth_week_and_the_taper_is_the_last_one(blocks: int) -> None:
    """A deload is a mesocycle with its own prescriptions, and the taper is the one at the
    end — so they are told apart by phase, never by a flag or a multiplier."""
    spans = mesocycle_spans(blocks)
    deloads = [span for span in spans if span.phase is Phase.DELOAD]
    tapers = [span for span in spans if span.phase is Phase.TAPER]
    assert [span.start_week for span in deloads] == [
        block * WEEKS_PER_BLOCK for block in range(1, blocks)
    ]
    assert all(span.start_week == span.end_week for span in deloads + tapers)
    assert len(tapers) == 1
    assert tapers[0].end_week == spans[-1].end_week == blocks * WEEKS_PER_BLOCK


@pytest.mark.parametrize("gap", [GAP_BEYOND_ONE_PLAN + 1, GAP_BEYOND_ONE_PLAN + 4])
def test_a_capped_plan_says_the_target_is_more_than_one_plan_away(gap: int) -> None:
    note = beyond_one_plan_note(gap)
    assert note is not None
    assert note.kind is NoteKind.TARGET_BEYOND_ONE_PLAN


@pytest.mark.parametrize("gap", [GAP_BEYOND_ONE_PLAN - 1, GAP_BEYOND_ONE_PLAN])
def test_a_plan_that_reaches_its_target_carries_no_such_note(gap: int) -> None:
    """⚠️ Both sides of the boundary, because the boundary itself moved.

    Kilian, 2026-08-24: the note fires only where the clamp genuinely shortened the plan.
    At exactly `GAP_BEYOND_ONE_PLAN` the formula wants `MAX_BLOCKS` and gets `MAX_BLOCKS`,
    so nothing was truncated and saying otherwise is untrue. The approved plan document's
    "gap >= 6" is superseded — this parametrisation is what stops it being restored.
    """
    assert beyond_one_plan_note(gap) is None


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
    """`planned_session` stores `weekday` AND `scheduled_on` and nothing in the schema keeps
    them in agreement, so the generator has to."""
    scheduled = session_date(microcycle_start(_MONDAY, 5), weekday)
    assert scheduled.weekday() == weekday
    assert (scheduled - _MONDAY).days == 28 + weekday
