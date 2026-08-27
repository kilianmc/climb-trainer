"""Sessions onto the weekday mask, and what happens when it does not fit.

DB-free: it reads `server/domain/planner/schedule.py`. Justified as a "complex transform" (an
exhaustive subset search with a tie-break) and as plan generation's volume allocation. The
expected weekday sets are **literals**, because the most-even subset is not obvious by
inspection and re-deriving it here would agree with any bug in the derivation. Mon/Thu out of
Mon-Fri motivated the algorithm; the four- and five-session rows caught a minimum-gap-only
tie-break, which chose Mon/Tue/Wed/Thu — every four-day subset ties at a minimum gap of 1.
"""

import pytest

from server.domain.planner.blueprint import NoteKind
from server.domain.planner.contract import CannotPlanError, RefusalReason
from server.domain.planner.schedule import choose_weekdays, fewer_sessions_note, weekdays_of_mask

_ALL_WEEK = 0b111_1111
_MON_TO_FRI = 0b001_1111
_MON_WED_SAT = 0b010_0101
_WED_SAT_SUN = 0b110_0100


def test_the_mask_reads_monday_as_bit_zero() -> None:
    """Shared with `user_profile.available_weekdays` and `planned_session.weekday`; getting
    the bit order backwards would put a Monday climber's plan on Sunday."""
    assert weekdays_of_mask(0b000_0001) == (0,)
    assert weekdays_of_mask(0b100_0000) == (6,)
    assert weekdays_of_mask(_MON_WED_SAT) == (0, 2, 5)


@pytest.mark.parametrize("mask", [_MON_WED_SAT, _MON_TO_FRI, _ALL_WEEK])
def test_every_available_day_is_used_when_the_counts_match(mask: int) -> None:
    available = weekdays_of_mask(mask)
    assert choose_weekdays(mask, len(available)) == available


@pytest.mark.parametrize(
    ("mask", "sessions", "expected"),
    [
        # Mon-Fri, two sessions: Mon/Thu, not the Mon/Wed a naive stride gives.
        (_MON_TO_FRI, 2, (0, 3)),
        (_MON_TO_FRI, 3, (0, 2, 4)),
        (_MON_TO_FRI, 4, (0, 1, 2, 4)),
        # A full week ties repeatedly, so these pin the lexicographic tie-break: Mon/Thu and
        # Mon/Fri both rest 3 and 4 days, and the first one wins.
        (_ALL_WEEK, 1, (0,)),
        (_ALL_WEEK, 2, (0, 3)),
        (_ALL_WEEK, 3, (0, 2, 4)),
        (_ALL_WEEK, 4, (0, 1, 3, 5)),
        (_ALL_WEEK, 5, (0, 1, 2, 3, 5)),
        # Wed/Sat/Sun with two sessions: Wed/Sat and Wed/Sun both rest 3 and 4, so the
        # tie-break decides, and Sat/Sun's one-day gap loses outright.
        (_WED_SAT_SUN, 2, (2, 5)),
    ],
)
def test_fewer_sessions_than_days_spreads_rest_as_evenly_as_it_can(
    mask: int, sessions: int, expected: tuple[int, ...]
) -> None:
    chosen = choose_weekdays(mask, sessions)
    assert chosen == expected
    assert len(set(chosen)) == sessions, "UNIQUE (microcycle_id, weekday) forbids a repeat"
    assert set(chosen) <= set(weekdays_of_mask(mask)), "never schedules an unavailable day"


def test_more_sessions_than_days_schedules_what_fits_and_says_so() -> None:
    """Never silently dropped, and never doubled up: two sessions on one weekday is not
    a preference, it is `UNIQUE (microcycle_id, weekday)` on `planned_session`."""
    chosen = choose_weekdays(_MON_WED_SAT, 5)
    assert chosen == (0, 2, 5)
    note = fewer_sessions_note(requested=5, scheduled=len(chosen))
    assert note is not None
    assert note.kind is NoteKind.FEWER_SESSIONS_THAN_REQUESTED
    assert note.message == (
        "You asked for 5 sessions a week and marked 3 days available, so this plan schedules 3."
    )


def test_a_plan_that_fits_carries_no_note() -> None:
    assert fewer_sessions_note(requested=3, scheduled=3) is None


def test_a_single_available_day_is_described_in_the_singular() -> None:
    note = fewer_sessions_note(requested=4, scheduled=1)
    assert note is not None
    assert "marked 1 day available" in note.message


def test_no_available_day_refuses_with_its_own_reason() -> None:
    """Mask 0 is legal and reachable ("answered, no days") and is NOT the equipment dead
    end: the control expresses the answer, it stores fine, and ticking a day is the fix."""
    with pytest.raises(CannotPlanError) as raised:
        choose_weekdays(0, 3)
    assert raised.value.reason is RefusalReason.NO_AVAILABLE_DAYS
    assert "Tick at least one day" in raised.value.message
