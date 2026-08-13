"""Reference-data seed — the grade ladder.

**This is the single seed module: CI, local development and production all call it.**
That is deliberate. A test fixture that seeds its own hand-written rows tests a table
production never has, and the divergence is invisible until a query works in CI and
returns nothing in production.

Idempotent by upsert on the natural keys, so re-running it after a migration or a
ladder edit is safe and cheap.

**It never deletes.** A grade removed from `server/domain/grades.py` stays in the table
rather than being pruned, because user rows will reference `grade.id` (target grade,
ascent grade) and a delete would either violate a foreign key or, worse, cascade into
someone's training history. Retiring a rung is therefore a deliberate migration, not a
side effect of editing a tuple.

All statements are SQLAlchemy constructs with bound parameters — no string-built SQL
anywhere, per the injection rules in CLAUDE.md.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from server.db import session_scope
from server.domain import grades
from server.models import Grade, GradeSystem


@dataclass(frozen=True, slots=True)
class SeedResult:
    grade_systems: int
    grades: int


def seed_reference_data(session: Session) -> SeedResult:
    """Upsert every grade system and grade. Does NOT commit — the caller owns that."""
    system_stmt = insert(GradeSystem).values(
        [
            {"key": spec.key.value, "name": spec.name, "discipline": spec.discipline}
            for spec in grades.GRADE_SYSTEMS
        ]
    )
    session.execute(
        system_stmt.on_conflict_do_update(
            index_elements=[GradeSystem.key],
            set_={
                "name": system_stmt.excluded.name,
                "discipline": system_stmt.excluded.discipline,
            },
        )
    )
    # Flush the upsert before reading ids back: the grade rows need `grade_system_id`,
    # and on a first run those ids do not exist yet.
    session.flush()

    id_by_key = {
        key: system_id
        for system_id, key in session.execute(select(GradeSystem.id, GradeSystem.key))
    }

    grade_stmt = insert(Grade).values(
        [
            {
                "grade_system_id": id_by_key[spec.system.value],
                "label": spec.label,
                "ordinal": spec.ordinal,
            }
            for spec in grades.GRADES
        ]
    )
    session.execute(
        grade_stmt.on_conflict_do_update(
            # The natural key. Re-pointing a label at a different rung is the one edit
            # that must propagate, since everything comparable is derived from ordinal.
            index_elements=[Grade.grade_system_id, Grade.label],
            set_={"ordinal": grade_stmt.excluded.ordinal},
        )
    )
    session.flush()

    return SeedResult(grade_systems=len(grades.GRADE_SYSTEMS), grades=len(grades.GRADES))


def main() -> None:
    """`uv run python -m server.seed` — run after `alembic upgrade head`.

    Out-of-band against production, for the same reason migrations are: it must never
    race a deploy.
    """
    with session_scope() as session:
        result = seed_reference_data(session)
    print(f"seeded {result.grade_systems} grade systems, {result.grades} grades")


if __name__ == "__main__":
    main()
