"""Sessions onto weekdays, and week numbers onto dates.

`datetime.date` only, and **no timezone maths at all**: the domain has no clock, so the
timezone decision is entirely the client's choice of `start_date`. That is why
`week_start_on_or_after` takes the day rather than reading one.

## Which days, when there are more available than sessions

The n-subset of the available days whose **circular rest gaps** (wrapping Sunday to Monday)
are the most even, tie-broken lexicographically. Exhaustive over `C(m, n) <= 35`, which is
cheap and provably deterministic.

Naive striding was the obvious alternative and it is worse in the commonest case: Monday to
Friday with two sessions strides to Monday/Wednesday, leaving a five-day gap, where this
picks Monday/Thursday. Rest is the thing being allocated, so it is the thing being spread.

⚠️ **"Most even" compares the whole ascending gap profile, not just the smallest gap, and
that is a correction rather than a refinement.** Maximising the minimum gap alone is
undefined past three sessions a week: with four sessions out of seven days *some* pair is
always adjacent, so every subset ties at a minimum of 1 and the lexicographic tie-break
picks Mon/Tue/Wed/Thu — four days on, three off, which is the opposite of spreading rest.
Comparing the sorted profiles picks Mon/Tue/Thu/Sat instead. Every gap profile of a given
`n` sums to 7, so "lexicographically largest ascending profile" is exactly "most even", and
it agrees with the minimum-gap rule wherever that rule actually decides.

## Fewer days than sessions is a note, never a silent change

`UNIQUE (microcycle_id, weekday)` on `planned_session` makes two sessions on one weekday
structurally impossible, so doubling up is not a preference this module gets to have — it is
a schema fact. The request is honoured as far as it fits and the shortfall is stated.

## An empty mask refuses

Mask 0 is legal and reachable ("answered, no days") and is not the equipment dead end: the
control expresses the answer, it stores fine, and ticking a day is the fix. So it refuses
with its own sentence rather than generating something empty.

## Session count never varies by phase

Deload and taper weeks keep the same weekday set. The load difference comes entirely from
the phase's own `prescription_template` rows, which is the most literal reading of "a deload
is not a scaled block" — and it removes a tunable.
"""

from datetime import date, timedelta
from itertools import combinations, pairwise

from server.domain.planner.blueprint import NoteKind, ScheduleNote
from server.domain.planner.contract import MAX_WEEKDAY_MASK, CannotPlanError, RefusalReason

DAYS_PER_WEEK = 7


def weekdays_of_mask(mask: int) -> tuple[int, ...]:
    """The weekdays a 7-bit mask marks available, ascending. **Monday = bit 0.**"""
    if not 0 <= mask <= MAX_WEEKDAY_MASK:
        raise ValueError(f"available_weekdays is a 7-bit mask, got {mask}.")
    return tuple(day for day in range(DAYS_PER_WEEK) if mask >> day & 1)


def choose_weekdays(mask: int, sessions_per_week: int) -> tuple[int, ...]:
    """Which weekdays this plan's sessions land on, every week of it.

    Returns fewer than `sessions_per_week` when fewer days are available — pair it with
    `fewer_sessions_note` so the plan says so.
    """
    available = weekdays_of_mask(mask)
    if not available:
        raise CannotPlanError(RefusalReason.NO_AVAILABLE_DAYS)
    if len(available) <= sessions_per_week:
        return available
    # `max()` returns the FIRST maximal element and `combinations` yields ascending, so
    # equally-even subsets tie-break to the lexicographically smallest set of days.
    return max(combinations(available, sessions_per_week), key=_rest_profile)


def fewer_sessions_note(*, requested: int, scheduled: int) -> ScheduleNote | None:
    """The note for a week that could not fit everything asked for. `None` when it did."""
    if scheduled >= requested:
        return None
    days = "day" if scheduled == 1 else "days"
    return ScheduleNote(
        NoteKind.FEWER_SESSIONS_THAN_REQUESTED,
        f"You asked for {requested} sessions a week and marked {scheduled} {days} available, "
        f"so this plan schedules {scheduled}.",
    )


def week_start_on_or_after(day: date) -> date:
    """The Monday on or after `day`. Idempotent on a Monday, which is what makes it safe to
    apply at the edge and assert in `PlannerInput`."""
    return day + timedelta(days=(DAYS_PER_WEEK - day.weekday()) % DAYS_PER_WEEK)


def microcycle_start(plan_start: date, week_no: int) -> date:
    """`microcycle.start_date` for a 1-based week number."""
    if week_no < 1:
        raise ValueError(f"week_no is 1-based, got {week_no}.")
    return plan_start + timedelta(days=DAYS_PER_WEEK * (week_no - 1))


def session_date(week_start: date, weekday: int) -> date:
    """`planned_session.scheduled_on`, stored rather than derived — see `PlannedSession`."""
    if not 0 <= weekday <= 6:
        raise ValueError(f"weekday is 0-6 with Monday = 0, got {weekday}.")
    return week_start + timedelta(days=weekday)


def _rest_profile(days: tuple[int, ...]) -> tuple[int, ...]:
    """The circular rest gaps between consecutive sessions, ascending.

    Sorted, so comparing two profiles compares how *even* they are and not which day is
    which. A single session's gap is the whole week, which is correct and also why the
    caller maximises over subsets rather than computing a spread: one session cannot be
    badly spaced.
    """
    if len(days) == 1:
        return (DAYS_PER_WEEK,)
    wrap = days[0] + DAYS_PER_WEEK - days[-1]
    gaps = (later - earlier for earlier, later in pairwise(days))
    return tuple(sorted((wrap, *gaps)))
