"""`server/contentseed.py` against real Postgres — idempotence and reconciliation.

Skips without `DATABASE_URL` (see conftest) and runs in CI against the postgres service
container after `alembic upgrade head`, which is the point: this is what proves the
migration, the models and the authored content agree. `tests/test_exercise_library.py`
covers the pure content rules and runs in the local gate.

Under CLAUDE.md's testing policy: **anything that can lose user data**, plus the "core
path" of a production seed run. Two properties earn a test here and nothing else does —

- **idempotence**, because this module runs on every migration dispatch with `seed: true`,
  and a second run that duplicated or moved rows would corrupt a library the plan
  generator reads;
- **reconciliation**, because it is the one place the module deletes. A content edit that
  *removes* a requirement or a phase has to take the old row with it. An insert-only seed
  would silently keep withholding an exercise from everyone with a contraindication that
  was removed;
- **the delete-or-retire fork**, because it is the only place the seed removes a row that
  user data could point at. Removing a key from the content must really delete the
  exercise (Kilian's call) — and must fall back to `retired_at` when a plan or a logged set
  references it, because `NO ACTION` means Postgres would otherwise abort the whole
  transaction and the seed would report success having written nothing.

Deliberately NOT tested: that every name and instruction round-trips. That is content, a
copy edit would break it, and `test_the_library_lands_whole` already proves the row counts.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from server.contentseed import ContentSeedError, _ids_by_key, seed_exercise_library
from server.domain.exercises import EXERCISES
from server.domain.grades import Discipline
from server.domain.vocabulary import ActivityKind, Phase, ProtocolKind
from server.models import (
    Activity,
    AppUser,
    ClimbingAspect,
    Equipment,
    Exercise,
    ExerciseContraindication,
    ExerciseEquipment,
    LoggedSession,
    LoggedSet,
    PrescriptionTemplate,
)

_EXPECTED_EQUIPMENT_ROWS = sum(len(spec.equipment_keys) for spec in EXERCISES)
_EXPECTED_CONTRAINDICATIONS = sum(len(spec.contraindication_keys) for spec in EXERCISES)
_EXPECTED_PRESCRIPTIONS = sum(len(spec.prescriptions) for spec in EXERCISES)


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_the_library_lands_whole(db_session: Session) -> None:
    """Every authored exercise, requirement, contraindication and template is in the table.

    The library is seeded once per session by the `seeded` fixture, from the same module
    production runs — so this asserts against what a production seed would have written.
    """
    keys = set(db_session.scalars(select(Exercise.key)).all())
    assert {spec.key for spec in EXERCISES} <= keys
    assert _count(db_session, ExerciseEquipment) == _EXPECTED_EQUIPMENT_ROWS
    assert _count(db_session, ExerciseContraindication) == _EXPECTED_CONTRAINDICATIONS
    assert _count(db_session, PrescriptionTemplate) == _EXPECTED_PRESCRIPTIONS


def test_the_zero_equipment_floor_survives_the_round_trip(db_session: Session) -> None:
    """The floor as the *database* sees it, which is what the generator will query.

    `tests/test_exercise_library.py` asserts it on the authored tuple; this asserts it on
    the rows, so a seed bug that invented a requirement — or a join reconcile that
    inserted the wrong pair — cannot leave a gearless climber with an empty aspect.
    """
    gearless = (
        select(Exercise.climbing_aspect_id)
        .outerjoin(ExerciseEquipment, ExerciseEquipment.exercise_id == Exercise.id)
        .where(ExerciseEquipment.exercise_id.is_(None))
    )
    covered = set(db_session.scalars(gearless).all())
    every_aspect = set(db_session.scalars(select(ClimbingAspect.id)).all())
    assert every_aspect - covered == set(), (
        "an aspect has no exercise with zero `exercise_equipment` rows in the DATABASE. "
        "There is no `bodyweight` equipment row on purpose, so that is a climber with no "
        "gear getting an empty slot in their plan."
    )


def test_seeding_twice_changes_nothing(db_session: Session) -> None:
    """A second run must be a no-op, not merely harmless.

    `removed_rows == 0` is the sharper half: it proves the reconciliation deletes nothing
    it just inserted, which an over-broad `NOT IN` would.
    """
    before = (
        _count(db_session, Exercise),
        _count(db_session, ExerciseEquipment),
        _count(db_session, ExerciseContraindication),
        _count(db_session, PrescriptionTemplate),
    )
    result = seed_exercise_library(db_session)
    again = seed_exercise_library(db_session)

    assert result.removed_rows == 0
    assert again.removed_rows == 0
    assert (
        _count(db_session, Exercise),
        _count(db_session, ExerciseEquipment),
        _count(db_session, ExerciseContraindication),
        _count(db_session, PrescriptionTemplate),
    ) == before


def test_a_requirement_the_content_no_longer_authors_is_removed(db_session: Session) -> None:
    """The reconcile half: a stale join row must not outlive the content edit.

    Simulated the only way it can be, from the outside: plant the row an earlier version of
    the content would have written, re-run, and watch it go. Without this the exercise
    stays unprescribable for anyone lacking equipment it no longer needs.
    """
    exercise_id = db_session.scalars(
        select(Exercise.id).where(Exercise.key == "hollow_body_hold")
    ).one()
    equipment_id = db_session.scalars(select(Equipment.id).order_by(Equipment.sort_order)).first()
    db_session.add(ExerciseEquipment(exercise_id=exercise_id, equipment_id=equipment_id))
    db_session.flush()

    result = seed_exercise_library(db_session)

    assert result.removed_rows >= 1
    assert (
        db_session.scalars(
            select(ExerciseEquipment.equipment_id).where(
                ExerciseEquipment.exercise_id == exercise_id
            )
        ).all()
        == []
    )


def test_a_phase_the_content_no_longer_prescribes_is_removed(db_session: Session) -> None:
    """Same argument for `prescription_template`: the phase set is content too.

    A max hang has no place in a taper week, so narrowing an exercise's phases has to take
    the old template with it — otherwise the generator keeps reading a prescription nobody
    authored.
    """
    spec = next(spec for spec in EXERCISES if len(spec.prescriptions) < len(Phase))
    unauthored = next(
        phase
        for phase in Phase
        if phase not in {prescription.phase for prescription in spec.prescriptions}
    )
    exercise_id = db_session.scalars(select(Exercise.id).where(Exercise.key == spec.key)).one()
    db_session.add(
        PrescriptionTemplate(exercise_id=exercise_id, phase=unauthored, sets=1, target_rpe=5)
    )
    db_session.flush()

    result = seed_exercise_library(db_session)

    assert result.removed_rows >= 1
    phases = set(
        db_session.scalars(
            select(PrescriptionTemplate.phase).where(
                PrescriptionTemplate.exercise_id == exercise_id
            )
        ).all()
    )
    assert phases == {prescription.phase for prescription in spec.prescriptions}


def test_a_missing_vocabulary_key_fails_loudly(db_session: Session) -> None:
    """The seed must never skip a row it cannot resolve.

    This is the "database not vocabulary-seeded yet" path — the realistic one, since
    `server.seed` and `server.contentseed` are two separate dispatch steps and running the
    second without the first is one forgotten line in a workflow. Silently skipping would
    ship a library missing requirements nobody notices until a plan prescribes something
    the user cannot do.
    """
    with pytest.raises(ContentSeedError, match="no row for"):
        _ids_by_key(db_session, Equipment, {"a_row_that_was_never_seeded"}, "equipment")


def _unauthored_exercise(session: Session) -> Exercise:
    """An `exercise` row with a key the content does not author, plus its child rows.

    This is the only honest way to simulate "Kilian deleted an exercise": the authored
    tuple is final and a test must not edit it, so the test plants the row a *previous*
    version of the content would have left behind and re-runs the seed over it. The child
    rows are there so the reported cascade count means something.
    """
    aspect = session.scalars(select(ClimbingAspect).order_by(ClimbingAspect.sort_order)).first()
    assert aspect is not None, "climbing_aspect is seeded by server/seed.py; conftest seeds it"
    row = Exercise(
        key=f"dropped-{uuid.uuid4().hex}",
        name="An exercise Kilian removed",
        climbing_aspect_id=aspect.id,
        protocol_kind=ProtocolKind.MAX_HANG,
        instructions="Removed from the library.",
    )
    session.add(row)
    session.flush()
    equipment_id = session.scalars(select(Equipment.id).order_by(Equipment.sort_order)).first()
    assert equipment_id is not None
    session.add(ExerciseEquipment(exercise_id=row.id, equipment_id=equipment_id))
    session.add(PrescriptionTemplate(exercise_id=row.id, phase=Phase.BASE, sets=3, target_rpe=7))
    session.flush()
    return row


def test_an_exercise_the_content_dropped_is_really_DELETED(db_session: Session) -> None:
    """The headline behaviour: removing a key removes the row, not just its visibility.

    Kilian's requirement, and it is the reason `retired_at` is a fallback rather than the
    mechanism: a library that only ever grows cannot be curated, and "hidden" rows
    accumulate forever while still being reachable by anything that queries the table
    directly.
    """
    orphan = _unauthored_exercise(db_session)

    result = seed_exercise_library(db_session)

    assert result.deleted_exercises == 1
    assert result.retired_exercises == 0
    # Its children went with it, and they were counted rather than left to the DDL's
    # cascade to do silently.
    assert result.removed_rows >= 2
    assert db_session.scalars(select(Exercise.id).where(Exercise.id == orphan.id)).all() == []
    assert (
        db_session.scalars(
            select(ExerciseEquipment.exercise_id).where(ExerciseEquipment.exercise_id == orphan.id)
        ).all()
        == []
    )


def test_an_exercise_a_LOGGED_SET_points_at_is_retired_instead(db_session: Session) -> None:
    """The fallback, and the reason it is decided by a QUERY rather than by a caught error.

    `logged_set.exercise_id` is `NO ACTION`, so the delete would raise — and a raised
    statement aborts the whole Postgres transaction, which this module runs inside one of.
    Catching the `IntegrityError` would therefore poison every statement after it and the
    seed would report success having written nothing. So the `EXISTS` runs first and this
    row is retired instead: the diary entry keeps resolving to a name, and
    `GET /api/library` stops offering it.

    Only the `logged_set` side is exercised here. The `session_block` side is the *same*
    `EXISTS` in the same `or_`, and reaching it would mean hand-building a
    plan -> mesocycle -> microcycle -> planned_session -> session_block chain whose column
    list nothing local can verify (these tests are CI-only). Not worth the risk of a test
    that is red for its own reasons.
    """
    orphan = _unauthored_exercise(db_session)
    account = AppUser(email=f"retire-{uuid.uuid4().hex}@example.test", password_hash=None)
    db_session.add(account)
    db_session.flush()
    activity = Activity(
        user_id=account.id,
        activity_kind=ActivityKind.CLIMBING,
        occurred_on=date(2026, 8, 23),
        duration_minutes=90,
        rpe=7,
        client_uuid=uuid.uuid4(),
    )
    db_session.add(activity)
    db_session.flush()
    db_session.add(LoggedSession(activity_id=activity.id, discipline=Discipline.BOULDER))
    db_session.flush()
    db_session.add(
        LoggedSet(
            logged_session_id=activity.id,
            client_uuid=uuid.uuid4(),
            exercise_id=orphan.id,
            set_index=1,
            actual_reps=5,
            rpe=7,
        )
    )
    db_session.flush()

    result = seed_exercise_library(db_session)

    assert result.deleted_exercises == 0
    assert result.retired_exercises == 1
    retired_at = db_session.scalars(
        select(Exercise.retired_at).where(Exercise.id == orphan.id)
    ).one()
    assert retired_at is not None, "the row survived but was not marked"

    # A second run must not move the timestamp: it records when the library stopped
    # offering the exercise, and a seed that rewrote it every dispatch would lose that.
    again = seed_exercise_library(db_session)
    assert again.retired_exercises == 0
    assert (
        db_session.scalars(select(Exercise.retired_at).where(Exercise.id == orphan.id)).one()
        == retired_at
    )


def test_re_authoring_a_retired_key_brings_it_back(db_session: Session) -> None:
    """`retired_at` is cleared by the upsert, so a key that returns is served again.

    The realistic path: an exercise is dropped, somebody has already trained it so the row
    is retired rather than deleted, and then Kilian puts it back. If the upsert did not
    write `retired_at = NULL` the exercise would stay invisible for exactly the users who
    had used it, and nothing would say why.
    """
    key = EXERCISES[0].key
    exercise_id = db_session.scalars(select(Exercise.id).where(Exercise.key == key)).one()
    db_session.execute(
        update(Exercise).where(Exercise.id == exercise_id).values(retired_at=func.now())
    )
    db_session.flush()

    seed_exercise_library(db_session)

    assert (
        db_session.scalars(select(Exercise.retired_at).where(Exercise.id == exercise_id)).one()
        is None
    )
