"""profile, exercise library, plan tree, activity/logging and the training diary

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-21

The domain schema: everything the app is actually for. Twenty-four tables and five new
native enum types, in one revision because they are one dependency graph — `logged_set`
points at `prescribed_set`, `activity` points at `planned_session`, and splitting them
across revisions would produce intermediate states no deploy would ever run against.

**Purely additive.** No column is dropped and no row is rewritten. `app_user`,
`auth_session`, `invite`, `rate_limit` and `grade_system` are untouched entirely; `grade`
gains **one unique constraint** on `(id, ordinal)`, which is additive by construction —
`id` is already its primary key, so the constraint cannot fail on any existing row, and
`grade` holds re-seedable reference data rather than user rows. Code running before this
revision keeps working after it (expand -> deploy -> contract).
`tests/test_migrations_additive.py` enforces that, and this revision is the reason its
protected set grew from `app_user` alone to every table that holds irreplaceable user
data.

Hand-written, like 0001-0003, because there is no Postgres on this machine to
autogenerate against. The bodies below were **rendered from the model metadata** with
`alembic.autogenerate.render_python_code` rather than typed out, so a name or a type can
not drift by transcription; CI is still what proves the DDL runs, by executing
`alembic upgrade head` against a throwaway `postgres:17-alpine` and then `alembic check`
against the models.

⚠️ **What `alembic check` does NOT cover: the enum VALUE LISTS below.** An earlier draft of
this docstring claimed it did. It does not — a SQLAlchemy `ENUM` compiles to its type
*name*, so `compare_type=True` sees `activity_kind` on both sides and is blind to the
membership and the order. Deleting `taper` from `phase` below leaves `alembic check` and
the whole suite green, and the first plan needing a taper mesocycle then dies at runtime on
`invalid input value for enum phase`. That gap is closed by
`tests/test_vocabulary_contract.py`, which compares these six lists against
`server/domain/vocabulary.py` directly. The duplication itself stays: importing live
application code into a migration un-pins it from history, which is the one thing a
migration must never be.

## Two things that differ from 0001-0003, both deliberate

**1. Constraint names are wrapped in `op.f()`.** 0003 documents the trap: `op.create_table`
applies `NAMING_CONVENTION` itself, and the `ck` template interpolates the name you pass,
so a pre-derived `ck_invite_max_uses_positive` comes back out as
`ck_invite_ck_invite_max_uses_positive`. `op.f()` marks a name as already final, which
removes the trap instead of requiring everyone to remember the exception — and it is what
`alembic check` compares against, since the model side derives these same strings.

**2. The five new enum types are created ONCE, explicitly, up front.** Each is declared
with `create_type=False` so that `op.create_table` does not also emit `CREATE TYPE`; the
implicit path is what produces "type activity_kind already exists" on the second table to
use it (0001's comment, still true). `discipline` already exists from 0001 and is
therefore declared here but never created.

## Not a data migration

Every table starts empty. There is nothing to backfill and no `server_default` written
across existing rows, because no existing row gains a column. The seed
(`python -m server.seed`) fills the four new reference tables — `climbing_aspect`,
`equipment`, `injury_area`, `ascent_tag` — and must be run after this upgrade; the exercise
library itself is content, authored separately, and is not seeded here.

## One reversal recorded here on purpose

`ascent.tags text[]` and its GIN index are **gone**, replaced by the `ascent_tag` lookup
plus the `ascent_tag_link` join (Kilian, 2026-08-21). If a later revision proposes bringing
the array back as "simpler", read `server/domain/vocabulary.py::ASCENT_TAGS` first — the
array version fragments the vocabulary it exists to aggregate, and it was the only
unbounded write in the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False on every one of them: the types are created (and dropped) explicitly
# in upgrade()/downgrade() below, so `op.create_table` must not try to emit CREATE TYPE
# again for the second and subsequent tables that use one.
#
# The value lists must match `server/domain/vocabulary.py` exactly, lowercase — that is
# what `values_callable` in server/models.py guarantees on the ORM side.
#
# ⚠️ **`alembic check` does NOT verify this**, contrary to what this comment said until
# 2026-08-21 — see the ⚠️ in the module docstring above. An `ENUM` compiles to its type
# name, so the comparison never looks inside. `tests/test_vocabulary_contract.py` is what
# checks it, and this comment is corrected here rather than deleted because the false
# version is exactly what would make a future reader delete that test as redundant.
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

# `discipline` is NOT in here: 0001 created it, and creating it again would be a no-op at
# best and a confusing failure at worst.
NEW_ENUM_TYPES = (activity_kind, ascent_style, protocol_kind, phase, session_status)


def upgrade() -> None:
    bind = op.get_bind()
    # checkfirst so a partially-applied environment can be brought forward, exactly as
    # 0001 does for `discipline`.
    for enum_type in NEW_ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    # The ONLY change to a table that already exists, and it is additive: `grade` gains a
    # unique constraint on (id, ordinal) so that `ascent` can reference the pair with a
    # composite foreign key. `id` is already the primary key, so this can never fail on
    # existing rows — and `grade` is re-seedable reference data with no user rows in it.
    op.create_unique_constraint("uq_grade_id_ordinal", "grade", ["id", "ordinal"])

    # Tags are a FIXED vocabulary: this lookup plus the `ascent_tag_link` join, NOT
    # `ascent.tags text[]` + a GIN index. Reversed 2026-08-21 (Kilian); the reasoning
    # is in server/domain/vocabulary.py::ASCENT_TAGS. Seeded by server/seed.py.
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
    # The library. Self-referential progression/regression foreign keys, so this table
    # has to exist before its own constraints can point at it — op.create_table handles
    # that in one statement.
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
    # `show_body_metrics` defaults to TRUE: %BW is the most useful strength number in
    # climbing, and a default of off would make the feature undiscoverable. Turning it
    # off hides the weight trend and every %BW figure and stops any weigh-in prompt.
    # There is deliberately no goal-weight, target-weight or BMI column here or anywhere
    # else in this migration; see CLAUDE.md, 'The app never recommends losing weight'.
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
    # uq_mesocycle_id_plan_id looks redundant next to the primary key. It is not: it is
    # the TARGET of microcycle's composite foreign key below, and a composite FK needs a
    # unique constraint on exactly those columns to reference. Dropping it breaks the
    # next table.
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
    # `plan_id` is carried down from mesocycle so that `(plan_id, week_no)` — the hottest
    # read in the app — needs no join. The composite foreign key on
    # (mesocycle_id, plan_id) is what makes that denormalisation safe rather than merely
    # intended: a row whose plan_id disagrees with its mesocycle's is rejected by
    # Postgres. uq_microcycle_plan_id_week_no doubles as the index for (plan_id, week_no),
    # but the composite FK needs its OWN index: neither unique constraint on this table
    # leads with `mesocycle_id`.
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
    # THE SUPERTYPE. One row per activity of any kind; `logged_session` below is the 1:1
    # climbing-only subtype. See server/models.py::Activity for why this is one table
    # and not five.
    #
    # `srpe_load` is GENERATED ... STORED. Note `rpe::integer`: both operands are
    # SMALLINT, so the uncast product resolves as int2*int2 and raises `smallint out of
    # range` before the widening cast to this INTEGER column — which on the outbox path
    # is a payload that retries forever. The duration CHECK is the other half.
    #
    # uq_activity_id_activity_kind is the target of logged_session's composite foreign
    # key. Keep it.
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
    # THE SUBTYPE, and the constraint that makes it one. `activity_id` is primary key AND
    # foreign key (at most one subtype row per activity); `activity_kind` is repeated
    # with CHECK (= 'climbing') and a composite FK to activity (id, activity_kind), so
    # Postgres itself refuses to hang a logged session off a bike ride.
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
    # Free-text search over the diary. Expression indexes (`to_tsvector`), which Alembic
    # skips on BOTH sides of an autogenerate comparison rather than reporting a phantom
    # diff — so `alembic check` stays quiet without anything being excluded by hand.
    # `simple`, not `english`: no stemming and no stopword list is the right call for short
    # notes full of proper nouns. Partial, because most of these columns are NULL.
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
    # (grade_id, grade_ordinal) -> grade (id, ordinal) is the third use of the composite
    # FK technique, and it is what makes the denormalised ordinal safe: the band IS the
    # discipline, so a transposed ordinal would file a rope send in the boulder pyramid
    # with nothing to recover the truth from. It needs uq_grade_id_ordinal, added to the
    # existing `grade` table above.
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
    # ### end Alembic commands ###


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
    # `discipline` stays: 0001 owns it, and grade_system still uses it.
