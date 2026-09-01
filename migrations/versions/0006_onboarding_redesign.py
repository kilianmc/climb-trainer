"""user_profile: current grade, strength/weakness aspects, display name; grade_system.sort_order

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISPLAY_NAME_MAX = 64

_GRADE_SYSTEM_SORT_ORDER: tuple[tuple[str, int], ...] = (
    ("font", 0),
    ("v_scale", 1),
    ("french", 2),
    ("yds", 3),
)


def upgrade() -> None:
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

    op.add_column("grade_system", sa.Column("sort_order", sa.SmallInteger(), nullable=True))
    for key, position in _GRADE_SYSTEM_SORT_ORDER:
        op.execute(
            sa.text("UPDATE grade_system SET sort_order = :position WHERE key = :key").bindparams(
                position=position, key=key
            )
        )
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
