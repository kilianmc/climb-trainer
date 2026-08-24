"""Periodisation: how many weeks, in what phase order, split into which mesocycles.

Integer arithmetic over the grade gap and nothing else — no clock, no DB, no RNG. Week
numbers become dates in `schedule.py`.

## The gap chooses the length, and it is clamped at both ends

No user input, no override, no new form control (Kilian, 2026-08-24): the gap is the one
number the profile already holds that says how much work there is.

`MIN_BLOCKS` exists because `gap <= 0` is not an error. A climber who has already met their
target still wants a plan, and two blocks — one base, one performance — is the shortest
thing that can honestly be called periodised.

`MAX_BLOCKS` exists because the alternative is a silent 40-week plan for somebody who typed
an aspirational grade. Past eight blocks the honest answer is "that is more than one plan
away", and `beyond_one_plan_note` says so out loud rather than shipping a plan nobody
finishes.

## A deload is a mesocycle, not a multiplier

Every block is **two** mesocycles: `LOADING_WEEKS` under the block's own phase, then
`UNLOAD_WEEKS` of `DELOAD` — or `TAPER`, in the last block. `Phase` in
`server/domain/vocabulary.py` is explicit that a deload has its own prescriptions rather
than being the normal block scaled down, so there is no per-phase volume multiplier anywhere
in this package and adding one would contradict the schema.

## The middle cycle is the library's authored order, not a second opinion

`PHASE_CYCLE_MIDDLE` is base -> strength -> power -> power endurance -> performance with the
ends removed, which is exactly the cycle `server/domain/exercises.py` authored its
prescriptions against. Because it matches, "a quality is maintained after its own block,
never previewed before it" holds by construction rather than by a test — and
`DELIBERATELY_UNPRESCRIBED`'s four exemptions stay correct.
"""

from dataclasses import dataclass
from typing import Final

from server.domain.planner.blueprint import NoteKind, ScheduleNote
from server.domain.vocabulary import Phase

LOADING_WEEKS: Final = 3
UNLOAD_WEEKS: Final = 1
WEEKS_PER_BLOCK: Final = LOADING_WEEKS + UNLOAD_WEEKS
MIN_BLOCKS: Final = 2
MAX_BLOCKS: Final = 8

PHASE_CYCLE_MIDDLE: Final[tuple[Phase, ...]] = (
    Phase.STRENGTH,
    Phase.POWER,
    Phase.POWER_ENDURANCE,
)

# The gap at which the block count saturates. Below it, one extra rung buys one extra block;
# at it, the formula asks for `MAX_BLOCKS` and gets it; only ABOVE it is the plan genuinely
# cut short, which is when `beyond_one_plan_note` fires.
GAP_BEYOND_ONE_PLAN: Final = MAX_BLOCKS - MIN_BLOCKS


@dataclass(frozen=True, slots=True)
class MesocycleSpan:
    """One mesocycle's phase and its week range, 1-based and inclusive as the column is.

    Not a `MesocycleBlueprint`: this is the skeleton, computed before a single session
    exists, and keeping the two apart is what lets the span arithmetic be tested on its own.
    """

    phase: Phase
    start_week: int
    end_week: int

    def __post_init__(self) -> None:
        if self.start_week < 1:
            raise ValueError(f"start_week is 1-based, got {self.start_week}.")
        if self.end_week < self.start_week:
            raise ValueError(f"end_week {self.end_week} precedes start_week {self.start_week}.")


def block_count_for(gap: int) -> int:
    """Blocks for a grade gap, clamped. `gap <= 0` yields `MIN_BLOCKS`, not an error."""
    return min(max(MIN_BLOCKS + max(gap, 0), MIN_BLOCKS), MAX_BLOCKS)


def week_count_for(gap: int) -> int:
    """`plan.week_count`. Always a whole number of blocks, so always 8-32."""
    return block_count_for(gap) * WEEKS_PER_BLOCK


def block_phases(block_count: int) -> tuple[Phase, ...]:
    """One phase per block: base, the rotating middle, performance."""
    if block_count < MIN_BLOCKS:
        raise ValueError(
            f"a plan needs at least {MIN_BLOCKS} blocks (a base and a performance block), "
            f"got {block_count}."
        )
    middle = tuple(
        PHASE_CYCLE_MIDDLE[index % len(PHASE_CYCLE_MIDDLE)] for index in range(block_count - 2)
    )
    return (Phase.BASE, *middle, Phase.PERFORMANCE)


def mesocycle_spans(block_count: int) -> tuple[MesocycleSpan, ...]:
    """Two spans per block, in week order: the loading phase, then its unload week.

    The unload week of the **last** block is the taper, not a deload. That is the whole
    difference between the two, and it is why the taper is always the final week of the plan.
    """
    phases = block_phases(block_count)
    last_index = len(phases) - 1
    spans: list[MesocycleSpan] = []
    for index, phase in enumerate(phases):
        first_week = index * WEEKS_PER_BLOCK + 1
        spans.append(MesocycleSpan(phase, first_week, first_week + LOADING_WEEKS - 1))
        unload_week = first_week + LOADING_WEEKS
        spans.append(
            MesocycleSpan(
                Phase.TAPER if index == last_index else Phase.DELOAD,
                unload_week,
                unload_week + UNLOAD_WEEKS - 1,
            )
        )
    return tuple(spans)


def beyond_one_plan_note(gap: int) -> ScheduleNote | None:
    """The note that stops a capped plan from looking like a complete answer.

    ⚠️ Fires **strictly above** `GAP_BEYOND_ONE_PLAN`, i.e. only when the clamp genuinely
    shortened the plan (Kilian, 2026-08-24). At exactly that gap the formula asks for
    `MAX_BLOCKS` and gets `MAX_BLOCKS`, so nothing was truncated and the note would be
    telling the user something untrue. The approved plan document says "gap >= 6" and is
    **wrong on this point** — do not restore it to match.
    """
    if gap <= GAP_BEYOND_ONE_PLAN:
        return None
    return ScheduleNote(
        NoteKind.TARGET_BEYOND_ONE_PLAN,
        f"Your target is more than one plan away, so this plan runs the longest we build: "
        f"{MAX_BLOCKS * WEEKS_PER_BLOCK} weeks. Build the next one when you get there.",
    )
