"""exercise: substitution_hint, retired_at

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
