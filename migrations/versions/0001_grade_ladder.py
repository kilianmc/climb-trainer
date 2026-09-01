"""grade ladder: grade_system + grade, and the discipline enum

Revision ID: 0001
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

discipline = postgresql.ENUM("boulder", "sport", name="discipline", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    discipline.create(bind, checkfirst=True)

    op.create_table(
        "grade_system",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("discipline", discipline, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_grade_system"),
        sa.UniqueConstraint("key", name="uq_grade_system_key"),
    )

    op.create_table(
        "grade",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grade_system_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["grade_system_id"],
            ["grade_system.id"],
            name="fk_grade_grade_system_id_grade_system",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_grade"),
        sa.UniqueConstraint("grade_system_id", "label", name="uq_grade_grade_system_id_label"),
        sa.UniqueConstraint("grade_system_id", "ordinal", name="uq_grade_grade_system_id_ordinal"),
    )
    op.create_index("ix_grade_ordinal", "grade", ["ordinal"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_grade_ordinal", table_name="grade")
    op.drop_table("grade")
    op.drop_table("grade_system")
    discipline.drop(op.get_bind(), checkfirst=True)
