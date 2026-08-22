"""user_profile: current grade, strength/weakness aspects, display name; grade_system.sort_order

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22

Expand -> deploy -> contract. Deploys are automatic here and migrations are not, so a
revision must be safe against the *currently deployed* code as well as the new code. Every
column added below is nullable with no default, so every existing row reads NULL and no row
is rewritten — and NULL is the honest value for all four, because nothing has asked yet.

## Why this exists — issue #54 (onboarding redesign) and issue #55 (grade system order)

Four new `user_profile` columns and one new `grade_system` column.

### The three answers that replaced eight sliders

The aspect step was **eight 1-5 self-ratings**, and it was the step most likely to hand the
plan generator garbage: eight middling guesses are indistinguishable from eight real
answers. It is replaced by three questions anybody can answer, and each needs a column:

- **`current_grade_id`** — "I climb 6c" plus a 7a target tells the generator far more than
  any self-rating does, because a 6c climber is measurably closer to 7a than a 6a climber
  is. ⚠️ It must sit on the same DISCIPLINE as the target grade: the ordinal ladders are
  disjoint per discipline and `server.domain.grades.convert` raises `CrossDisciplineError`
  rather than compare across them. `server/profile/routes.py` enforces that at the edge —
  the schema cannot, because a CHECK cannot follow two foreign keys into `grade`.
- **`strength_aspect_id` / `weakness_aspect_id`** — one of each, chosen from the eight
  aspects. `user_aspect_rating` keeps the eight scores as optional detail behind a
  disclosure; its docstring used to claim it was "the generator's only picture of a
  weakness" and this revision is what makes that false.

Plus **`display_name`**, which the account screen offers with the user's email as a
starting value. It is free text and therefore a row on CLAUDE.md's free-text inventory,
bounded at `DISPLAY_NAME_MAX` (64) in the column *and* at the edge in `server/fields.py`.

### `grade_system.sort_order` (issue #55)

`GET /api/vocabulary` ordered grade systems by **serial `id`** while its three sibling
lookup tables order by an explicit `sort_order`. That is latent, not live: insert a system
mid-tuple and CI — always a fresh database, so serials follow declaration order — keeps
passing, while dev and production keep their old serials and render the new system LAST.
The test pinning declaration order would then assert a property the real databases do not
have.

**This is the one column here that needs a backfill**, because it is `NOT NULL` in the
model and `grade_system` already holds four rows. Three steps, in the only safe order: add
nullable, backfill by `key`, then `SET NOT NULL`. The values are the tuple positions in
`server.domain.grades.GRADE_SYSTEMS`, **hardcoded rather than imported** — a revision has to
reproduce the same result forever, and importing domain code would make this file's
behaviour depend on a tuple a later PR may reorder. `server/seed.py` writes the same values
from that tuple's position from now on.

`grade_system` is reference data: `tests/test_migrations_additive.py` does not protect it
(nothing in it reaches `app_user` through a foreign key), which is what makes a
`SET NOT NULL` here legal where the same op on `user_profile` would be refused.

## ⚠️ `equipment_reviewed_at` is RETIRED and is deliberately NOT dropped

Issue #54 removed the equipment step from onboarding, so nothing reads or writes
`user_profile.equipment_reviewed_at` any more: it is gone from `ProfileResponse`, from
`ProfilePatchRequest` and from the client's completion maths. The column stays.

Two reasons, and either alone is sufficient:

1. **`user_profile` holds real user rows**, so `op.drop_column` on it is precisely what
   `tests/test_migrations_additive.py` refuses. That guard is not in the way here — it is
   correct.
2. **Expand -> deploy -> contract.** The currently deployed code still selects that column;
   dropping it in the same revision that stops reading it would break every request served
   between the migration and the deploy.

The contract half is a later revision, once a deployed-and-verified `0006` has proved
nothing reads it. `user_equipment` and every `exercise_equipment` requirement are untouched:
issue #54 defers the owned-vs-lacked question to PR #10, where the alternatives lookup is
what gives a "I don't have this" flag its meaning.

## Safe against the currently deployed code

- Four nullable columns with no default: pre-`0006` code neither writes nor reads them, and
  no existing row changes.
- The `strength_and_weakness_differ` CHECK passes vacuously for every existing row, because
  both columns are NULL everywhere the moment it is created. `IS DISTINCT FROM` rather than
  `<>`: `NULL <> NULL` is NULL, which a CHECK accepts, so the naive spelling would pass in
  exactly the state these columns spend most of their life in.
- `grade_system.sort_order` is backfilled before it is made `NOT NULL`, so the `ALTER` cannot
  abort on a NULL row. Pre-`0006` code never inserts a `grade_system` row outside the seed.

Hand-written, like 0001-0005, because there is no Postgres on this machine to autogenerate
against — and this revision was written under an explicit instruction not to touch a
database, so **`alembic upgrade` and `alembic check` have NOT been run against it here**.
CI proves both: `alembic upgrade head` against a throwaway `postgres:17-alpine`, then
`alembic check` against the models.

## `downgrade()`

Reversible without inventing anything, which is unusual here and worth stating: every
column it drops was added by this revision, so no user answer predates it. `sort_order` is
dropped whole rather than made nullable again — the column did not exist before `0006`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `user_profile.display_name` — mirrors `server.models.DISPLAY_NAME_MAX`, spelled out here
# because a revision must not depend on a constant a later PR could retune.
DISPLAY_NAME_MAX = 64

# The tuple positions in `server.domain.grades.GRADE_SYSTEMS` at the time this revision was
# written. Hardcoded on purpose: see the module docstring.
_GRADE_SYSTEM_SORT_ORDER: tuple[tuple[str, int], ...] = (
    ("font", 0),
    ("v_scale", 1),
    ("french", 2),
    ("yds", 3),
)


def upgrade() -> None:
    # ---------------------------------------------------------------- user_profile
    op.add_column("user_profile", sa.Column("current_grade_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_user_profile_current_grade_id_grade"),
        "user_profile",
        "grade",
        ["current_grade_id"],
        ["id"],
    )
    op.add_column("user_profile", sa.Column("strength_aspect_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_user_profile_strength_aspect_id_climbing_aspect"),
        "user_profile",
        "climbing_aspect",
        ["strength_aspect_id"],
        ["id"],
    )
    op.add_column("user_profile", sa.Column("weakness_aspect_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_user_profile_weakness_aspect_id_climbing_aspect"),
        "user_profile",
        "climbing_aspect",
        ["weakness_aspect_id"],
        ["id"],
    )
    op.add_column(
        "user_profile",
        sa.Column("display_name", sa.String(length=DISPLAY_NAME_MAX), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_user_profile_strength_and_weakness_differ"),
        "user_profile",
        "strength_aspect_id IS NULL OR weakness_aspect_id IS NULL "
        "OR strength_aspect_id IS DISTINCT FROM weakness_aspect_id",
    )

    # ---------------------------------------------------------------- grade_system
    # Nullable first, so the ALTER below has something to check rather than something to
    # abort on. Four rows, reference data, seeded — see the docstring.
    op.add_column("grade_system", sa.Column("sort_order", sa.SmallInteger(), nullable=True))
    for key, position in _GRADE_SYSTEM_SORT_ORDER:
        op.execute(
            sa.text("UPDATE grade_system SET sort_order = :position WHERE key = :key").bindparams(
                position=position, key=key
            )
        )
    # Anything the four keys above did not match — a system added to the tuple between
    # `0005` and this revision — sorts after them rather than blocking the ALTER.
    op.execute(sa.text("UPDATE grade_system SET sort_order = id WHERE sort_order IS NULL"))
    op.alter_column("grade_system", "sort_order", existing_type=sa.SmallInteger(), nullable=False)


def downgrade() -> None:
    op.drop_column("grade_system", "sort_order")
    op.drop_constraint(
        op.f("ck_user_profile_strength_and_weakness_differ"), "user_profile", type_="check"
    )
    op.drop_column("user_profile", "display_name")
    op.drop_constraint(
        op.f("fk_user_profile_weakness_aspect_id_climbing_aspect"),
        "user_profile",
        type_="foreignkey",
    )
    op.drop_column("user_profile", "weakness_aspect_id")
    op.drop_constraint(
        op.f("fk_user_profile_strength_aspect_id_climbing_aspect"),
        "user_profile",
        type_="foreignkey",
    )
    op.drop_column("user_profile", "strength_aspect_id")
    op.drop_constraint(
        op.f("fk_user_profile_current_grade_id_grade"), "user_profile", type_="foreignkey"
    )
    op.drop_column("user_profile", "current_grade_id")
