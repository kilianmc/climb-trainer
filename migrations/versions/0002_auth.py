"""auth: app_user, auth_session (refresh families), rate_limit

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13

The authentication schema: accounts, the refresh-token rotation families that back
`server/auth/refresh.py`, and the Postgres-backed fixed-window rate limiter.

Hand-written, like 0001, because there is no Postgres on the machine this was written
on to autogenerate against. CI is what proves it: `alembic upgrade head` against a
throwaway `postgres:17-alpine`, then `alembic check` to prove it matches the models.

Constraint and index names are spelled out explicitly and match what
`NAMING_CONVENTION` in server/models.py derives. If they drift, `alembic check` fails
in CI and a future `op.drop_constraint` has nothing stable to name.

No enum type is created here: `is_demo` is a plain boolean and `scope` lives only in
the JWT, never in a column, so there is nothing for the `create_type=False` dance that
0001 needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), nullable=False),
        # 254 = the RFC 5321 maximum. Stored lowercased and stripped by every write
        # path, because citext is not available here — see server/models.py.
        sa.Column("email", sa.String(length=254), nullable=False),
        # NULLABLE on purpose: the seeded demo account has no password and must never
        # be reachable through /api/auth/login.
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        # TIMESTAMPTZ (never naive), defaulted by the database's clock rather than a
        # serverless function's.
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )

    op.create_table(
        "auth_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        # sha256 hex of the opaque refresh token. The plaintext is never stored.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "issued_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # Set on rotation. A token presented with this already set has been replayed.
        sa.Column("rotated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # CASCADE so deleting an account cannot leave live refresh tokens behind.
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name="fk_auth_session_user_id_app_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_session"),
        sa.UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
    )
    # Revoking a whole family on reuse detection is one indexed UPDATE.
    op.create_index("ix_auth_session_family_id", "auth_session", ["family_id"], unique=False)
    op.create_index(
        "ix_auth_session_user_id_family_id",
        "auth_session",
        ["user_id", "family_id"],
        unique=False,
    )

    op.create_table(
        "rate_limit",
        # The composite PK IS the window, which is what lets the limiter be a single
        # INSERT ... ON CONFLICT DO UPDATE with no read-then-write race.
        sa.Column("bucket", sa.String(length=128), nullable=False),
        sa.Column("window_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", "window_start", name="pk_rate_limit"),
    )


def downgrade() -> None:
    op.drop_table("rate_limit")
    op.drop_index("ix_auth_session_user_id_family_id", table_name="auth_session")
    op.drop_index("ix_auth_session_family_id", table_name="auth_session")
    op.drop_table("auth_session")
    # Last: auth_session's foreign key references it.
    op.drop_table("app_user")
