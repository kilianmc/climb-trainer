"""profile, exercise library, plan tree, activity/logging and the training diary

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

discipline = postgresql.ENUM("boulder", "sport", name="discipline", create_type=False)
activity_kind = postgresql.ENUM(
    "climbing",
    "cardio",
    "strength",
    "mobility",
    "other",
    name="activity_kind",
    create_type=False,
)
ascent_style = postgresql.ENUM(
    "onsight",
    "flash",
    "redpoint",
    "top_rope",
    "repeat",
    "attempt",
    name="ascent_style",
    create_type=False,
)
protocol_kind = postgresql.ENUM(
    "max_hang",
    "repeaters",
    "intervals",
    "circuit",
    "limit_boulder",
    "straight_sets",
    "laps",
    "hold",
    "other",
    name="protocol_kind",
    create_type=False,
)
phase = postgresql.ENUM(
    "base",
    "strength",
    "power",
    "power_endurance",
    "performance",
    "deload",
    "taper",
    name="phase",
    create_type=False,
)
session_status = postgresql.ENUM(
    "planned",
    "in_progress",
    "completed",
    "skipped",
    "rescheduled",
    name="session_status",
    create_type=False,
)

NEW_ENUM_TYPES = (activity_kind, ascent_style, protocol_kind, phase, session_status)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in NEW_ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    op.create_unique_constraint("uq_grade_id_ordinal", "grade", ["id", "ordinal"])

    op.create_table(
        "ascent_tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ascent_tag")),
        sa.UniqueConstraint("key", name=op.f("uq_ascent_tag_key")),
    )
    op.create_table(
        "climbing_aspect",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_climbing_aspect")),
        sa.UniqueConstraint("key", name=op.f("uq_climbing_aspect_key")),
    )
    op.create_table(
        "equipment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment")),
        sa.UniqueConstraint("key", name=op.f("uq_equipment_key")),
    )
    op.create_table(
        "injury_area",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_injury_area")),
        sa.UniqueConstraint("key", name=op.f("uq_injury_area_key")),
    )
    op.create_table(
        "exercise",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=96), nullable=False),
        sa.Column("climbing_aspect_id", sa.Integer(), nullable=False),
        sa.Column("protocol_kind", protocol_kind, nullable=False),
        sa.Column("discipline", discipline, nullable=True),
        sa.Column("instructions", sa.String(length=2000), nullable=False),
        sa.Column("media_url", sa.String(length=512), nullable=True),
        sa.Column("progression_of_id", sa.Integer(), nullable=True),
        sa.Column("regression_of_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["climbing_aspect_id"],
            ["climbing_aspect.id"],
            name=op.f("fk_exercise_climbing_aspect_id_climbing_aspect"),
        ),
        sa.ForeignKeyConstraint(
            ["progression_of_id"],
            ["exercise.id"],
            name=op.f("fk_exercise_progression_of_id_exercise"),
        ),
        sa.ForeignKeyConstraint(
            ["regression_of_id"],
            ["exercise.id"],
            name=op.f("fk_exercise_regression_of_id_exercise"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exercise")),
        sa.UniqueConstraint("key", name=op.f("uq_exercise_key")),
    )
    op.create_index(
        "ix_exercise_climbing_aspect_id", "exercise", ["climbing_aspect_id"], unique=False
    )
    op.create_table(
        "exercise_contraindication",
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("injury_area_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name=op.f("fk_exercise_contraindication_exercise_id_exercise"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["injury_area_id"],
            ["injury_area.id"],
            name=op.f("fk_exercise_contraindication_injury_area_id_injury_area"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "exercise_id", "injury_area_id", name=op.f("pk_exercise_contraindication")
        ),
    )
    op.create_index(
        "ix_exercise_contraindication_injury_area_id",
        "exercise_contraindication",
        ["injury_area_id"],
        unique=False,
    )
    op.create_table(
        "exercise_equipment",
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            name=op.f("fk_exercise_equipment_equipment_id_equipment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name=op.f("fk_exercise_equipment_exercise_id_exercise"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("exercise_id", "equipment_id", name=op.f("pk_exercise_equipment")),
    )
    op.create_index(
        "ix_exercise_equipment_equipment_id", "exercise_equipment", ["equipment_id"], unique=False
    )
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("discipline", discipline, nullable=False),
        sa.Column("target_grade_id", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("week_count", sa.SmallInteger(), nullable=False),
        sa.Column("generator_version", sa.String(length=32), nullable=False),
        sa.Column("generator_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("abandoned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("week_count BETWEEN 1 AND 52", name=op.f("ck_plan_week_count_in_range")),
        sa.ForeignKeyConstraint(
            ["target_grade_id"], ["grade.id"], name=op.f("fk_plan_target_grade_id_grade")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_plan_user_id_app_user"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan")),
    )
    op.create_index("ix_plan_user_id_created_at", "plan", ["user_id", "created_at"], unique=False)
    op.create_table(
        "prescription_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("phase", phase, nullable=False),
        sa.Column("sets", sa.SmallInteger(), nullable=False),
        sa.Column("reps", sa.SmallInteger(), nullable=True),
        sa.Column("work_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("rest_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("rest_between_sets_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("intensity_pct", sa.SmallInteger(), nullable=True),
        sa.Column("target_rpe", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint(
            "intensity_pct IS NULL OR (intensity_pct BETWEEN 1 AND 200)",
            name=op.f("ck_prescription_template_intensity_pct_sane"),
        ),
        sa.CheckConstraint("sets >= 1", name=op.f("ck_prescription_template_sets_positive")),
        sa.CheckConstraint(
            "target_rpe IS NULL OR (target_rpe BETWEEN 1 AND 10)",
            name=op.f("ck_prescription_template_target_rpe_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name=op.f("fk_prescription_template_exercise_id_exercise"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prescription_template")),
        sa.UniqueConstraint(
            "exercise_id", "phase", name=op.f("uq_prescription_template_exercise_id_phase")
        ),
    )
    op.create_table(
        "user_aspect_rating",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("climbing_aspect_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column(
            "rated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "score BETWEEN 1 AND 5", name=op.f("ck_user_aspect_rating_score_in_range")
        ),
        sa.ForeignKeyConstraint(
            ["climbing_aspect_id"],
            ["climbing_aspect.id"],
            name=op.f("fk_user_aspect_rating_climbing_aspect_id_climbing_aspect"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_user_aspect_rating_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "climbing_aspect_id", name=op.f("pk_user_aspect_rating")
        ),
    )
    op.create_table(
        "user_equipment",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            name=op.f("fk_user_equipment_equipment_id_equipment"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_user_equipment_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "equipment_id", name=op.f("pk_user_equipment")),
    )
    op.create_table(
        "user_injury",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("injury_area_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("resolved_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "resolved_on IS NULL OR resolved_on >= started_on",
            name=op.f("ck_user_injury_resolved_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["injury_area_id"],
            ["injury_area.id"],
            name=op.f("fk_user_injury_injury_area_id_injury_area"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_user_injury_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_injury")),
    )
    op.create_index("ix_user_injury_user_id", "user_injury", ["user_id"], unique=False)
    op.create_table(
        "user_profile",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("primary_discipline", discipline, nullable=False),
        sa.Column("target_grade_id", sa.Integer(), nullable=True),
        sa.Column("sessions_per_week", sa.SmallInteger(), nullable=False),
        sa.Column("available_weekdays", sa.SmallInteger(), nullable=False),
        sa.Column(
            "show_body_metrics", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "available_weekdays BETWEEN 0 AND 127",
            name=op.f("ck_user_profile_available_weekdays_is_7_bits"),
        ),
        sa.CheckConstraint(
            "sessions_per_week BETWEEN 1 AND 7",
            name=op.f("ck_user_profile_sessions_per_week_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["target_grade_id"], ["grade.id"], name=op.f("fk_user_profile_target_grade_id_grade")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_user_profile_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_profile")),
    )
    op.create_table(
        "mesocycle",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("phase", phase, nullable=False),
        sa.Column("start_week", sa.SmallInteger(), nullable=False),
        sa.Column("end_week", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "end_week >= start_week", name=op.f("ck_mesocycle_end_week_after_start")
        ),
        sa.CheckConstraint("start_week >= 1", name=op.f("ck_mesocycle_start_week_positive")),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plan.id"], name=op.f("fk_mesocycle_plan_id_plan"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mesocycle")),
        sa.UniqueConstraint("id", "plan_id", name=op.f("uq_mesocycle_id_plan_id")),
        sa.UniqueConstraint("plan_id", "start_week", name=op.f("uq_mesocycle_plan_id_start_week")),
    )
    op.create_table(
        "microcycle",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mesocycle_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("week_no", sa.SmallInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("is_deload", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("week_no >= 1", name=op.f("ck_microcycle_week_no_positive")),
        sa.ForeignKeyConstraint(
            ["mesocycle_id", "plan_id"],
            ["mesocycle.id", "mesocycle.plan_id"],
            name="fk_microcycle_mesocycle_id_plan_id_mesocycle",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_microcycle")),
        sa.UniqueConstraint("plan_id", "week_no", name=op.f("uq_microcycle_plan_id_week_no")),
    )
    op.create_index(
        "ix_microcycle_mesocycle_id_plan_id",
        "microcycle",
        ["mesocycle_id", "plan_id"],
        unique=False,
    )
    op.create_table(
        "planned_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("microcycle_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=False),
        sa.Column(
            "activity_kind", activity_kind, server_default=sa.text("'climbing'"), nullable=False
        ),
        sa.Column("status", session_status, server_default=sa.text("'planned'"), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("estimated_minutes", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_planned_session_weekday_in_range")
        ),
        sa.ForeignKeyConstraint(
            ["microcycle_id"],
            ["microcycle.id"],
            name=op.f("fk_planned_session_microcycle_id_microcycle"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_session")),
        sa.UniqueConstraint(
            "microcycle_id", "weekday", name=op.f("uq_planned_session_microcycle_id_weekday")
        ),
    )
    op.create_index(
        "ix_planned_session_scheduled_on", "planned_session", ["scheduled_on"], unique=False
    )
    op.create_table(
        "activity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("activity_kind", activity_kind, nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("rpe", sa.SmallInteger(), nullable=True),
        sa.Column(
            "srpe_load",
            sa.Integer(),
            sa.Computed("rpe::integer * duration_minutes", persisted=True),
            nullable=True,
        ),
        sa.Column("planned_session_id", sa.Integer(), nullable=True),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 1 AND 1440", name=op.f("ck_activity_duration_in_range")
        ),
        sa.CheckConstraint(
            "rpe IS NULL OR (rpe BETWEEN 1 AND 10)", name=op.f("ck_activity_rpe_in_range")
        ),
        sa.ForeignKeyConstraint(
            ["planned_session_id"],
            ["planned_session.id"],
            name=op.f("fk_activity_planned_session_id_planned_session"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_activity_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity")),
        sa.UniqueConstraint("id", "activity_kind", name=op.f("uq_activity_id_activity_kind")),
        sa.UniqueConstraint("user_id", "client_uuid", name=op.f("uq_activity_user_id_client_uuid")),
    )
    op.create_index(
        "ix_activity_planned_session_id", "activity", ["planned_session_id"], unique=False
    )
    op.create_index(
        "ix_activity_user_id_occurred_on", "activity", ["user_id", "occurred_on"], unique=False
    )
    op.create_table(
        "session_block",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("planned_session_id", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.SmallInteger(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("protocol_kind", protocol_kind, nullable=False),
        sa.Column("rest_after_seconds", sa.SmallInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["exercise_id"], ["exercise.id"], name=op.f("fk_session_block_exercise_id_exercise")
        ),
        sa.ForeignKeyConstraint(
            ["planned_session_id"],
            ["planned_session.id"],
            name=op.f("fk_session_block_planned_session_id_planned_session"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_block")),
        sa.UniqueConstraint(
            "planned_session_id",
            "order_index",
            name=op.f("uq_session_block_planned_session_id_order_index"),
        ),
    )
    op.create_table(
        "logged_session",
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column(
            "activity_kind", activity_kind, server_default=sa.text("'climbing'"), nullable=False
        ),
        sa.Column("discipline", discipline, nullable=False),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "activity_kind = 'climbing'", name=op.f("ck_logged_session_activity_kind_is_climbing")
        ),
        sa.ForeignKeyConstraint(
            ["activity_id", "activity_kind"],
            ["activity.id", "activity.activity_kind"],
            name="fk_logged_session_activity_id_activity_kind_activity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("activity_id", name=op.f("pk_logged_session")),
    )
    op.create_index(
        "ix_logged_session_notes_tsv",
        "logged_session",
        [sa.text("to_tsvector('simple', notes)")],
        unique=False,
        postgresql_using="gin",
        postgresql_where=sa.text("notes IS NOT NULL"),
    )
    op.create_table(
        "prescribed_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_block_id", sa.Integer(), nullable=False),
        sa.Column("set_index", sa.SmallInteger(), nullable=False),
        sa.Column("target_reps", sa.SmallInteger(), nullable=True),
        sa.Column("target_work_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("target_rest_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("target_load_kg", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("target_intensity_pct", sa.SmallInteger(), nullable=True),
        sa.Column("target_rpe", sa.SmallInteger(), nullable=True),
        sa.Column("target_grade_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("set_index >= 1", name=op.f("ck_prescribed_set_set_index_positive")),
        sa.CheckConstraint(
            "target_intensity_pct IS NULL OR (target_intensity_pct BETWEEN 1 AND 200)",
            name=op.f("ck_prescribed_set_target_intensity_pct_sane"),
        ),
        sa.CheckConstraint(
            "target_rpe IS NULL OR (target_rpe BETWEEN 1 AND 10)",
            name=op.f("ck_prescribed_set_target_rpe_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["session_block_id"],
            ["session_block.id"],
            name=op.f("fk_prescribed_set_session_block_id_session_block"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_grade_id"], ["grade.id"], name=op.f("fk_prescribed_set_target_grade_id_grade")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prescribed_set")),
        sa.UniqueConstraint(
            "session_block_id",
            "set_index",
            name=op.f("uq_prescribed_set_session_block_id_set_index"),
        ),
    )
    op.create_table(
        "ascent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("logged_session_id", sa.Integer(), nullable=True),
        sa.Column("climbed_on", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("grade_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("style", ascent_style, nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=True),
        sa.Column("board_angle", sa.SmallInteger(), nullable=True),
        sa.Column("rpe", sa.SmallInteger(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempts IS NULL OR attempts >= 1", name=op.f("ck_ascent_attempts_positive")
        ),
        sa.CheckConstraint(
            "board_angle IS NULL OR (board_angle BETWEEN -60 AND 90)",
            name=op.f("ck_ascent_board_angle_in_range"),
        ),
        sa.CheckConstraint(
            "rpe IS NULL OR (rpe BETWEEN 1 AND 10)", name=op.f("ck_ascent_rpe_in_range")
        ),
        sa.ForeignKeyConstraint(
            ["grade_id", "grade_ordinal"],
            ["grade.id", "grade.ordinal"],
            name="fk_ascent_grade_id_grade_ordinal_grade",
        ),
        sa.ForeignKeyConstraint(
            ["logged_session_id"],
            ["logged_session.activity_id"],
            name=op.f("fk_ascent_logged_session_id_logged_session"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_ascent_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ascent")),
        sa.UniqueConstraint("user_id", "client_uuid", name=op.f("uq_ascent_user_id_client_uuid")),
    )
    op.create_index("ix_ascent_logged_session_id", "ascent", ["logged_session_id"], unique=False)
    op.create_index(
        "ix_ascent_notes_tsv",
        "ascent",
        [sa.text("to_tsvector('simple', notes)")],
        unique=False,
        postgresql_using="gin",
        postgresql_where=sa.text("notes IS NOT NULL"),
    )
    op.create_index(
        "ix_ascent_user_id_climbed_on", "ascent", ["user_id", "climbed_on"], unique=False
    )
    op.create_index(
        "ix_ascent_user_id_grade_ordinal", "ascent", ["user_id", "grade_ordinal"], unique=False
    )
    op.create_table(
        "journal_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=True),
        sa.Column("feel", sa.SmallInteger(), nullable=True),
        sa.Column("sleep_quality", sa.SmallInteger(), nullable=True),
        sa.Column("skin", sa.SmallInteger(), nullable=True),
        sa.Column("body_weight_kg", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("logged_session_id", sa.Integer(), nullable=True),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "body IS NOT NULL OR feel IS NOT NULL OR sleep_quality IS NOT NULL "
            "OR skin IS NOT NULL OR body_weight_kg IS NOT NULL",
            name=op.f("ck_journal_entry_not_empty"),
        ),
        sa.CheckConstraint(
            "body_weight_kg IS NULL OR (body_weight_kg BETWEEN 20 AND 300)",
            name=op.f("ck_journal_entry_body_weight_kg_sane"),
        ),
        sa.CheckConstraint(
            "feel IS NULL OR (feel BETWEEN 1 AND 5)", name=op.f("ck_journal_entry_feel_in_range")
        ),
        sa.CheckConstraint(
            "skin IS NULL OR (skin BETWEEN 1 AND 5)", name=op.f("ck_journal_entry_skin_in_range")
        ),
        sa.CheckConstraint(
            "sleep_quality IS NULL OR (sleep_quality BETWEEN 1 AND 5)",
            name=op.f("ck_journal_entry_sleep_quality_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["logged_session_id"],
            ["logged_session.activity_id"],
            name=op.f("fk_journal_entry_logged_session_id_logged_session"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_journal_entry_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_entry")),
        sa.UniqueConstraint(
            "user_id", "client_uuid", name=op.f("uq_journal_entry_user_id_client_uuid")
        ),
    )
    op.create_index(
        "ix_journal_entry_body_tsv",
        "journal_entry",
        [sa.text("to_tsvector('simple', body)")],
        unique=False,
        postgresql_using="gin",
        postgresql_where=sa.text("body IS NOT NULL"),
    )
    op.create_index(
        "ix_journal_entry_logged_session_id", "journal_entry", ["logged_session_id"], unique=False
    )
    op.create_index(
        "ix_journal_entry_user_id_entry_date",
        "journal_entry",
        ["user_id", "entry_date"],
        unique=False,
    )
    op.create_table(
        "logged_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("logged_session_id", sa.Integer(), nullable=False),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("prescribed_set_id", sa.Integer(), nullable=True),
        sa.Column("set_index", sa.SmallInteger(), nullable=False),
        sa.Column("actual_reps", sa.SmallInteger(), nullable=True),
        sa.Column("actual_work_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("actual_load_kg", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("rpe", sa.SmallInteger(), nullable=True),
        sa.Column("body_weight_kg", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("body_weight_as_of", sa.Date(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "actual_reps IS NULL OR actual_reps >= 0",
            name=op.f("ck_logged_set_actual_reps_not_negative"),
        ),
        sa.CheckConstraint(
            "actual_work_seconds IS NULL OR actual_work_seconds >= 0",
            name=op.f("ck_logged_set_actual_work_seconds_not_negative"),
        ),
        sa.CheckConstraint(
            "body_weight_kg IS NULL OR (body_weight_kg BETWEEN 20 AND 300)",
            name=op.f("ck_logged_set_body_weight_kg_sane"),
        ),
        sa.CheckConstraint(
            "rpe IS NULL OR (rpe BETWEEN 1 AND 10)", name=op.f("ck_logged_set_rpe_in_range")
        ),
        sa.CheckConstraint("set_index >= 1", name=op.f("ck_logged_set_set_index_positive")),
        sa.ForeignKeyConstraint(
            ["exercise_id"], ["exercise.id"], name=op.f("fk_logged_set_exercise_id_exercise")
        ),
        sa.ForeignKeyConstraint(
            ["logged_session_id"],
            ["logged_session.activity_id"],
            name=op.f("fk_logged_set_logged_session_id_logged_session"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prescribed_set_id"],
            ["prescribed_set.id"],
            name=op.f("fk_logged_set_prescribed_set_id_prescribed_set"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_logged_set")),
        sa.UniqueConstraint(
            "logged_session_id",
            "client_uuid",
            name=op.f("uq_logged_set_logged_session_id_client_uuid"),
        ),
    )
    op.create_index("ix_logged_set_exercise_id", "logged_set", ["exercise_id"], unique=False)
    op.create_index(
        "ix_logged_set_note_tsv",
        "logged_set",
        [sa.text("to_tsvector('simple', note)")],
        unique=False,
        postgresql_using="gin",
        postgresql_where=sa.text("note IS NOT NULL"),
    )
    op.create_index(
        "ix_logged_set_prescribed_set_id", "logged_set", ["prescribed_set_id"], unique=False
    )
    op.create_table(
        "ascent_tag_link",
        sa.Column("ascent_id", sa.Integer(), nullable=False),
        sa.Column("ascent_tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ascent_id"],
            ["ascent.id"],
            name=op.f("fk_ascent_tag_link_ascent_id_ascent"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ascent_tag_id"],
            ["ascent_tag.id"],
            name=op.f("fk_ascent_tag_link_ascent_tag_id_ascent_tag"),
        ),
        sa.PrimaryKeyConstraint("ascent_id", "ascent_tag_id", name=op.f("pk_ascent_tag_link")),
    )
    op.create_index(
        "ix_ascent_tag_link_ascent_tag_id", "ascent_tag_link", ["ascent_tag_id"], unique=False
    )


def downgrade() -> None:
    """For local and CI use only.

    **Never run against production** — `migrate.yml` deliberately offers no `downgrade`
    action, and recovery there is a Neon branch restore. This body drops real training
    history, which is precisely why it must not be one dropdown click away.

    Indexes first (a table cannot be dropped while an index on it is being named), then
    tables in exact reverse creation order so no foreign key is ever left dangling, then
    `grade`'s added constraint, then the enum types last: a type cannot go while a column
    still uses it.
    """
    op.drop_index("ix_ascent_tag_link_ascent_tag_id", table_name="ascent_tag_link")
    op.drop_index("ix_logged_set_prescribed_set_id", table_name="logged_set")
    op.drop_index("ix_logged_set_note_tsv", table_name="logged_set")
    op.drop_index("ix_logged_set_exercise_id", table_name="logged_set")
    op.drop_index("ix_journal_entry_user_id_entry_date", table_name="journal_entry")
    op.drop_index("ix_journal_entry_logged_session_id", table_name="journal_entry")
    op.drop_index("ix_journal_entry_body_tsv", table_name="journal_entry")
    op.drop_index("ix_ascent_user_id_grade_ordinal", table_name="ascent")
    op.drop_index("ix_ascent_user_id_climbed_on", table_name="ascent")
    op.drop_index("ix_ascent_notes_tsv", table_name="ascent")
    op.drop_index("ix_ascent_logged_session_id", table_name="ascent")
    op.drop_index("ix_logged_session_notes_tsv", table_name="logged_session")
    op.drop_index("ix_activity_user_id_occurred_on", table_name="activity")
    op.drop_index("ix_activity_planned_session_id", table_name="activity")
    op.drop_index("ix_planned_session_scheduled_on", table_name="planned_session")
    op.drop_index("ix_microcycle_mesocycle_id_plan_id", table_name="microcycle")
    op.drop_index("ix_user_injury_user_id", table_name="user_injury")
    op.drop_index("ix_plan_user_id_created_at", table_name="plan")
    op.drop_index("ix_exercise_equipment_equipment_id", table_name="exercise_equipment")
    op.drop_index(
        "ix_exercise_contraindication_injury_area_id", table_name="exercise_contraindication"
    )
    op.drop_index("ix_exercise_climbing_aspect_id", table_name="exercise")
    op.drop_table("ascent_tag_link")
    op.drop_table("logged_set")
    op.drop_table("journal_entry")
    op.drop_table("ascent")
    op.drop_table("prescribed_set")
    op.drop_table("logged_session")
    op.drop_table("session_block")
    op.drop_table("activity")
    op.drop_table("planned_session")
    op.drop_table("microcycle")
    op.drop_table("mesocycle")
    op.drop_table("user_profile")
    op.drop_table("user_injury")
    op.drop_table("user_equipment")
    op.drop_table("user_aspect_rating")
    op.drop_table("prescription_template")
    op.drop_table("plan")
    op.drop_table("exercise_equipment")
    op.drop_table("exercise_contraindication")
    op.drop_table("exercise")
    op.drop_table("injury_area")
    op.drop_table("equipment")
    op.drop_table("climbing_aspect")
    op.drop_table("ascent_tag")
    op.drop_constraint("uq_grade_id_ordinal", "grade", type_="unique")
    for enum_type in reversed(NEW_ENUM_TYPES):
        enum_type.drop(op.get_bind(), checkfirst=True)
