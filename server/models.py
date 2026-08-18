"""SQLAlchemy 2 declarative models.

Two things in this file are infrastructure rather than schema, and both exist to stop
a class of future mistake:

1. **An explicit constraint naming convention** on the metadata. Without it Postgres
   invents names like `grade_grade_system_id_label_key`, Alembic autogenerate emits
   `None` for the name, and a later `op.drop_constraint` has nothing stable to name.
   With it, every index and constraint name is derivable from the model, so
   autogenerate diffs are small and reviewable and `alembic check` is meaningful.

2. **`type_annotation_map` pinning `datetime` to `TIMESTAMP(timezone=True)`** —
   i.e. `TIMESTAMPTZ`, never a naive timestamp. This is repo-wide and automatic: any
   future `Mapped[datetime]` gets it without anyone having to remember. Naive
   timestamps are the classic thing that is fine until the first user trains in
   another timezone or a DST boundary lands mid-session, and by then there is data to
   migrate. Store aware, convert at the edge.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from server.domain.grades import Discipline

# `column_0_N_name` joins every column in the constraint, so a two-column unique
# constraint gets both names — which is what makes the name predictable from the model.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Native Postgres enum. Closed vocabularies get a real type: it is type-safe and cheap,
# and the price (an `ALTER TYPE ... ADD VALUE` migration to extend it) is acceptable for
# a genuinely closed set. `values_callable` stores the enum's *values* ('boulder'), not
# its Python member names ('BOULDER') — the default would put SCREAMING_CASE in the
# database and in every JSON payload.
discipline_enum = Enum(
    Discipline,
    name="discipline",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: TIMESTAMP(timezone=True)}


class GradeSystem(Base):
    """A grading scale. A lookup table, not an enum: it carries user-facing content.

    `key` is the stable machine identifier (`server.domain.grades.GradeSystemKey`) and
    is what code matches on; `name` is display only, and `id` is what other tables
    reference.
    """

    __tablename__ = "grade_system"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    discipline: Mapped[Discipline] = mapped_column(discipline_enum)

    grades: Mapped[list["Grade"]] = relationship(
        back_populates="grade_system",
        order_by="Grade.ordinal",
    )


class Grade(Base):
    """One rung of one scale.

    `ordinal` is the shared integer ladder — see `server/domain/grades.py`. It is the
    *comparable* half of a grade; `label` is display only. Never persist a grade as a
    label alone, and never accept an `ordinal` from a client: the API takes a
    `grade_id` that must resolve against this table.
    """

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
    """

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    # argon2id encoded hash ("$argon2id$v=19$m=47104,t=1,p=1$..."), ~100 chars at the
    # profile in server/auth/passwords.py. 255 leaves room for a future parameter bump.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    # `Mapped[datetime]` picks up TIMESTAMPTZ from `type_annotation_map` above. The
    # default is a SERVER default so the timestamp is the database's clock, not a
    # serverless function's — the two disagree often enough to matter for ordering.
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
