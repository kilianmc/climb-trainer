"""plan: current_grade_id + generator_caveats, session_block rest, one-active index

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-25

Four purely additive operations for PR #11b, the plan WRITE path. Additive by rule as well as
by luck — expand -> deploy -> contract, and deploys here are automatic while migrations are
not, so a revision must be safe against the *currently deployed* code too. Nothing here can
fail on existing data: `plan` and `session_block` are empty in both environments, because no
write path to the plan tree has ever existed. That matters most for the unique index, since
creating one against rows that already violate it is the usual way an "additive" revision
aborts.

## `plan.current_grade_id` — a real column, not a derivation

The profile's current grade **drifts as the climber improves**, and nothing else recovers what
grade the plan was built from — `generator_input` carries the *ordinal*, not the id, and an
ordinal alone does not identify a `grade` row (see `ascent`'s composite FK). Issue #64's
dashboard progression queries this.

`NO ACTION`, matching the sibling `plan.target_grade_id`, and **deliberately no index**: an FK
index exists to save the referencing-side scan a `SET NULL`/`CASCADE` delete performs, and
`grade` is seeded reference data nothing deletes. **Do not "complete the set."**

## `plan.generator_caveats` — `jsonb`, nullable, and ONE column for four things

It holds what the generator *said* about the plan it built: the plan-level shortfall roll-up,
the schedule notes, each session's unfilled slots and each block's substitution. None of it is
recoverable from the tree — a block's shortfall names the aspect the generator WANTED and could
not fill, which no persisted row records — so without this column the `/plan` screen loses every
equipment-gap banner on reload.

One column rather than four, and rather than one each on `plan`, `planned_session` and
`session_block`: it is one fact, written by one statement, read by one screen, and nothing
queries inside it — the same argument that makes `generator_input` `jsonb`. Per-row columns would
have meant ~2,400 mostly-NULL jsonb values per plan on `session_block`.

Nullable, no server default, no backfill. The READ path has to cope with caveats it cannot parse
regardless (`server/plans/routes.py::_StoredCaveats` treats an unrecognised shape as "no
caveats", never a 500), and a `NOT NULL DEFAULT '{}'` would buy that reader nothing while losing
the ability to tell "no caveats" from "never written". Server-written only.

(Added in round 2 by AMENDING this revision, which was legitimate on both of CLAUDE.md's checks:
the file was still untracked, and neither environment had run it.)

## `session_block.rest_between_sets_seconds` — a new column, not a redefinition

All three rests in the plan tree are distinct, and the generator already emits all three
(`server/domain/planner/blueprint.py`, documented departure 4):

- `prescribed_set.target_rest_seconds` — rest *within* a set (between reps on a repeater).
- **this column** — rest *between* sets of the block.
- `session_block.rest_after_seconds` — rest *after* the whole block.

Redefining any of them to absorb another would silently change what already generates, on plans
somebody is halfway through. `SmallInteger`, nullable, mirroring
`prescription_template.rest_between_sets_seconds`, the row the blueprint reads the value from.

## `uq_plan_one_active_per_user`

⚠️ **The predicate below is `server/models.py::Plan`'s definition of active, verbatim, and has
to stay verbatim** — two definitions of "active" that drift is an invariant that holds for the
index and not for the endpoint. Postgres has no partial unique *constraint*, so it is a partial
unique *index*, the same shape and reason as `0005`'s `uq_user_injury_open_area`. (Issue #62: the
old objection in the `Plan` docstring — no local Postgres to verify the rendering against —
expired with PR #57.)

⚠️ **`sa.text(...)`, never `func.text(...)`.** `func.text("…")` type-checks, lints, and compiles
to a *function call* named `text` that Postgres has never heard of, so it passes every local gate
that does not touch a database and then fails against the real thing. Same trap `0005` documents.

The endpoint half is not replaced by this index and is not optional: the transaction that
activates one plan is the transaction that stands the previous one down
(`server/plans/routes.py::create_plan`). The index is what makes a concurrent double-tap a `409`
instead of two active plans.

`downgrade()` drops exactly what `upgrade()` added — none of the four existed before — and is for
local and CI use only; production never downgrades. Hand-written, like 0001-0007.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `server.models.Plan.__table_args__`'s definition of active, character for character. Spelled
# out rather than imported because a revision must not depend on a constant a later PR retunes.
ONE_ACTIVE_INDEX = "uq_plan_one_active_per_user"
ACTIVE_PLAN_PREDICATE = "activated_at IS NOT NULL AND abandoned_at IS NULL AND completed_at IS NULL"


def upgrade() -> None:
    op.add_column("plan", sa.Column("current_grade_id", sa.Integer(), nullable=True))
    op.add_column(
        "plan",
        sa.Column("generator_caveats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # `op.f(...)` marks the name as already-conventional so Alembic does not re-apply
    # `NAMING_CONVENTION` to it — the house style every FK in `0004` uses.
    op.create_foreign_key(
        op.f("fk_plan_current_grade_id_grade"),
        "plan",
        "grade",
        ["current_grade_id"],
        ["id"],
    )
    op.add_column(
        "session_block",
        sa.Column("rest_between_sets_seconds", sa.SmallInteger(), nullable=True),
    )
    op.create_index(
        ONE_ACTIVE_INDEX,
        "plan",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_PLAN_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(ONE_ACTIVE_INDEX, table_name="plan")
    op.drop_column("session_block", "rest_between_sets_seconds")
    op.drop_column("plan", "generator_caveats")
    op.drop_constraint(op.f("fk_plan_current_grade_id_grade"), "plan", type_="foreignkey")
    op.drop_column("plan", "current_grade_id")
