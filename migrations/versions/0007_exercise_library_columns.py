"""exercise: substitution_hint, retired_at

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-23

Two nullable columns, and nothing else. Additive by necessity and by rule: expand ->
deploy -> contract, and deploys here are automatic while migrations are not, so a
revision must be safe against the *currently deployed* code as well as the new code.
Pre-`0007` code neither reads nor writes either column and no existing row is rewritten.

⚠️ **`retired_at` was FOLDED INTO this revision rather than stacked as an `0008`, and
that was checked rather than assumed.** At the time of the amendment this file had never
been committed to any branch (`git log --all -- <this path>` was empty), so no ref
`migrations/env.py` could have checked out carried it, and both environments read back
`0006 (head)` from their last `migrate.yml` runs (dev run 32653834390, production run
32654384094, both 2026-08-23). An undeployed revision is editable; a deployed one never
is, and if `alembic_version` had said `0007` anywhere this would be `0008` instead.

## Why `substitution_hint` exists — PR #10, the exercise library

The equipment vocabulary has **no `bodyweight` row**, deliberately (CLAUDE.md, "There is
deliberately no `bodyweight` equipment row"). Two obligations replace it, and this is the
schema half of the second: an exercise must be able to carry its own "no dumbbell? a
packed backpack" hint, **on the exercise row, next to the movement it applies to** rather
than in a vocabulary — because the honest substitute for a dumbbell is not the honest
substitute for a foam roller, and a shared lookup would have to pretend otherwise.

⚠️ **It is NULL for every finger-loading protocol, and that is a safety boundary, not an
omission.** A hangboard, campus-board or no-hang exercise gets no hint, because every
substitute for a real edge is an improvised one — a home-made hangboard, a door frame, a
towel hang — and that is the most injury-prone thing a climber can rig. The rule is
enforced in `tests/test_exercise_library.py`, not here: a CHECK cannot see which equipment
rows an exercise requires.

## 255, and no Pydantic mirror

`server.models.SUBSTITUTION_HINT_MAX`, spelled out below because a revision must not
depend on a constant a later PR could retune. It is the same bound the lookup tables'
`description` uses, because it is the same kind of thing — one sentence of display text.
There is deliberately **no bound in `server/fields.py`**: this is authored content written
by the seed, never a field on a request, so there is no edge to validate at. It is still
untrusted on OUTPUT and is never rendered as HTML.

## Why `retired_at` exists — logical retirement is the FALLBACK, not the rule

Kilian's call: an exercise dropped from `server/domain/exercises.py` should really be
gone, not merely hidden. `server/contentseed.py` therefore **deletes** an unauthored
exercise outright when nothing references it. This column is what happens when something
does: `session_block.exercise_id` and `logged_set.exercise_id` are `NO ACTION` foreign
keys, so Postgres refuses to delete an exercise that appears in somebody's plan or
training diary — and that refusal is correct, because a diary that forgets what you did is
worse than a library with one row too many. Such a row gets `retired_at` set instead, is
filtered out of `GET /api/library`, and stays in the table so the history that points at it
still resolves.

`TIMESTAMPTZ`, like every other timestamp in this schema (`Base.type_annotation_map` pins
it repo-wide). A timestamp rather than a boolean because "when did this leave the library"
is the question a diary entry from six months ago actually raises, and a boolean cannot
answer it. No index: the only reader is the library endpoint, which reads the whole table.

## `equipment_reviewed_at` is untouched

Still retired, still not dropped (see `0006`). This revision goes nowhere near
`user_profile`, and `tests/test_migrations_additive.py` would refuse it if it did.

Hand-written, like 0001-0006, and **no database was touched to produce it**: `alembic
upgrade` and `alembic check` have not been run here. CI proves both against its
`postgres:17-alpine` service container.

## `downgrade()`

Exactly reversible: neither column existed before this revision, so dropping them loses
nothing that predates it. `exercise` is reference content and holds no user rows, which is
what makes a `drop_column` on it legal where the same op on `user_profile` would be
refused. Local and CI use only — production never downgrades.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors `server.models.SUBSTITUTION_HINT_MAX`. See the module docstring.
SUBSTITUTION_HINT_MAX = 255


def upgrade() -> None:
    op.add_column(
        "exercise",
        sa.Column("substitution_hint", sa.String(length=SUBSTITUTION_HINT_MAX), nullable=True),
    )
    op.add_column(
        "exercise",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exercise", "retired_at")
    op.drop_column("exercise", "substitution_hint")
