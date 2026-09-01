"""plan: current_grade_id + generator_caveats, session_block rest, one-active index

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ONE_ACTIVE_INDEX = "uq_plan_one_active_per_user"
ACTIVE_PLAN_PREDICATE = "activated_at IS NOT NULL AND abandoned_at IS NULL AND completed_at IS NULL"


def upgrade() -> None:
    op.add_column("plan", sa.Column("current_grade_id", sa.Integer(), nullable=True))
    op.add_column(
        "plan",
        sa.Column("generator_caveats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
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
