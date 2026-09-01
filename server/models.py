"""SQLAlchemy 2 declarative models.
Two things here are infrastructure rather than schema, and both stop a class of future mistake.
**An explicit constraint naming convention** on the metadata: without it Postgres invents names
like `grade_grade_system_id_label_key`, autogenerate emits `None` for the name, and a later
`op.drop_constraint` has nothing stable to name. **`type_annotation_map` pinning `datetime` to
`TIMESTAMP(timezone=True)`** — TIMESTAMPTZ, never naive — repo-wide and automatic, so any
future `Mapped[datetime]` gets it without anyone remembering. Naive timestamps are fine until
the first user trains in another timezone or a DST boundary lands mid-session, and by then
there is data to migrate. Store aware, convert at the edge.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from server.domain.grades import Discipline
from server.domain.vocabulary import (
    ActivityKind,
    AscentStyle,
    Phase,
    ProtocolKind,
    SessionStatus,
)

# `column_0_N_name` joins every column in the constraint, so a two-column unique
# constraint gets both names — which is what makes the name predictable from the model.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Native Postgres enum: type-safe and cheap, and the price of extending one (an
# `ALTER TYPE ... ADD VALUE` migration) is acceptable for a genuinely closed set.
discipline_enum = Enum(
    Discipline,
    name="discipline",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

# The rest of the closed vocabularies, from `server/domain/vocabulary.py`. Every one of
# them repeats `values_callable` — there is no shared helper, because a helper that took
# the enum class and the type name would be shorter to read and *exactly* as easy to
# bypass by writing `Enum(Foo, name="foo")` for the next one. The repetition is the
# reminder. Drop `values_callable` from any of these and the database stores
# 'MAX_HANG' while every query, payload and TypeScript union says 'max_hang'.
activity_kind_enum = Enum(
    ActivityKind,
    name="activity_kind",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)
ascent_style_enum = Enum(
    AscentStyle,
    name="ascent_style",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)
protocol_kind_enum = Enum(
    ProtocolKind,
    name="protocol_kind",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)
phase_enum = Enum(
    Phase,
    name="phase",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)
session_status_enum = Enum(
    SessionStatus,
    name="session_status",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

# `sa.text("true")` / `sa.text("false")`, never `func.true()` / `func.false()`.
# The `func.` forms compile to `true()` and `false()`, which are not Postgres functions —
# the DDL would fail outright. Nothing notices today because this repo never calls
# `create_all()` and `compare_server_default` is off in `migrations/env.py`, so the only
# reader of these is Alembic's renderer. That makes it a trap rather than a bug: a
# `create_all()` fixture is a *tempting* shortcut past `alembic upgrade head`, and it would
# fail on three columns for a reason that looks nothing like the cause.
TRUE = text("true")
FALSE = text("false")

# `Numeric`, never float: a load is money-like, and 0.1 + 0.2 arithmetic on someone's
# training numbers is both wrong and visibly wrong.
KILOGRAMS = Numeric(5, 2)

# Here rather than inline because the Pydantic schemas must use the SAME numbers: a
# request model allowing 4000 characters into a 2000-character column is a 500, not a 422.
NOTES_MAX = 2000
SET_NOTE_MAX = 500
# `logged_session.location`. The same 120 `ascent.name` uses: a gym or crag name is a short
# label, and `server/fields.py::SessionLocation` mirrors this number rather than repeating it.
LOCATION_MAX = 120
ASCENT_NOTES_MAX = 1000
JOURNAL_BODY_MAX = 4000
# `user_profile.display_name`. 64 rather than 120: it is a name on a screen, not a route
# name, and it is the same bound `invite.label` uses for the same kind of short label.
DISPLAY_NAME_MAX = 64
# `exercise.substitution_hint`. Authored content, not user input, so it has no Pydantic
# request bound — the same 255 the lookup tables' `description` uses, for the same reason.
SUBSTITUTION_HINT_MAX = 255


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: TIMESTAMP(timezone=True)}


class GradeSystem(Base):
    """A grading scale. A lookup table, not an enum: it carries user-facing content.

    `key` is the stable machine identifier (`server.domain.grades.GradeSystemKey`) and
    is what code matches on; `name` is display only, and `id` is what other tables
    reference.

    ## `sort_order` exists because a SERIAL is not a display order (issue #55, `0006`)

    `GET /api/vocabulary` used to order these by `id`, while its three sibling lookup
    tables order by an explicit `sort_order`. That is a **latent** bug rather than a live
    one, and the shape of it is worth keeping: insert a new system mid-tuple and CI — always
    a fresh database, so serials follow declaration order — keeps passing, while dev and
    production keep their old serials and render the new system LAST. The test pinning
    declaration order would then assert a property the real databases do not have.

    So this column is the same contract the siblings have: **the value is the tuple
    position in `server.domain.grades.GRADE_SYSTEMS`**, written by the seed, so display
    order is edited by moving a line rather than by renumbering a column. It is not in
    `GradeSystemOut` — ordering is the server's job, and a client that could see it could
    disagree with it.
    """

    __tablename__ = "grade_system"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    discipline: Mapped[Discipline] = mapped_column(discipline_enum)
    sort_order: Mapped[int] = mapped_column(SmallInteger)

    grades: Mapped[list["Grade"]] = relationship(
        back_populates="grade_system",
        order_by="Grade.ordinal",
    )


class Grade(Base):
    """One rung of one scale: `ordinal` compares (see `server/domain/grades.py`), `label`
    displays. The API takes a `grade_id` and reads the ordinal from here, never the reverse."""

    __tablename__ = "grade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grade_system_id: Mapped[int] = mapped_column(ForeignKey("grade_system.id"))
    label: Mapped[str] = mapped_column(String(16))
    # SmallInteger is plenty: ordinals are banded per discipline in the low thousands.
    ordinal: Mapped[int] = mapped_column(SmallInteger)

    grade_system: Mapped[GradeSystem] = relationship(back_populates="grades")

    __table_args__ = (
        # The seed upserts on this pair, so it is a data contract, not just hygiene.
        UniqueConstraint("grade_system_id", "label"),
        # One label per rung per scale: this is what makes the ladder a ladder, and
        # what a bad seed edit would violate first.
        UniqueConstraint("grade_system_id", "ordinal"),
        # Cross-scale lookup ("what is ordinal 1009 called in the V-scale?") and the
        # send pyramid's `(user_id, grade_ordinal)` joins both come in on ordinal.
        Index("ix_grade_ordinal", "ordinal"),
        # NOT hygiene: the target of `ascent`'s composite FK on (grade_id, grade_ordinal).
        # Drop it and a wrong ordinal silently reclassifies an ascent's discipline.
        UniqueConstraint("id", "ordinal"),
    )


class AppUser(Base):
    """An account. Named `app_user` because `user` is a reserved word in Postgres.

    `email` is `String(254)` (the RFC 5321 maximum) rather than `citext`: the extension
    is not guaranteed on Neon and adding one is a privileged operation, so
    case-insensitivity is enforced at the edge instead — every write path lowercases and
    strips before it touches this column, and the unique constraint then means what it
    looks like it means. If a future path forgets to normalise, two accounts differing
    only in case become possible; that is the failure this comment exists to prevent.

    `password_hash` is **nullable on purpose**. The seeded demo account has no password
    and must never be loggable through `/api/auth/login`; a NULL here is what makes that
    structural rather than a check the login handler could forget.

    `invite_id` is attribution: which invite this account was created from.
    """

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    # argon2id encoded hash ("$argon2id$v=19$m=47104,t=1,p=1$..."), ~100 chars at the
    # profile in server/auth/passwords.py. 255 leaves room for a future parameter bump.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=FALSE)
    # NULLABLE: the demo account and every account predating the gate have no invite. RESTRICT,
    # not SET NULL or CASCADE — a tidy-up must not erase the attribution this column exists for.
    invite_id: Mapped[int | None] = mapped_column(
        ForeignKey("invite.id", ondelete="RESTRICT"), nullable=True
    )
    # A SERVER default, so the timestamp is the database's clock rather than a serverless
    # function's — the two disagree often enough to matter for ordering.
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuthSession(Base):
    """One refresh token in a rotation family. See `server/auth/refresh.py`.

    A *family* is the chain of refresh tokens descending from one login. Every rotation
    writes a new row with the same `family_id` and stamps `rotated_at` on the old one,
    so the family is an append-only audit trail of a single browser's session.

    That trail is what makes **reuse detection** possible: a token whose row already has
    `rotated_at` (or `revoked_at`) set has been presented twice, which only happens if it
    was captured. The response is to revoke the whole family — the legitimate holder is
    logged out too, which is the correct trade when the alternative is leaving an
    attacker with a valid chain.

    `token_hash` stores a **sha256 hex digest, never the token**. A database dump must
    not be a set of working credentials.
    """

    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ondelete=CASCADE: deleting an account must not leave live refresh tokens behind,
    # and this is one of the few places where the database can guarantee that itself.
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid())
    # 64 hex characters, exactly — sha256. Unique because two rows sharing a digest
    # would make rotation ambiguous, and because it is the lookup key on every refresh.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    issued_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column()
    rotated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        # Revoking a compromised family is a single indexed UPDATE.
        Index("ix_auth_session_family_id", "family_id"),
        # "this user's live sessions", for a future device list and for logout-everywhere.
        Index("ix_auth_session_user_id_family_id", "user_id", "family_id"),
    )


class Invite(Base):
    """A registration invite. One per person, hashed, revocable, and countable.

    Registration is invite-only — see `server/auth/invites.py`. `EmailStr` proves an address
    is syntactically valid and nothing more, so without this table anyone can create an
    account on climb.kilianmc.com.

    `code_hash` stores a **sha256 hex digest, never the code**, for the same reason
    `AuthSession.token_hash` does: a database dump must not be a set of working invites.
    sha256 rather than argon2 because a code is 128 bits of CSPRNG output — there is no
    dictionary, and nothing for a work factor to slow down.

    `label` is what makes a use **attributable** ("Bob, from the gym"). Codes are per person,
    so revoking one revokes exactly one invitation and leaves everyone else's working. It is
    never returned to a caller.

    `max_uses` / `uses` are a counter rather than a boolean `used` flag because a code for a
    couple, or for a coach and two clients, is the same code used twice. The CHECK constraints
    below are the database's own half of the limit: `server/auth/invites.py` takes a row lock
    so two concurrent registrations cannot both spend the last use, and `ck_invite_uses_within_max`
    means a bug in that logic fails loudly instead of over-issuing.
    """

    __tablename__ = "invite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 64 hex characters, exactly — sha256. Unique because it is the lookup key on every
    # registration, and because two rows sharing a digest would make "which invite" ambiguous.
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(64))
    max_uses: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    uses: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    # NULL means "no expiry". Aware, like every datetime here.
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint("max_uses >= 1", name="max_uses_positive"),
        # The structural limit. An invite can never be spent more times than it was issued
        # for, whatever the application layer believes.
        CheckConstraint("uses >= 0 AND uses <= max_uses", name="uses_within_max"),
    )


class RateLimit(Base):
    """Fixed-window request counter. See `server/auth/ratelimit.py`.

    It lives in Postgres because there are no background workers and no Redis in this
    deployment — a serverless function is frozen between requests, so an in-process
    counter would reset on every cold start and be per-instance even when warm.

    The primary key IS the window: `(bucket, window_start)`. That makes the whole limiter
    one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING count`, i.e. one round trip with
    no read-then-write race. `bucket` never contains a raw IP — see the module for why.
    """

    __tablename__ = "rate_limit"

    bucket: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


# --- Reference: the exercise library and the vocabularies that carry display text ---


class ClimbingAspect(Base):
    """What an exercise trains. A lookup table because it carries display text; upserted by the
    seed on `key`, so `key` is a data contract and retiring an aspect is a migration."""

    __tablename__ = "climbing_aspect"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class Equipment(Base):
    """Something a user has access to, and an exercise may require. The generator filters the
    library on this, so an unseeded row is a prescription nobody can perform."""

    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class InjuryArea(Base):
    """A body area an injury can sit in. Coarse on purpose: the only decision made from a flag
    is which exercises to withhold, so this is not a diagnosis and must not grow into one."""

    __tablename__ = "injury_area"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class AscentTag(Base):
    """A taggable fact about a climb. ⚠️ Replaced `ascent.tags text[]` + GIN, reversed 2026-08-21.
    Reasoning in `server/domain/vocabulary.py::ASCENT_TAGS`, where the tag list is edited."""

    __tablename__ = "ascent_tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255))
    # Groups the picker ("Holds", "Angle", ...). Nothing queries on it and only the seed
    # writes it, which is why it is a plain string and not a seventh native enum.
    category: Mapped[str] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class Exercise(Base):
    """One library exercise. Reference data: written only by the seed, never by a user.

    **Removing a key from `server/domain/exercises.py` removes the ROW**, unless a plan or
    a logged set points at it — in which case `retired_at` is set and the row stays. See
    that column and `server/contentseed.py`.

    **`progression_of_id` / `regression_of_id` are self-referential and independent.**
    Two columns rather than one, because the graph is not a clean chain: "easier version
    of X" and "harder version of X" are authored separately and an exercise can be a
    regression of something it is not the progression-of anything of. A single
    `parent_id` would force one direction to be inferred, and the inference is wrong at
    every branch point.

    `protocol_kind` is the *default* shape; a `session_block` snapshots its own copy so
    that editing the library never rewrites a plan that was already generated.

    Deliberately absent: an `energy_system` column. The plan sketch listed one, but the
    closed vocabularies were settled without it and `climbing_aspect` + `protocol_kind`
    already carry everything the generator reads. Adding a seventh enum here would be a
    product decision, not an implementation detail — so it is a question, not a column.
    """

    __tablename__ = "exercise"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(96))
    climbing_aspect_id: Mapped[int] = mapped_column(ForeignKey("climbing_aspect.id"))
    protocol_kind: Mapped[ProtocolKind] = mapped_column(protocol_kind_enum)
    # NULL = discipline-agnostic (a hangboard protocol serves both). Most of the library is
    # NULL here; the exceptions only make sense on a rope, or only on a boulder.
    discipline: Mapped[Discipline | None] = mapped_column(discipline_enum, nullable=True)
    instructions: Mapped[str] = mapped_column(String(2000))
    # "No dumbbell? A packed backpack." ⚠️ NULL FOR EVERY FINGER-LOADING PROTOCOL: hangboard,
    # campus and no-hang have no honest substitute, only improvised edges.
    substitution_hint: Mapped[str | None] = mapped_column(
        String(SUBSTITUTION_HINT_MAX), nullable=True
    )
    # A URL to a demo clip, hosted wherever the library content is hosted. NULL until
    # one exists; never rendered as HTML (see the output-escaping rules in CLAUDE.md).
    media_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # ⚠️ **Logical retirement is the FALLBACK, not the rule.** An exercise dropped from
    # `server/domain/exercises.py` is genuinely DELETED by `server/contentseed.py` when
    # nothing references it — Kilian's call: hiding a row he judged weak is not deleting
    # it. This column is what happens when something does reference it. `session_block`
    # and `logged_set` point here with `NO ACTION`, so Postgres refuses the delete rather
    # than cascading into somebody's training diary, and the seed sets this instead.
    # Retired rows are filtered out of `GET /api/library` and are never prescribable; the
    # row stays so that a six-month-old diary entry still resolves to a name.
    # A timestamp, not a boolean: "when did this leave the library" is the question an old
    # log entry actually raises. Deliberately NOT in the API response — see the CDN rule
    # in `server/library/routes.py`.
    retired_at: Mapped[datetime | None] = mapped_column(nullable=True)
    progression_of_id: Mapped[int | None] = mapped_column(ForeignKey("exercise.id"), nullable=True)
    regression_of_id: Mapped[int | None] = mapped_column(ForeignKey("exercise.id"), nullable=True)

    __table_args__ = (
        # "every exercise for this aspect", which is how the generator walks the library,
        # and also the index the CASCADE from `climbing_aspect` would need.
        Index("ix_exercise_climbing_aspect_id", "climbing_aspect_id"),
    )


class ExerciseEquipment(Base):
    """What an exercise requires. Every row is a requirement, so the set is an AND, and the
    composite primary key being the whole row makes the "has everything?" anti-join cheap."""

    __tablename__ = "exercise_equipment"

    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercise.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        # Covers the CASCADE from `equipment`, whose FK column leads no index; the composite PK
        # already covers `exercise`. Postgres does not index the referencing side for you.
        Index("ix_exercise_equipment_equipment_id", "equipment_id"),
    )


class ExerciseContraindication(Base):
    """ "Do not prescribe this exercise while this area is injured." The generator WITHHOLDS
    rather than substitutes: the slot goes to whatever else scores highest for that aspect."""

    __tablename__ = "exercise_contraindication"

    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercise.id", ondelete="CASCADE"), primary_key=True
    )
    injury_area_id: Mapped[int] = mapped_column(
        ForeignKey("injury_area.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        # Covers the CASCADE from `injury_area`; the composite PK already covers the one
        # from `exercise`. See ExerciseEquipment above.
        Index("ix_exercise_contraindication_injury_area_id", "injury_area_id"),
    )


class PrescriptionTemplate(Base):
    """The default prescription for one exercise in one phase. Reference data.

    One row per (exercise, phase): a max hang is 5x10s in `strength` and 3x10s in
    `deload`, and the generator reads the row rather than applying a multiplier to a
    base prescription (see `Phase` for why a deload is a block, not a scale factor).

    **`intensity_pct` has no explicit anchor column, deliberately.** What the percentage
    is *of* is determined by the exercise's `protocol_kind` — a percentage on a
    `max_hang` is of that user's best hang, a percentage on `straight_sets` is of a
    training max — and an `intensity_anchor` vocabulary would be a seventh closed set
    invented to restate something already derivable. If the compiler ever needs an
    anchor the protocol_kind cannot supply, that is the moment to add one, with a
    migration and a reason.
    """

    __tablename__ = "prescription_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id", ondelete="CASCADE"))
    phase: Mapped[Phase] = mapped_column(phase_enum)
    sets: Mapped[int] = mapped_column(SmallInteger)
    # Reps OR seconds, depending on the protocol. Neither is derived: a repeater set has
    # seconds and no reps, a pull-up reps and no seconds, and a circuit legitimately neither.
    reps: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    work_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rest_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rest_between_sets_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    intensity_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    target_rpe: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("exercise_id", "phase"),
        CheckConstraint("sets >= 1", name="sets_positive"),
        CheckConstraint(
            "intensity_pct IS NULL OR (intensity_pct BETWEEN 1 AND 200)",
            name="intensity_pct_sane",
        ),
        CheckConstraint(
            "target_rpe IS NULL OR (target_rpe BETWEEN 1 AND 10)", name="target_rpe_in_range"
        ),
    )


# --- The user's profile ---


class UserProfile(Base):
    """Everything the plan generator needs about a person. One row per account.

    **`user_id` is both primary key and foreign key**, which is what makes the 1:1 real rather
    than conventional: a second profile for the same account is impossible, not discouraged.
    `available_weekdays` is a 7-bit mask, Monday = bit 0 — read on every generation and written
    whole, with no query wanting "everyone free on Thursdays".

    ## ⚠️ THREE COLUMNS ARE NULLABLE BECAUSE UNANSWERED IS A REAL STATE (0005)

    Onboarding writes this row **one step at a time**, so it exists before those questions have
    been asked, and the `NOT NULL` they carried until `0005` forced the write path to invent
    placeholders — two of which were indistinguishable from real answers
    (`sessions_per_week = 3` is a perfectly plausible reply), so the bar credited work nobody
    had done. **NULL means "not answered yet". It never means "zero", "none" or "default", and
    nothing may substitute a fallback** — the generator must refuse to generate rather than
    assume a training frequency. ⚠️ `available_weekdays = 0` is a legal *mask* meaning "answered,
    no days", and **the API accepts and stores it** (`ge=0`); only the web client's own submit
    gate declines to send it, and a client-side gate is not an API property.
    `primary_discipline IS NULL` means no target grade yet, since it is derived from one.

    ## ⚠️ A step needs a `*_reviewed_at` column exactly when ZERO ROWS is a legitimate answer

    Exactly one step qualifies: `injuries_reviewed_at`, because "nothing is hurting" writes no
    `user_injury` rows and an empty child table otherwise cannot distinguish "asked, nothing"
    from "never asked". A timestamp rather than a boolean because "when did you last look at
    this?" is the question a future prompt would ask. **The other three steps must NOT get one**
    — the aspect step's answer is three scalar columns, and the grades and availability are
    scalars whose own NULL carries it. `equipment_reviewed_at` was the second and is **retired**
    with its step (`0006`, issue #54): nothing reads or writes it, it is absent from
    `ProfileResponse` and from the completion maths, and the column stays only because
    expand -> deploy -> contract says so. A profile with zero `user_equipment` rows is normal.

    ## `show_body_metrics` defaults to TRUE

    Off, **the weight trend and every %BW figure are hidden and nothing prompts for a weigh-in**
    — a real state with real behaviour, which is why `tests/test_schema_profile.py` covers both
    positions. On by default because %BW is the most useful strength number in climbing and a
    default of off would make it undiscoverable; it exists because for some climbers a weight
    number on a training screen is actively harmful, and "just don't look at it" is not a design.

    ⚠️ **There is no goal-weight, target-weight or BMI column here, and there must never be one.**
    See CLAUDE.md, "The app never recommends losing weight";
    `tests/test_schema_no_weight_targets.py` enforces it across the whole metadata.
    """

    __tablename__ = "user_profile"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    # NULL until a target grade is chosen: this is DERIVED from that grade's system, so
    # the two can never disagree. See the class docstring.
    primary_discipline: Mapped[Discipline | None] = mapped_column(discipline_enum, nullable=True)
    # The grade being trained for; NULL until onboarding asks. RESTRICT by default: a cascade
    # here would silently erase somebody's goal if a grade were ever retired.
    target_grade_id: Mapped[int | None] = mapped_column(ForeignKey("grade.id"), nullable=True)
    # ⚠️ Must sit on the same DISCIPLINE as the target (`server/profile/routes.py` enforces it):
    # the ladders are disjoint, so a Font grade under a French target is a row nothing can use.
    current_grade_id: Mapped[int | None] = mapped_column(ForeignKey("grade.id"), nullable=True)
    sessions_per_week: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    available_weekdays: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # The headline: one strength, one weakness, from the eight aspects. NULL until asked. See
    # `UserAspectRating` for why these exist alongside the eight scores, not instead of them.
    strength_aspect_id: Mapped[int | None] = mapped_column(
        ForeignKey("climbing_aspect.id"), nullable=True
    )
    weakness_aspect_id: Mapped[int | None] = mapped_column(
        ForeignKey("climbing_aspect.id"), nullable=True
    )
    # Free text, and the ELEVENTH row on CLAUDE.md's free-text inventory. NULL = never set; the
    # client offers the account's email as a starting value without persisting it.
    display_name: Mapped[str | None] = mapped_column(String(DISPLAY_NAME_MAX), nullable=True)
    show_body_metrics: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    # ⚠️ RETIRED (issue #54), deliberately still here: nothing reads or writes it. `DROP COLUMN`
    # on a table of real user rows is what expand -> deploy -> contract forbids; that is a later PR.
    equipment_reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # When the injuries step was last answered. NULL = never asked; a value with no rows in
    # `user_injury` = asked, nothing to record. Nothing else can express the second.
    injuries_reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Both CHECKs are unchanged by 0005 and still correct: a NULL is neither true nor
    # false to a CHECK, so it passes both without either constraint having to mention it.
    __table_args__ = (
        CheckConstraint("sessions_per_week BETWEEN 1 AND 7", name="sessions_per_week_in_range"),
        # 7 bits, Monday = bit 0. 0 is a legal mask, REACHABLE through the API ("answered, no
        # days"); "not answered" is NULL, a different thing, and the one the progress bar reads.
        CheckConstraint(
            "available_weekdays BETWEEN 0 AND 127", name="available_weekdays_is_7_bits"
        ),
        # One aspect cannot be both the strongest and the weakest thing about a climber.
        # `IS DISTINCT FROM` rather than `<>`, because `NULL <> NULL` is NULL and would pass
        # this vacuously in exactly the state the columns spend most of their life in — and
        # because both being NULL (nothing answered) has to stay legal.
        CheckConstraint(
            "strength_aspect_id IS NULL OR weakness_aspect_id IS NULL "
            "OR strength_aspect_id IS DISTINCT FROM weakness_aspect_id",
            name="strength_and_weakness_differ",
        ),
    )


class UserEquipment(Base):
    """What this user has access to. Composite PK, so a duplicate is impossible."""

    __tablename__ = "user_equipment"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), primary_key=True)


class UserAspectRating(Base):
    """A self-rated 1-5 score per aspect. Detail, not the headline.

    ⚠️ **This used to say "the generator's only picture of a weakness", and issue #54 made
    that false.** Eight 1-5 sliders were the aspect step, and they were the step most likely
    to hand the generator garbage: they are hard to answer honestly, and eight middling
    guesses look exactly like eight real answers. The headline is now
    `user_profile.strength_aspect_id` and `weakness_aspect_id` — one of each, which anybody
    can answer — and the eight scores are the optional detail behind a disclosure for
    someone who wants to be specific.

    So the generator has two pictures of a weakness and they are not equivalent:

    - **the profile's `weakness_aspect_id`** is a deliberate answer to a direct question,
      and is the one to trust;
    - **these rows** are finer-grained and may be nothing more than the default an
      untouched slider was left at, which is why the client marks a row it has moved.

    Both are still written together — picking a strength or a weakness also writes that
    aspect's score — so a profile never has one without the other.

    Self-rated rather than tested, because a testing protocol for eight aspects is a
    whole product of its own and this one has to work on day one. `rated_at` is here so
    a rating can be shown as stale ("you rated endurance 5 months ago").
    """

    __tablename__ = "user_aspect_rating"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    climbing_aspect_id: Mapped[int] = mapped_column(
        ForeignKey("climbing_aspect.id"), primary_key=True
    )
    score: Mapped[int] = mapped_column(SmallInteger)
    rated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="score_in_range"),)


class UserInjury(Base):
    """An injury flag, open or historical.

    A row per injury rather than a boolean per area, because "resolved in March" is
    information the generator should use (it can reintroduce the withheld exercises) and
    a flag that gets flipped back loses it. `resolved_on IS NULL` is the "currently
    injured" predicate; the note is free text and is treated as untrusted on output like
    every other note in the schema.
    """

    __tablename__ = "user_injury"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    injury_area_id: Mapped[int] = mapped_column(ForeignKey("injury_area.id"))
    note: Mapped[str | None] = mapped_column(String(SET_NOTE_MAX), nullable=True)
    started_on: Mapped[date] = mapped_column(Date)
    resolved_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        # The generator reads "this user's open injuries" on every generation.
        Index("ix_user_injury_user_id", "user_id"),
        # ⚠️ AT MOST ONE OPEN INJURY PER AREA (0005). A partial unique INDEX rather than a
        # constraint because Postgres has no partial unique *constraint*; the `uq_` name says
        # what it enforces rather than that it is also an access path.
        #
        # It closes a real race, not a hypothetical one: `PATCH /api/profile` reads the open
        # rows and then inserts the missing ones, so two concurrent requests both see "no
        # open elbow row" and both insert, leaving one area open twice — a duplicated
        # checkbox in the editor and a doubled contraindication in the generator. Resolved
        # rows are deliberately outside the predicate: flagging, resolving and re-flagging the
        # same area is the history this table exists to keep.
        Index(
            "uq_user_injury_open_area",
            "user_id",
            "injury_area_id",
            unique=True,
            postgresql_where=text("resolved_on IS NULL"),
        ),
        CheckConstraint(
            "resolved_on IS NULL OR resolved_on >= started_on", name="resolved_after_started"
        ),
    )


# --- The plan tree: prescription, NEVER mutated by logging. Fully relational, a row per set:
# a 24-week plan is ~290 KB of a 0.5 GB budget, so `jsonb` would save nothing and cost queries.


class Plan(Base):
    """A training plan: the root of the prescription tree.

    `generator_version` + `generator_input` make a plan **reproducible**: re-running version X
    against the same input must produce the same tree, which is what makes a generator change
    reviewable and v2's "adapt from logged data" possible. `generator_input` is `jsonb` because
    its shape belongs to the generator and nothing queries inside it.

    Lifecycle is three nullable timestamps rather than a status enum, because the diary wants the
    dates and an enum records only *that*. "Active" is
    `activated_at IS NOT NULL AND abandoned_at IS NULL AND completed_at IS NULL`.

    **One-active-plan-per-user is enforced here too, by `uq_plan_one_active_per_user`** — a
    partial unique index on `user_id` whose predicate is that sentence verbatim (`0008`;
    `uq_user_injury_open_area` is the precedent, and Postgres has no partial unique *constraint*).
    ⚠️ **Keep the predicate and the sentence above character-identical**: two definitions of
    "active" that drift is an invariant that holds for only one of them.
    ⚠️ **The index does not replace the endpoint's obligation, and neither is sufficient alone.**
    `server/plans/routes.py::create_plan` stands the previous plan down in the same transaction
    that activates the new one, because the index can only *refuse* a second active row, never
    choose which survives. What the index buys is that a concurrent double-tap is a `409`.

    `generator_caveats` is the third generation column and is `jsonb`: what the generator *said*
    about the plan it built. Stored because none of it is recoverable from the tree — a block's
    shortfall names the aspect the generator WANTED and could not fill — and because without it
    the `/plan` screen loses every equipment-gap banner on reload. **One column, not four**: one
    fact, written by one statement, read by one screen, queried by nothing; the alternative was
    ~2,400 NULLs per plan on `session_block`. ⚠️ `_StoredCaveats` treats a shape it does not
    recognise as "no caveats" rather than raising, so no change to `Shortfall` or `ScheduleNote`
    can make an already-persisted plan unopenable.

    `current_grade_id` is **stored, not derived**: the profile's current grade drifts as the
    climber improves, and `generator_input` carries the *ordinal*, not the id. `NO ACTION` and
    deliberately unindexed, like `target_grade_id` — `grade` is reference data nothing deletes,
    so there is no referencing-side scan for an index to save.
    """

    __tablename__ = "plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    discipline: Mapped[Discipline] = mapped_column(discipline_enum)
    target_grade_id: Mapped[int | None] = mapped_column(ForeignKey("grade.id"), nullable=True)
    current_grade_id: Mapped[int | None] = mapped_column(ForeignKey("grade.id"), nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    week_count: Mapped[int] = mapped_column(SmallInteger)
    generator_version: Mapped[str] = mapped_column(String(32))
    generator_input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # ⚠️ Server-written only, and read DEFENSIVELY — see the docstring section above.
    generator_caveats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    abandoned_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    mesocycles: Mapped[list["Mesocycle"]] = relationship(
        back_populates="plan",
        order_by="Mesocycle.start_week",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # "this user's plans, newest first" and "this user's active plan" both land here.
        Index("ix_plan_user_id_created_at", "user_id", "created_at"),
        # At most one active plan per user. ⚠️ `text(...)`, never `func.text(...)` — the
        # latter compiles to a nonsense function call that type-checks, lints and passes
        # every local test, then fails against real Postgres (the trap `0005` documents).
        # The predicate must stay character-identical to this class's docstring.
        Index(
            "uq_plan_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "activated_at IS NOT NULL AND abandoned_at IS NULL AND completed_at IS NULL"
            ),
        ),
        CheckConstraint("week_count BETWEEN 1 AND 52", name="week_count_in_range"),
    )


class Mesocycle(Base):
    """A phase block spanning whole weeks. `start_week` / `end_week` are 1-based and inclusive;
    `UNIQUE (id, plan_id)` is not hygiene but the target of `microcycle`'s composite FK."""

    __tablename__ = "mesocycle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id", ondelete="CASCADE"))
    phase: Mapped[Phase] = mapped_column(phase_enum)
    start_week: Mapped[int] = mapped_column(SmallInteger)
    end_week: Mapped[int] = mapped_column(SmallInteger)

    plan: Mapped[Plan] = relationship(back_populates="mesocycles")
    microcycles: Mapped[list["Microcycle"]] = relationship(
        back_populates="mesocycle",
        order_by="Microcycle.week_no",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("plan_id", "start_week"),
        # Referenced by fk_microcycle_mesocycle_id_plan_id_mesocycle. Keep it.
        UniqueConstraint("id", "plan_id"),
        CheckConstraint("start_week >= 1", name="start_week_positive"),
        CheckConstraint("end_week >= start_week", name="end_week_after_start"),
    )


class Microcycle(Base):
    """One week of a plan.

    ## Why `plan_id` is here as well as on the parent

    The query pattern settled in CLAUDE.md is `(plan_id, week_no)` — "week 7 of this
    plan" — and reaching it through `mesocycle` costs a join on the hottest read in the
    app. So `plan_id` is carried down, and the denormalisation is made **safe rather
    than trusted** by a composite foreign key: `(mesocycle_id, plan_id)` references
    `mesocycle (id, plan_id)`, so a row whose `plan_id` disagrees with its mesocycle's
    is rejected by Postgres. Without that constraint this column would be the classic
    denormalisation that is correct until the first bulk insert with a transposed
    argument.

    There is deliberately **no second foreign key straight to `plan`**: the composite one
    already guarantees the plan exists, and two paths to the same parent is how
    `ON DELETE` behaviour starts disagreeing with itself.

    `UNIQUE (plan_id, week_no)` doubles as the index the plan sketch asked for — a
    unique constraint *is* a btree index in Postgres, so a separate `ix_` would be a
    second copy of the same tree.
    """

    __tablename__ = "microcycle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mesocycle_id: Mapped[int] = mapped_column(Integer)
    plan_id: Mapped[int] = mapped_column(Integer)
    week_no: Mapped[int] = mapped_column(SmallInteger)
    start_date: Mapped[date] = mapped_column(Date)
    is_deload: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)

    mesocycle: Mapped[Mesocycle] = relationship(back_populates="microcycles")
    planned_sessions: Mapped[list["PlannedSession"]] = relationship(
        back_populates="microcycle",
        order_by="PlannedSession.weekday",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["mesocycle_id", "plan_id"],
            ["mesocycle.id", "mesocycle.plan_id"],
            name="fk_microcycle_mesocycle_id_plan_id_mesocycle",
            ondelete="CASCADE",
        ),
        UniqueConstraint("plan_id", "week_no"),
        # ⚠️ Required by the composite CASCADE above, and easy to believe is already
        # covered. It is not: the two unique constraints on this table lead with `plan_id`
        # and `id`, so the foreign key's own leading column `mesocycle_id` has no usable
        # index at all — and deleting a plan cascades through every mesocycle in it. Two
        # columns, matching the FK exactly, rather than one on `mesocycle_id`: the cascade
        # looks both up.
        Index("ix_microcycle_mesocycle_id_plan_id", "mesocycle_id", "plan_id"),
        CheckConstraint("week_no >= 1", name="week_no_positive"),
    )


class PlannedSession(Base):
    """One prescribed session on one day of one week.

    ## `activity_kind` on a *planned* session is what makes adherence honest

    A plan can prescribe a run or a mobility slot, not only a climbing session. The slot
    carries the kind it expects; whether a given logged activity satisfies it is a
    **query**, not a constraint — deliberately, because the rule ("a non-climbing
    activity satisfies a planned slot; every activity counts as load regardless") is
    product logic that will be tuned, and a schema that hard-coded it would have to be
    migrated to tune it. See `Activity.planned_session_id`.

    `weekday` is 0-6 with Monday = 0, matching `UserProfile.available_weekdays`.
    `scheduled_on` is stored rather than computed from the microcycle's start date so
    that moving a session to Thursday is a single UPDATE and the diary can order by a
    real date without arithmetic.
    """

    __tablename__ = "planned_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    microcycle_id: Mapped[int] = mapped_column(ForeignKey("microcycle.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    scheduled_on: Mapped[date] = mapped_column(Date)
    activity_kind: Mapped[ActivityKind] = mapped_column(
        activity_kind_enum, server_default=text("'climbing'")
    )
    status: Mapped[SessionStatus] = mapped_column(
        session_status_enum, server_default=text("'planned'")
    )
    title: Mapped[str] = mapped_column(String(80))
    estimated_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    microcycle: Mapped[Microcycle] = relationship(back_populates="planned_sessions")
    blocks: Mapped[list["SessionBlock"]] = relationship(
        back_populates="planned_session",
        order_by="SessionBlock.order_index",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("microcycle_id", "weekday"),
        Index("ix_planned_session_scheduled_on", "scheduled_on"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_in_range"),
    )


class SessionBlock(Base):
    """One exercise within a planned session, with the protocol it is run under.

    `protocol_kind` is **snapshotted from the exercise**, not read through the foreign
    key, so that re-authoring the library never silently rewrites a plan somebody is
    halfway through. The same reasoning is why `prescribed_set` holds real numbers rather
    than pointing at a `prescription_template`.

    ⚠️ **The ASPECT is the one thing not snapshotted, and it is a known, accepted
    asymmetry.** `BlockOut.aspect_key` is read live from `exercise.climbing_aspect_id`
    (`server/plans/routes.py::_exercise_reference`), so re-authoring an exercise's aspect
    changes what an already-persisted plan says a block trains — exactly what the snapshot
    above exists to prevent. Not a bug today: nothing keys off it and the aspect is the most
    stable field on an exercise. Recorded so it is a decision rather than a mystery; the fix
    would be a `climbing_aspect_id` column here, and it belongs to whichever PR first needs
    the aspect to be historically true.
    """

    __tablename__ = "session_block"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planned_session_id: Mapped[int] = mapped_column(
        ForeignKey("planned_session.id", ondelete="CASCADE")
    )
    order_index: Mapped[int] = mapped_column(SmallInteger)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    protocol_kind: Mapped[ProtocolKind] = mapped_column(protocol_kind_enum)
    # ⚠️ THREE distinct rests, none may absorb another: `prescribed_set.target_rest_seconds` is
    # within a set, this is between sets of the block, `rest_after_seconds` is after the block.
    rest_between_sets_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rest_after_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    planned_session: Mapped[PlannedSession] = relationship(back_populates="blocks")
    prescribed_sets: Mapped[list["PrescribedSet"]] = relationship(
        back_populates="session_block",
        order_by="PrescribedSet.set_index",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("planned_session_id", "order_index"),)


class PrescribedSet(Base):
    """The leaf of the plan tree. `target_load_kg` is ADDED load (belt weight), never bodyweight;
    nullable targets throughout beat a table per protocol, read through one player loop."""

    __tablename__ = "prescribed_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_block_id: Mapped[int] = mapped_column(
        ForeignKey("session_block.id", ondelete="CASCADE")
    )
    set_index: Mapped[int] = mapped_column(SmallInteger)
    target_reps: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    target_work_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    target_rest_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    target_load_kg: Mapped[Decimal | None] = mapped_column(KILOGRAMS, nullable=True)
    target_intensity_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    target_rpe: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    target_grade_id: Mapped[int | None] = mapped_column(ForeignKey("grade.id"), nullable=True)

    session_block: Mapped[SessionBlock] = relationship(back_populates="prescribed_sets")

    __table_args__ = (
        UniqueConstraint("session_block_id", "set_index"),
        CheckConstraint("set_index >= 1", name="set_index_positive"),
        CheckConstraint(
            "target_rpe IS NULL OR (target_rpe BETWEEN 1 AND 10)", name="target_rpe_in_range"
        ),
        # Matches `prescription_template.intensity_pct`, which this is generated from: a bound
        # on the template alone would let the generator write a value it could never hold.
        CheckConstraint(
            "target_intensity_pct IS NULL OR (target_intensity_pct BETWEEN 1 AND 200)",
            name="target_intensity_pct_sane",
        ),
    )


# --- Logging — kept strictly distinct from prescription ---


class Activity(Base):
    """**The supertype: anything the user did that counts as training load.**

    ## Why this table exists at all

    The obvious design is a single `logged_session` table for climbing, and then — the
    first time cardio or a mobility routine needs logging — a second table beside it with
    its own date, its own duration, its own RPE and its own idempotency key. At that
    point every readiness calculation, every rest-day check and every diary query has to
    be written twice and kept in agreement, and the second copy is always the one that
    is forgotten. Issue #38 (complementary training) makes that future concrete, so the
    supertype is here on day one, before there is any data to migrate.

    So: **one row per activity, whatever kind it was.** `logged_session` is a 1:1 subtype
    carrying only the columns that are meaningless for a bike ride.

    ## `srpe_load` lives here, not on `logged_session`

    `GENERATED ... STORED` can only reference columns of its own table, and `rpe` and
    `duration_minutes` are supertype columns — so this is the only table the generated
    column *can* live on. That turns out to be the right answer anyway: the load score
    for an easy run is as real as the load score for a session, and ACWR that ignored it
    would understate a heavy week. NULL `rpe` yields NULL `srpe_load`, which is honest —
    an activity logged without an RPE has no load score, rather than a load score of zero.

    ## Adherence vs load — both readings, one column

    `planned_session_id` is nullable and is the *only* thing that links an activity to
    the plan. Adherence is therefore "activities that point at a planned slot", and load
    is "all activities" — two queries over one column, and neither rule is baked into a
    constraint, because both will be tuned in PR #11.

    ## Idempotent replay

    `client_uuid` is minted by the client and unique **per user**, so the outbox can
    replay a flush with `ON CONFLICT (user_id, client_uuid) DO UPDATE` and never double
    up a session. Scoped to the user rather than globally so one client's collision can
    never block another account's write.
    """

    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    activity_kind: Mapped[ActivityKind] = mapped_column(activity_kind_enum)
    # The training *day*, which every rolling window groups by. A date, not a timestamp: a
    # session starting at 23:30 belongs to the day the climber says it does.
    occurred_on: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger)
    rpe: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Session RPE x minutes: the standard sRPE load. STORED rather than a view or an
    # application-side product so that every reader — the API, a raw window-function
    # query, psql — gets the same number, and so ACWR can be a plain window over it.
    #
    # ⚠️ **`rpe::integer` is not decoration.** Both operands are `SMALLINT`, so
    # `rpe * duration_minutes` resolves as `int2 * int2 -> int2` and raises `smallint out
    # of range` BEFORE the widening cast to this INTEGER column. A client that sent the
    # duration in seconds by mistake (a 90-minute session as 5400, RPE 7 -> 37800) would
    # abort the whole INSERT — and on the outbox path that payload retries forever and can
    # never succeed. The cast makes the arithmetic int4; the CHECK below is what actually
    # rejects the bad value, and the Pydantic bound in PR #9 is what turns it into a 422
    # instead of a retry loop. All three, because each catches it at a different distance.
    srpe_load: Mapped[int | None] = mapped_column(
        Integer, Computed("rpe::integer * duration_minutes", persisted=True), nullable=True
    )
    planned_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("planned_session.id", ondelete="SET NULL"), nullable=True
    )
    client_uuid: Mapped[uuid.UUID] = mapped_column(Uuid())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    climbing_session: Mapped["LoggedSession | None"] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "client_uuid"),
        # Referenced by fk_logged_session_activity_id_activity_kind_activity, which is
        # what stops a `logged_session` attaching itself to a bike ride. Keep it.
        UniqueConstraint("id", "activity_kind"),
        # "this user's training, newest first" — the diary, the readiness window and the
        # rest-day check. No DESC: a two-column btree is scanned backwards at the same
        # cost, and an explicit DESC would make this an expression index that Alembic
        # compares poorly for no gain.
        Index("ix_activity_user_id_occurred_on", "user_id", "occurred_on"),
        # ⚠️ Required by the `ON DELETE SET NULL` on `planned_session_id`. Postgres does
        # NOT index the referencing side of a foreign key, and it must find these rows to
        # null them — so without this index, deleting a plan cascades to its ~1000
        # `planned_session`/`prescribed_set` rows and each one sequentially scans this
        # table. That is invisible to every test and to CI, and it is billed directly as
        # Neon awake time. The same reasoning applies to `logged_set.prescribed_set_id`,
        # `ascent.logged_session_id` and `journal_entry.logged_session_id`.
        #
        # **The rule is: every `SET NULL` or `CASCADE` foreign key needs an index whose
        # LEADING column is the first FK column.** Most in this schema get it free from a
        # composite primary key or a unique constraint that happens to lead with the right
        # column — `logged_set`'s `uq (logged_session_id, client_uuid)`, `plan`'s
        # `ix (user_id, created_at)` and so on. Six do not and are declared explicitly:
        # these four, plus `microcycle (mesocycle_id, plan_id)`,
        # `exercise_equipment (equipment_id)` and
        # `exercise_contraindication (injury_area_id)`.
        #
        # **Every other foreign key here is `NO ACTION` or `RESTRICT` and is deliberately
        # unindexed.** That is a different argument, not an oversight: those parents are
        # reference rows the seed never deletes (`grade`, `exercise`, `equipment`,
        # `climbing_aspect`, `injury_area`, `ascent_tag`) or, for `app_user.invite_id`,
        # a row that RESTRICT exists to make undeletable. No delete means no referencing-side
        # scan, so there is nothing for an index to save. Do not "complete the set" by
        # indexing them — that is a dozen indexes bought with write cost and storage against
        # a 0.5 GB budget, for lookups nothing performs.
        Index("ix_activity_planned_session_id", "planned_session_id"),
        # 1..1440 = one minute to twenty-four hours: outside that is a unit error, not a long
        # day. It is also what keeps `srpe_load` inside int4 (10 * 1440 = 14400).
        CheckConstraint("duration_minutes BETWEEN 1 AND 1440", name="duration_in_range"),
        CheckConstraint("rpe IS NULL OR (rpe BETWEEN 1 AND 10)", name="rpe_in_range"),
    )


class LoggedSession(Base):
    """The climbing-only half of an activity. 1:1 subtype of `Activity`.

    ## How the subtype is wired, and why it is structural

    `activity_id` is the primary key *and* a foreign key, so there can be at most one
    subtype row per activity. On top of that, `activity_kind` is repeated here with a
    `CHECK (activity_kind = 'climbing')` and a **composite foreign key** to
    `activity (id, activity_kind)` — so Postgres itself refuses to hang a logged session
    off a cardio activity. The repeated column looks redundant read on its own; it is
    the price of the guarantee, and the guarantee is the entire point of having a
    supertype (see `Activity`).

    SQLAlchemy joined-table inheritance was considered and not used: it wants a
    polymorphic identity per discriminator value, and four of the five `activity_kind`
    values have no subclass at all. A plain 1:1 relationship says exactly what is true.

    ## Two free-text fields here, and `location` is the one that gets forgotten

    `notes` and `location` are both user-typed. There are **nine** such fields in the
    schema — `logged_session.notes`, `logged_session.location`, `logged_set.note`,
    `ascent.name`, `ascent.notes`, `journal_entry.body`, `user_injury.note`, `plan.name`,
    `planned_session.title` — plus email and password at registration. CLAUDE.md carries
    the canonical list; an earlier version of this docstring said "one of the four", which
    was the diary-notes count and left `location` and `user_injury.note` out of a rule
    that binds them. Every one of them is untrusted on **output** as well as input: never
    `dangerouslySetInnerHTML`, not even for "a bit of markdown", not even for a gym name.
    """

    __tablename__ = "logged_session"

    activity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_kind: Mapped[ActivityKind] = mapped_column(
        activity_kind_enum, server_default=text("'climbing'")
    )
    discipline: Mapped[Discipline] = mapped_column(discipline_enum)
    location: Mapped[str | None] = mapped_column(String(LOCATION_MAX), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(NOTES_MAX), nullable=True)

    activity: Mapped[Activity] = relationship(back_populates="climbing_session")
    sets: Mapped[list["LoggedSet"]] = relationship(
        back_populates="logged_session",
        order_by="LoggedSet.set_index",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "activity_kind"],
            ["activity.id", "activity.activity_kind"],
            name="fk_logged_session_activity_id_activity_kind_activity",
            ondelete="CASCADE",
        ),
        CheckConstraint("activity_kind = 'climbing'", name="activity_kind_is_climbing"),
        # `simple`, not `english`: no stemming or stopwords, right for short mixed-language
        # notes full of proper nouns ('Cafe Kraft', 'Font'). Expression index, so no phantom diff.
        Index(
            "ix_logged_session_notes_tsv",
            text("to_tsvector('simple', notes)"),
            postgresql_using="gin",
            postgresql_where=text("notes IS NOT NULL"),
        ),
    )


class LoggedSet(Base):
    """What actually happened in one set. Never a mutation of `prescribed_set`.

    `prescribed_set_id` is nullable: a set done off-plan is a first-class thing to record, and
    forcing it to point at a prescription is how a log starts lying. `exercise_id` is NOT
    nullable, because "what did I do" has to be answerable.

    `body_weight_kg` is a **snapshot** from the most recent weigh-in within about a week, copied
    on at write time, with `body_weight_as_of` recording which day. Not a join to the latest
    `journal_entry`: %BW is displayed attached to a *performance*, so deriving it live would
    silently restate every historical figure the next time somebody steps on a scale. A figure
    that changes retroactively is worse than a missing one. **Nullable, always** — there may be
    no recent weigh-in, and with `show_body_metrics` off nothing prompts for one;
    `tests/test_schema_no_weight_targets.py` guards that nullability, because a NOT NULL here
    would mean demanding a weight before recording a performance.

    `UNIQUE (logged_session_id, client_uuid)` is the outbox contract: the Tier-2 flush replays
    with `ON CONFLICT ... DO UPDATE`, so a retried flush updates rather than duplicates.

    ## ⚠️ One invariant here is NOT structural, and that is a deliberate choice

    With `prescribed_set_id` set, `exercise_id` should equal
    `prescribed_set -> session_block.exercise_id`. Nothing in the database enforces it: **it is
    a write-path invariant (issue #62), asserted with a 422 by `server/sessions/routes.py`**,
    which refuses the whole flush. Making it structural was rejected on cost — the composite-FK
    technique needs the parent to expose the column, so it would mean denormalising `exercise_id`
    onto `prescribed_set` plus a `UNIQUE (id, exercise_id)` on both, two columns and three
    constraints across a tree that exists to hold prescriptions. The damage is milder than the
    ones that *are* enforced (a set filed against the wrong exercise, not a discipline
    reclassified), and the nullable FK would be MATCH SIMPLE anyway, so off-plan sets would be
    unconstrained either way.
    """

    __tablename__ = "logged_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    logged_session_id: Mapped[int] = mapped_column(
        ForeignKey("logged_session.activity_id", ondelete="CASCADE")
    )
    client_uuid: Mapped[uuid.UUID] = mapped_column(Uuid())
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    prescribed_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("prescribed_set.id", ondelete="SET NULL"), nullable=True
    )
    set_index: Mapped[int] = mapped_column(SmallInteger)
    actual_reps: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    actual_work_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    actual_load_kg: Mapped[Decimal | None] = mapped_column(KILOGRAMS, nullable=True)
    rpe: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    body_weight_kg: Mapped[Decimal | None] = mapped_column(KILOGRAMS, nullable=True)
    body_weight_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(String(SET_NOTE_MAX), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    logged_session: Mapped[LoggedSession] = relationship(back_populates="sets")

    __table_args__ = (
        UniqueConstraint("logged_session_id", "client_uuid"),
        # "the last time I did this exercise", which is what puts last session's note in
        # front of the user when they open the same exercise again.
        Index("ix_logged_set_exercise_id", "exercise_id"),
        # ⚠️ Required by the `ON DELETE SET NULL` on `prescribed_set_id`, and this is the
        # worst of the four to omit: `logged_set` is the largest table in the app, and
        # abandoning a 24-week plan deletes ~1000 prescribed sets, each of which would
        # otherwise sequentially scan all of it. See Activity's matching index.
        Index("ix_logged_set_prescribed_set_id", "prescribed_set_id"),
        CheckConstraint("set_index >= 1", name="set_index_positive"),
        CheckConstraint("actual_reps IS NULL OR actual_reps >= 0", name="actual_reps_not_negative"),
        CheckConstraint(
            "actual_work_seconds IS NULL OR actual_work_seconds >= 0",
            name="actual_work_seconds_not_negative",
        ),
        CheckConstraint("rpe IS NULL OR (rpe BETWEEN 1 AND 10)", name="rpe_in_range"),
        CheckConstraint(
            "body_weight_kg IS NULL OR (body_weight_kg BETWEEN 20 AND 300)",
            name="body_weight_kg_sane",
        ),
        # Per-set notes are searched alongside the longer prose. Partial, because most
        # sets have no note and an index over mostly-NULL rows should not pay for them.
        Index(
            "ix_logged_set_note_tsv",
            text("to_tsvector('simple', note)"),
            postgresql_using="gin",
            postgresql_where=text("note IS NOT NULL"),
        ),
    )


class Ascent(Base):
    """A climb, logged. The emotional payload of the whole app — always a Tier-1 write.

    ## Grade is stored twice, on purpose

    `grade_id` is the grade **as given** (so the label the climber chose is what comes
    back), and `grade_ordinal` is the ladder position copied alongside it. The copy is
    what makes the send pyramid a single indexed scan instead of a join through
    `grade_system`, and — because the ladders are banded per discipline — the boulder
    pyramid is `grade_ordinal BETWEEN 1000 AND 1999` on that same index. That is why
    there is no `discipline` column here: the band **is** the discipline, and a third
    copy of the same fact would be a third thing to keep in step.

    Never accept a client-supplied ordinal: resolve `grade_id` against the seeded table
    and read the ordinal from the row.

    **And the copy is made safe, not trusted**, by the composite foreign key on
    `(grade_id, grade_ordinal) -> grade (id, ordinal)` — the same technique `microcycle`
    and `logged_session` use. Without it, a transposed argument in a bulk insert writes an
    ordinal that belongs to a different rung, and because the band IS the discipline, a
    French 7a rope send silently files itself in the boulder pyramid with nothing to
    recover the truth from. There is deliberately no additional band CHECK: the foreign
    key already guarantees the ordinal is *that grade's* ordinal, so a band check would
    restate an existing guarantee.

    `logged_session_id` is nullable — an ascent at the crag on a rest day is not part of
    a training session, and refusing to record it would be the schema arguing with
    reality.

    Tags live in `ascent_tag_link`, a join to the seeded `ascent_tag` vocabulary. They
    were `text[]` + a GIN index until 2026-08-21; see `AscentTag` for why that reversed.
    """

    __tablename__ = "ascent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    logged_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("logged_session.activity_id", ondelete="SET NULL"), nullable=True
    )
    climbed_on: Mapped[date] = mapped_column(Date)
    # The route or problem name. Free text because a climb log without names is not a climb
    # log; bounded, escaped on output, never used to build SQL.
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # No single-column ForeignKey: the composite constraint below covers both grade columns,
    # and a second path to `grade` would be a second ON DELETE policy to keep in step.
    grade_id: Mapped[int] = mapped_column(Integer)
    grade_ordinal: Mapped[int] = mapped_column(SmallInteger)
    style: Mapped[AscentStyle] = mapped_column(ascent_style_enum)
    attempts: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Degrees of overhang on a board or wall. Negative for slabs, so the range is wider
    # than a system board's 0-70.
    board_angle: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rpe: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(ASCENT_NOTES_MAX), nullable=True)
    client_uuid: Mapped[uuid.UUID] = mapped_column(Uuid())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        # The ordinal is the grade's ordinal, guaranteed. See the class docstring.
        ForeignKeyConstraint(
            ["grade_id", "grade_ordinal"],
            ["grade.id", "grade.ordinal"],
            name="fk_ascent_grade_id_grade_ordinal_grade",
        ),
        UniqueConstraint("user_id", "client_uuid"),
        # The diary timeline. Ascending, scanned backwards — see Activity's index.
        Index("ix_ascent_user_id_climbed_on", "user_id", "climbed_on"),
        # The send pyramid, and the discipline filter that rides on the same index.
        Index("ix_ascent_user_id_grade_ordinal", "user_id", "grade_ordinal"),
        # ⚠️ Required by the `ON DELETE SET NULL` above: without it, deleting one logged session
        # sequentially scans every ascent in the database. See `Activity`'s index for the why.
        Index("ix_ascent_logged_session_id", "logged_session_id"),
        Index(
            "ix_ascent_notes_tsv",
            text("to_tsvector('simple', notes)"),
            postgresql_using="gin",
            postgresql_where=text("notes IS NOT NULL"),
        ),
        CheckConstraint("attempts IS NULL OR attempts >= 1", name="attempts_positive"),
        CheckConstraint(
            "board_angle IS NULL OR (board_angle BETWEEN -60 AND 90)", name="board_angle_in_range"
        ),
        CheckConstraint("rpe IS NULL OR (rpe BETWEEN 1 AND 10)", name="rpe_in_range"),
    )


class AscentTagLink(Base):
    """Which tags a climb carries. `ascent_id` cascades; `ascent_tag_id` deliberately does NOT —
    a tag somebody has used must not be removable out from under their history."""

    __tablename__ = "ascent_tag_link"

    ascent_id: Mapped[int] = mapped_column(
        ForeignKey("ascent.id", ondelete="CASCADE"), primary_key=True
    )
    ascent_tag_id: Mapped[int] = mapped_column(ForeignKey("ascent_tag.id"), primary_key=True)

    __table_args__ = (
        # The composite PK serves "this ascent's tags"; this serves the reverse — "every
        # ascent tagged crimpy", which is the aggregate the fixed vocabulary exists for.
        Index("ix_ascent_tag_link_ascent_tag_id", "ascent_tag_id"),
    )


class JournalEntry(Base):
    """A diary entry that is not attached to a set or a climb.

    Notes primarily live **on the thing they describe** — `logged_session.notes`,
    `logged_set.note`, `ascent.notes` (and see `LoggedSession` for the full nine-field
    free-text inventory) — because that is what makes them useful later
    (last session's note reappears when the same exercise comes up again). This table is
    for the rest: "fingers feel tweaky, backing off the crimps this week".

    `logged_session_id` is nullable, so an entry may optionally hang off a session
    without being one of its notes.

    ## `body_weight_kg`, and the one thing that must never be built on it

    A weigh-in is recorded here, and it is the source the `logged_set` snapshot copies
    from. **The trend is smoothed / rolling only** — never a raw day-to-day line, which
    is noise (hydration, food, time of day) presented as signal.

    ⚠️ **There is no goal weight, target weight or BMI column here or anywhere else in
    this schema, and the app never recommends losing weight.** Low strength-to-weight
    produces "get stronger", never "get lighter". Climbing has a documented
    disordered-eating problem; see "The app never recommends losing weight" in CLAUDE.md
    for the full reasoning, and `tests/test_schema_no_weight_targets.py` for the guard
    that fails the build if a column like that ever appears.

    Diet, when it arrives, is **habits-only** — no calorie logging, no food diary, no
    nutrient columns. Note that there is no table for it here.

    The CHECK is what stops an empty row: an entry has to carry *something*, and a
    weigh-in on its own counts, so `body` is nullable rather than forcing the client to
    send an empty string to record 71.4 kg.
    """

    __tablename__ = "journal_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    entry_date: Mapped[date] = mapped_column(Date)
    body: Mapped[str | None] = mapped_column(String(JOURNAL_BODY_MAX), nullable=True)
    feel: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    sleep_quality: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    skin: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    body_weight_kg: Mapped[Decimal | None] = mapped_column(KILOGRAMS, nullable=True)
    logged_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("logged_session.activity_id", ondelete="SET NULL"), nullable=True
    )
    client_uuid: Mapped[uuid.UUID] = mapped_column(Uuid())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "client_uuid"),
        Index("ix_journal_entry_user_id_entry_date", "user_id", "entry_date"),
        # ⚠️ Required by the `ON DELETE SET NULL` on `logged_session_id`. See Activity's
        # matching index for why an unindexed referencing side is a Neon awake-time bill.
        Index("ix_journal_entry_logged_session_id", "logged_session_id"),
        Index(
            "ix_journal_entry_body_tsv",
            text("to_tsvector('simple', body)"),
            postgresql_using="gin",
            postgresql_where=text("body IS NOT NULL"),
        ),
        CheckConstraint("feel IS NULL OR (feel BETWEEN 1 AND 5)", name="feel_in_range"),
        CheckConstraint(
            "sleep_quality IS NULL OR (sleep_quality BETWEEN 1 AND 5)",
            name="sleep_quality_in_range",
        ),
        CheckConstraint("skin IS NULL OR (skin BETWEEN 1 AND 5)", name="skin_in_range"),
        CheckConstraint(
            "body_weight_kg IS NULL OR (body_weight_kg BETWEEN 20 AND 300)",
            name="body_weight_kg_sane",
        ),
        CheckConstraint(
            "body IS NOT NULL OR feel IS NOT NULL OR sleep_quality IS NOT NULL "
            "OR skin IS NOT NULL OR body_weight_kg IS NOT NULL",
            name="not_empty",
        ),
    )
