"""The plan generator — pure, and enforced pure by `server/domain/.ruff.toml`.

No DB, no clock, no RNG, no I/O; dates are passed in. That purity is not tidiness: it is
what makes `POST /api/plans/preview` able to build a whole plan without writing a row,
which is what makes the demo mount interactive. The ruff `TID251` rule one directory up
bans the imports that would break it, and it is scoped to `server/domain/` by hierarchical
config discovery so it cannot fire on legitimate code elsewhere.

**This module is a re-export facade and defines nothing.** Every name here belongs to a
sibling module, because `schedule.py` raises a refusal and `contract.py` therefore cannot
live in the package `__init__` without making the import circular.

| module | what it owns |
| --- | --- |
| `contract.py` | `GENERATOR_VERSION`, `PlannerInput`, `CannotPlanError`, `RefusalReason` |
| `periodisation.py` | `week_count_for`, `block_phases`, `mesocycle_spans` + the constants |
| `schedule.py` | the weekday mask, the subset choice, and the date maths |
| `blueprint.py` | the frozen output tree |
| `selection.py` | which exercises fill a cell, the per-phase emphasis, the shortfalls |
| `generate.py` | `generate()` — the whole plan |
| `fingerprint.py` | `library_digest()` — the library as a third input — and `generator_input()` |
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
