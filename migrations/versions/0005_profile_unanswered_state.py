"""user_profile: unanswered is NULL; two *_reviewed_at columns; one open injury per area

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-21

Expand -> deploy -> contract. Deploys are automatic here and migrations are not, so a
revision must be safe against the *currently deployed* code as well as the new code.

## Why this exists

`0004` made `user_profile.primary_discipline`, `sessions_per_week` and
`available_weekdays` `NOT NULL`. Onboarding (PR #9) writes that row **one step at a
time** — which is what lets an abandoned setup resume rather than restart — so the row
exists before those questions have been asked, and `NOT NULL` forced the write path to
invent placeholders. Two of them were indistinguishable from real answers:
`sessions_per_week = 3` is a perfectly plausible reply, so a completion bar counting "has
a value" credited work nobody had done, and the plan generator would have read a number
the user never chose. Kilian's call: fix the schema, not the reader.

## The rule for the two `*_reviewed_at` columns

**A step needs a `*_reviewed_at` column exactly when ZERO ROWS is a legitimate answer.**
Two of the five qualify, and the same failure hit both:

- `injuries_reviewed_at` — "nothing is hurting" writes no `user_injury` rows, so an empty
  table means "asked, nothing wrong" or "never asked" and nothing can tell them apart.
- `equipment_reviewed_at` — "I own none of this" writes no `user_equipment` rows. **For an
  outdoor-only climber with no gym membership this was a hard dead-end**: every one of the
  fifteen rows seeded at the time was an indoor wall or a piece of kit, so there was nothing
  they could honestly tick — a permanently disabled Continue button, 100% unreachable, and a
  dashboard nagging them about a step they had already answered correctly. The vocabulary has
  since gained `outdoor_boulders` and `outdoor_routes` too; that half needed no migration.

The other three do NOT get one, and adding a third would be cargo-culting:

- **aspects** — submitting the step always writes eight rows, so `>= 1 rating` already
  proves the step was taken;
- **target grade** and **availability** — scalar columns whose own NULL carries it, which
  is what the nullability half of this revision is for.

PR #9 shipped a device-local `localStorage` flag for the injuries case as a stopgap; these
columns replace it, and the flag and its module are deleted in the same PR.

## Safe against the currently deployed code

- **Dropping `NOT NULL` widens what the column accepts.** Code that always writes a value
  keeps working unchanged; nothing existing starts failing. It is the additive direction.
- **Both `*_reviewed_at` columns are nullable with no default**, so every existing row gets
  NULL and no row is rewritten. NULL reads as "never asked", which is the truth for every
  profile that predates this revision.
- **The partial unique index is safe to add because neither database has a single
  `user_injury` row** (verified before writing this: `0004` created the table days ago
  and no endpoint could write to it until PR #9). On a table with rows, `CREATE UNIQUE
  INDEX` would fail on the first duplicate instead of quietly succeeding — which is the
  correct behaviour, but it would mean this revision needs a de-duplication step first.
  It does not need one, and this paragraph is why.

Hand-written, like 0001-0004, because there is no Postgres on this machine to
autogenerate against. CI proves it: `alembic upgrade head` against a throwaway
`postgres:17-alpine`, then `alembic check` against the models.

`op.alter_column` needs `existing_type` for the enum column so Alembic emits a bare
`ALTER COLUMN ... DROP NOT NULL` rather than trying to reason about the type; the ENUM is
declared with `create_type=False` for the same reason `0004`'s are — nothing here creates
or drops a type.

## ⚠️ `downgrade()` cannot restore `NOT NULL` on its own, and does not pretend to

Going back needs a value for every row where the column is now NULL, and **there is no
correct value to invent** — that is the entire point of the change. So the downgrade
backfills exactly the placeholders `0004`-era code used (`boulder`, `3`, `0`) and says so
here, because a downgrade that wrote a *different* guess would be inventing training
input under a name that reads like a repair.

**A downgrade is therefore lossy: after it runs, "unanswered" reads as "3 sessions a week
on no days, bouldering", and nothing can recover which rows were guessed.** It is written
so `alembic downgrade` completes rather than aborting halfway with `column contains null
values`, and it is deliberately obvious rather than clever. It is also untestable here and
untested in CI (nothing runs `downgrade`, and `migrate.yml` offers no downgrade action);
recovery from a bad upgrade is a Neon branch restore, not this function.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Declared, never created: `0001` owns this type. See the module docstring.
discipline = postgresql.ENUM("boulder", "sport", name="discipline", create_type=False)

# The 0004-era placeholders, named so `downgrade()` cannot use a different set by accident.
_LEGACY_DISCIPLINE = "boulder"
_LEGACY_SESSIONS_PER_WEEK = 3
_LEGACY_WEEKDAYS = 0


def upgrade() -> None:
    op.alter_column("user_profile", "primary_discipline", existing_type=discipline, nullable=True)
    op.alter_column(
        "user_profile", "sessions_per_week", existing_type=sa.SmallInteger(), nullable=True
    )
    op.alter_column(
        "user_profile", "available_weekdays", existing_type=sa.SmallInteger(), nullable=True
    )
    op.add_column(
        "user_profile",
        sa.Column("equipment_reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("injuries_reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Postgres has no partial unique CONSTRAINT, so this is a partial unique INDEX. The
    # predicate is what keeps injury HISTORY legal: any number of resolved rows per area,
    # at most one open one.
    op.create_index(
        "uq_user_injury_open_area",
        "user_injury",
        ["user_id", "injury_area_id"],
        unique=True,
        postgresql_where=sa.text("resolved_on IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_injury_open_area", table_name="user_injury")
    op.drop_column("user_profile", "injuries_reviewed_at")
    op.drop_column("user_profile", "equipment_reviewed_at")
    # Backfill BEFORE restoring NOT NULL, or the ALTER aborts on the first NULL row. These
    # are the placeholders the pre-0005 code wrote; see the docstring for why this is lossy.
    op.execute(
        sa.text(
            "UPDATE user_profile SET primary_discipline = :discipline "
            "WHERE primary_discipline IS NULL"
        ).bindparams(discipline=_LEGACY_DISCIPLINE)
    )
    op.execute(
        sa.text(
            "UPDATE user_profile SET sessions_per_week = :sessions WHERE sessions_per_week IS NULL"
        ).bindparams(sessions=_LEGACY_SESSIONS_PER_WEEK)
    )
    op.execute(
        sa.text(
            "UPDATE user_profile SET available_weekdays = :weekdays "
            "WHERE available_weekdays IS NULL"
        ).bindparams(weekdays=_LEGACY_WEEKDAYS)
    )
    op.alter_column(
        "user_profile", "available_weekdays", existing_type=sa.SmallInteger(), nullable=False
    )
    op.alter_column(
        "user_profile", "sessions_per_week", existing_type=sa.SmallInteger(), nullable=False
    )
    op.alter_column("user_profile", "primary_discipline", existing_type=discipline, nullable=False)
