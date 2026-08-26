"""plan: current_grade_id + generator_caveats, session_block rest, one-active index

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-25

Four purely additive operations, for PR #11b — the plan WRITE path. `0007` shipped a
read-only library; this is the first revision the persist endpoint needs. Additive by rule
as well as by luck: expand -> deploy -> contract, and deploys here are automatic while
migrations are not, so a revision must be safe against the *currently deployed* code too.
Pre-`0008` code reads and writes none of the three new columns, and no existing row is
rewritten.

Nothing here can fail on existing data: `plan` and `session_block` are **empty in both
environments**, because no write path to the plan tree has ever existed. That matters for
the unique index in particular — creating one against rows that already violate it is the
usual way a "purely additive" revision aborts.

## `plan.current_grade_id` — a real column, not a derivation

The profile's current grade **drifts as the climber improves**. Once the user logs 6b,
nothing anywhere recovers what grade the plan was built from — and `generator_input`
carries the *ordinal*, not the id, so it is not a substitute (a `grade.id` and its ordinal
live in different ladders' rows; see `ascent`'s composite FK for what the ordinal alone is
worth). Issue #64's dashboard progression queries this. So it is stored.

**No `ondelete`, therefore `NO ACTION`**, matching the sibling `plan.target_grade_id`.
**And deliberately no index**, per CLAUDE.md's rule: an index on an FK column exists to
save the referencing-side scan a `SET NULL`/`CASCADE` delete performs, and `grade` is
seeded reference data nothing deletes (retiring a grade is its own deliberate migration —
`server/seed.py` upserts and never deletes). No delete means no scan means nothing for an
index to save. **Do not "complete the set."**

## `plan.generator_caveats` — `jsonb`, nullable, and ONE column for four things

Added in round 2 of #11b (Kilian's call, 2026-08-26) by AMENDING this revision rather than
stacking an `0009`. The amendment was checked the two ways CLAUDE.md requires: `git log
--all -- migrations/versions/0008_plan_persist.py` returns nothing — the file is still
UNTRACKED, not merely uncommitted — and neither environment has run it (dev at `0007`,
production at `0006`). Once a revision exists on any branch or has been applied anywhere it
is frozen and the fix is a new revision.

It holds what the generator *said* about the plan it built: the plan-level shortfall
roll-up, the schedule notes, each session's unfilled slots and each block's substitution.
None of it is recoverable from the tree — a block's shortfall names the aspect the generator
WANTED and could not fill, which no persisted row records — so without this column the
`/plan` screen loses every equipment-gap banner on reload.

**One column rather than four, and rather than one each on `plan`, `planned_session` and
`session_block`.** It is one fact, written by one statement, read by one screen, and nothing
queries inside it — the same argument that makes `generator_input` `jsonb`. Per-row columns
would have meant a mostly-NULL `jsonb` on `session_block`: ~2,400 NULLs per plan to record a
handful of caveats. The three `generator_*` columns together are the generation record.

**Nullable, with no server default and no backfill.** `plan` is empty in both environments,
so there is nothing to backfill; nullable anyway because the READ path has to cope with a
plan whose caveats it cannot parse regardless (`server/plans/routes.py::_StoredCaveats`
treats an unrecognised shape as "no caveats", never a 500), and a NOT NULL with a `'{}'`
default would buy that reader nothing while removing the ability to tell "no caveats" from
"never written". Server-written only: no request body reaches it.

## `session_block.rest_between_sets_seconds` — a new column, not a redefinition

All three rests in the plan tree are genuinely distinct, and the generator already emits
all three (`server/domain/planner/blueprint.py`, documented departure 4):

- `prescribed_set.target_rest_seconds` — rest *within* a set (between reps on a repeater).
- **this column** — rest *between* sets of the block.
- `session_block.rest_after_seconds` — rest *after* the whole block.

Redefining any of them to absorb another would silently change what already generates, on
plans somebody is halfway through. `SmallInteger`, nullable, mirroring
`prescription_template.rest_between_sets_seconds`, which is the row the blueprint reads the
value out of.

## `uq_plan_one_active_per_user` — the one-active-plan invariant, structurally

`server/models.py::Plan` defines active as
`activated_at IS NOT NULL AND abandoned_at IS NULL AND completed_at IS NULL`, and the
predicate below is **that sentence verbatim**. It has to stay verbatim: two definitions of
"active" that drift is an invariant that holds for the index and not for the endpoint.

Postgres has no partial unique *constraint*, so this is a partial unique *index* — the same
shape as `uq_user_injury_open_area` in `0005`, and the same reason. The old objection
recorded in the `Plan` docstring (Alembic compares partial-index predicates as text, with no
local Postgres to verify the rendering against, so shipping one risked a false
`alembic check` failure) **expired with PR #57**, which brought up a local Postgres. Tracked
as issue **#62**.

⚠️ **`sa.text(...)`, never `func.text(...)`.** `func.text("…")` type-checks, lints, and
compiles to a *function call* named `text` that Postgres has never heard of — so it passes
every local gate that does not touch a database and then fails against the real thing. Same
trap the `0005` precedent documents.

The endpoint half of the invariant is not replaced by this index and is not optional: the
transaction that activates one plan is the transaction that stands the previous one down
(`server/plans/routes.py::create_plan`). The index is what makes a concurrent double-tap a
`409` instead of two active plans.

## `downgrade()`

Exactly reversible — none of the four existed before this revision, so dropping them loses
nothing that predates it. `plan` and `session_block` carry user rows, which is why the
downgrade drops only what it added and touches no other column;
`tests/test_migrations_additive.py` reads `upgrade()` alone and would refuse a destructive op
there. Local and CI use only — production never downgrades (`migrate.yml` offers no
`downgrade` action, on purpose).

Hand-written, like 0001-0007, and no database was touched to *produce* it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors `server.models.Plan.__table_args__` and the `Plan` docstring's definition of
# active, character for character. Spelled out here rather than imported because a revision
# must not depend on a constant a later PR could retune.
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
