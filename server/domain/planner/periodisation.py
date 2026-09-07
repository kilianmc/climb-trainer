"""Periodisation: how many weeks, in what phase order, split into which mesocycles.

Integer arithmetic and nothing else — no clock, no DB, no RNG. Week numbers become dates in
`schedule.py`.

## Sixteen weeks, four blocks, for every user

Ruling 49 (Kilian, 2026-09-06). The grade gap used to choose the length —
`clamp(2 + gap, 2, 8)` blocks — and no source does that; it was an app invention that gave a
met target an 8-week plan and an aspirational grade a 32-week one. Twelve weeks was measured
and rejected: this library cannot fill it. The taper loses its hard aerobic-power work on 5 of
42 profiles and the library-breadth floor fails on every profile, against 0 of 42 and a pass
at sixteen.

## A deload is a mesocycle, not a multiplier

Every block is **two** mesocycles: `LOADING_WEEKS` under the block's own phase, then
`UNLOAD_WEEKS` of `DELOAD` — or `TAPER`, in the last block. `Phase` in
`server/domain/vocabulary.py` is explicit that a deload has its own prescriptions rather
than being the normal block scaled down, so there is no per-phase volume multiplier anywhere
in this package and adding one would contradict the schema.

## Which four blocks: the authored cycle with power dropped

Ruling 51, candidate D2. Dropping the `POWER` block costs `power` 27.4% -> 24.2% of all
prescribed seconds and it stays the second-biggest thing in the plan, because limit boulders
and contact strength are prescribed in the three surviving blocks anyway; dropping
`POWER_ENDURANCE` instead would have cost that quality 9.4% -> 2.4%, three quarters of itself.
The middle keeps the order `server/domain/exercises.py` authored its prescriptions against,
so `DELIBERATELY_UNPRESCRIBED`'s exemptions stay correct.
"""

from dataclasses import dataclass
from typing import Final

from server.domain.vocabulary import Phase

LOADING_WEEKS: Final = 3
UNLOAD_WEEKS: Final = 1
WEEKS_PER_BLOCK: Final = LOADING_WEEKS + UNLOAD_WEEKS

BLOCK_PHASES: Final[tuple[Phase, ...]] = (
    Phase.BASE,
    Phase.STRENGTH,
    Phase.POWER_ENDURANCE,
    Phase.PERFORMANCE,
)

# A LITERAL, not `len(BLOCK_PHASES) * WEEKS_PER_BLOCK`: `generate()` derives the length from
# the spans, so these are two independent sources and the tests check them against each other.
WEEK_COUNT: Final = 16


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


def mesocycle_spans() -> tuple[MesocycleSpan, ...]:
    """Two spans per block, in week order: the loading phase, then its unload week.

    The unload week of the **last** block is the taper, not a deload. That is the whole
    difference between the two, and it is why the taper is always the final week of the plan.
    """
    last_index = len(BLOCK_PHASES) - 1
    spans: list[MesocycleSpan] = []
    for index, phase in enumerate(BLOCK_PHASES):
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
