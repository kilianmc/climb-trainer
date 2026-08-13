"""The grade ladder as it actually lands in Postgres.

These tests **skip without `DATABASE_URL`** (see conftest) and run in CI against the
postgres service container after `alembic upgrade head` — which is the point: they are
what proves the *migration* and the *seed* agree with the domain module, not just that
the domain module agrees with itself. `tests/test_grades.py` covers the pure logic.

Deliberately not tested here: that `select()` returns rows, that a relationship loads,
or anything else that would be testing SQLAlchemy rather than this schema.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.domain.grades import GRADE_SYSTEMS, GRADES
from server.models import Grade, GradeSystem
from server.seed import seed_reference_data


def test_seeded_rows_match_the_domain_ladder_exactly(db_session: Session) -> None:
    """No drift between `server/domain/grades.py` and the table the app queries."""
    rows = db_session.execute(
        select(GradeSystem.key, Grade.label, Grade.ordinal).join(
            Grade, Grade.grade_system_id == GradeSystem.id
        )
    ).all()
    assert {(key, label, ordinal) for key, label, ordinal in rows} == {
        (grade.system.value, grade.label, grade.ordinal) for grade in GRADES
    }


def test_seed_is_idempotent(db_session: Session) -> None:
    """It runs on every migration and in every CI job, so re-running must be a no-op.

    Duplicating reference data would break the `grade_id` a user's profile points at.
    """
    before = db_session.scalar(select(func.count()).select_from(Grade))
    seed_reference_data(db_session)
    seed_reference_data(db_session)
    assert db_session.scalar(select(func.count()).select_from(Grade)) == before
    assert before == len(GRADES)
    assert db_session.scalar(select(func.count()).select_from(GradeSystem)) == len(GRADE_SYSTEMS)


def test_discipline_enum_stores_lowercase_values_not_python_member_names(
    db_session: Session,
) -> None:
    """`values_callable` in models.py is what makes this true.

    Without it SQLAlchemy would persist `BOULDER`, and every JSON payload and every
    `WHERE discipline = 'boulder'` written later would silently match nothing.
    """
    disciplines = set(db_session.scalars(select(GradeSystem.discipline)).all())
    assert {d.value for d in disciplines} == {"boulder", "sport"}


def test_database_rejects_two_labels_on_the_same_rung(db_session: Session) -> None:
    """Proves the MIGRATION created `uq_grade_grade_system_id_ordinal`, not just the model.

    The ladder invariant has to hold in the database too — a seed bug or a manual fix-up
    must not be able to put two labels of one scale on one rung.
    """
    existing = db_session.scalars(select(Grade).limit(1)).one()
    db_session.add(
        Grade(
            grade_system_id=existing.grade_system_id,
            label="__dupe__",  # must fit label's String(16)
            ordinal=existing.ordinal,
        )
    )
    try:
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        # A failed flush poisons the SAVEPOINT; unwind it so teardown stays clean.
        db_session.rollback()
