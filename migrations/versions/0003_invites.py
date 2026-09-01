"""invites: per-person registration codes, hashed

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-19
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
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("max_uses", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("uses", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("max_uses >= 1", name="max_uses_positive"),
        sa.CheckConstraint("uses >= 0 AND uses <= max_uses", name="uses_within_max"),
        sa.PrimaryKeyConstraint("id", name="pk_invite"),
        sa.UniqueConstraint("code_hash", name="uq_invite_code_hash"),
    )

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
    op.drop_table("invite")
