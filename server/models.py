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

from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    UniqueConstraint,
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
