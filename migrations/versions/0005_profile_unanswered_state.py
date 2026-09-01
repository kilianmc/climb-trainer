"""user_profile: unanswered is NULL; two *_reviewed_at columns; one open injury per area

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

discipline = postgresql.ENUM("boulder", "sport", name="discipline", create_type=False)

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
