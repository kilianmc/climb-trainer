"""The plan generator — pure, and enforced pure by `server/domain/.ruff.toml`.
No DB, no clock, no RNG, no I/O; dates are passed in. That purity is what makes `POST
/api/plans/preview` able to build a whole plan without writing a row, which is what makes the demo
mount interactive. **This module is a re-export facade and defines nothing**: every name belongs to
a sibling, because `schedule.py` raises a refusal and `contract.py` therefore cannot live in the
package `__init__` without making the import circular. `periodisation.py` owns weeks and phases,
`schedule.py` the weekday mask and date maths, `selection.py` which exercises fill a cell plus the
shortfalls, `blueprint.py` the frozen output tree, `fingerprint.py` the library digest,
`generate.py` the whole plan.
"""

from server.domain.planner.blueprint import (
    BlockBlueprint,
    MesocycleBlueprint,
    MicrocycleBlueprint,
    NoteKind,
    PlanBlueprint,
    ScheduleNote,
    SessionBlueprint,
    SetBlueprint,
    Shortfall,
)
from server.domain.planner.contract import (
    GENERATOR_VERSION,
    REFUSAL_MESSAGES,
    CannotPlanError,
    PlannerInput,
    RefusalReason,
)
from server.domain.planner.fingerprint import generator_input, library_digest
from server.domain.planner.generate import SECONDS_PER_REP, WARMUP_MINUTES, generate
from server.domain.planner.selection import (
    ASPECT_EMPHASIS,
    BLOCKS_PER_SESSION,
    SUPPORT_ASPECTS,
    candidates,
    prescribable,
)

__all__ = [
    "ASPECT_EMPHASIS",
    "BLOCKS_PER_SESSION",
    "GENERATOR_VERSION",
    "REFUSAL_MESSAGES",
    "SECONDS_PER_REP",
    "SUPPORT_ASPECTS",
    "WARMUP_MINUTES",
    "BlockBlueprint",
    "CannotPlanError",
    "MesocycleBlueprint",
    "MicrocycleBlueprint",
    "NoteKind",
    "PlanBlueprint",
    "PlannerInput",
    "RefusalReason",
    "ScheduleNote",
    "SessionBlueprint",
    "SetBlueprint",
    "Shortfall",
    "candidates",
    "generate",
    "generator_input",
    "library_digest",
    "prescribable",
]
