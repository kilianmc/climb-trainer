"""invites: per-person registration codes, hashed

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-19

Registration was wide open: `EmailStr` validates syntax, so nothing proved control of an
address and anyone could create an account on production (issue #35). This table is the
gate — see `server/auth/invites.py`.

Hand-written, like 0001 and 0002, because there is no Postgres on the machine this was
written on to autogenerate against. CI proves it: `alembic upgrade head` against a
throwaway `postgres:17-alpine`, then `alembic check` against the models.

Constraint names are spelled out and match what `NAMING_CONVENTION` in server/models.py
derives — except the two CHECK constraints, which pass their **bare** names (`max_uses_positive`)
because `op.create_table` applies the convention itself and a pre-derived
`ck_invite_max_uses_positive` comes out as `ck_invite_ck_invite_max_uses_positive`. Alembic
1.19 does compare CHECK constraints by name, so that mistake is an `alembic check` failure,
not a cosmetic one. Verified against a throwaway Postgres before this file was committed.

**Nothing here is a data migration.** The table starts empty and `app_user.invite_id` is
nullable, so an existing deployment keeps every account it has and has no usable invite
until one is minted with `python -m server.admin create-invite`. That is the expected
half-live window (expand -> deploy -> contract): after this revision and before the deploy
that gates `register`, registration still works as it did.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invite",
        sa.Column("id", sa.Integer(), nullable=False),
        # sha256 hex of the code. The plaintext is never stored — a database dump must
        # not be a set of working invites.
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        # Human label ("Bob, from the gym"), which is what makes a use attributable.
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("max_uses", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("uses", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        # NULL = no expiry. TIMESTAMPTZ, never naive.
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("max_uses >= 1", name="max_uses_positive"),
        # The structural half of the limit. `server/auth/invites.py` takes a row lock so
        # two concurrent registrations cannot both spend the last use; this is what makes
        # a bug in that logic fail loudly instead of over-issuing.
        sa.CheckConstraint("uses >= 0 AND uses <= max_uses", name="uses_within_max"),
        sa.PrimaryKeyConstraint("id", name="pk_invite"),
        # Unique because it is the lookup key on every registration, and because two rows
        # sharing a digest would make "which invite was spent" ambiguous. The unique index
        # is also the index the lookup uses — no separate one is needed.
        sa.UniqueConstraint("code_hash", name="uq_invite_code_hash"),
    )

    # Attribution. Nullable so existing accounts and the demo account are untouched, and
    # RESTRICT so a spent invite cannot be deleted out from under the record of who used it.
    op.add_column("app_user", sa.Column("invite_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_app_user_invite_id_invite",
        "app_user",
        "invite",
        ["invite_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_app_user_invite_id_invite", "app_user", type_="foreignkey")
    op.drop_column("app_user", "invite_id")
    # Last: app_user's foreign key referenced it.
    op.drop_table("invite")
