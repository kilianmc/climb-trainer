"""The three things about the logging schema that only a real database can prove.

These **skip without `DATABASE_URL`** (see conftest) and run in CI against the postgres
service container after `alembic upgrade head`, which is the point: each one is a
behaviour of the *migration*, not of the ORM declarations.

Per the testing policy in CLAUDE.md, each covers a named bullet:

- **`srpe_load` is a `GENERATED ... STORED` column** — a "complex transform" that lives
  in DDL. Nothing in Python computes it, so nothing in Python can be unit-tested instead,
  and a typo in the expression would surface as a silently wrong training load.
- **Idempotent replay by `client_uuid`** — the explicit "anything that can lose user
  data" bullet. The outbox replays a flush after a failed request; if the unique
  constraints are not exactly where the `ON CONFLICT` clauses expect them, a retry either
  duplicates a session or raises.
- **The supertype/subtype constraint** — the guarantee that cardio cannot grow a parallel
  logging system is a composite foreign key, so it has to be tested against Postgres or
  not at all.

Deliberately NOT tested here: that columns have the types they declare, that a
relationship loads, or that `select()` returns rows. That is testing SQLAlchemy.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.domain.grades import Discipline
from server.domain.vocabulary import ActivityKind, AscentStyle, ProtocolKind
from server.models import (
    Activity,
    AppUser,
    Ascent,
    AscentTag,
    AscentTagLink,
    ClimbingAspect,
    Exercise,
    Grade,
    LoggedSession,
    LoggedSet,
)


@pytest.fixture
def user(db_session: Session) -> AppUser:
    """A throwaway account. Rolled back with the test, like everything else here."""
    account = AppUser(email=f"logging-{uuid.uuid4().hex}@example.test", password_hash=None)
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def exercise(db_session: Session) -> Exercise:
    """One library row, built on a SEEDED aspect.

    The exercise library itself is content and is not seeded (see `server/seed.py`), so a
    test that needs an `exercise_id` has to make one. The aspect it hangs off, though,
    comes from the real seed — hand-writing that would test a table production never has.
    """
    aspect = db_session.scalars(select(ClimbingAspect).order_by(ClimbingAspect.sort_order)).first()
    assert aspect is not None, "climbing_aspect is seeded by server/seed.py; conftest seeds it"
    row = Exercise(
        key=f"test-{uuid.uuid4().hex}",
        name="Test hang",
        climbing_aspect_id=aspect.id,
        protocol_kind=ProtocolKind.MAX_HANG,
        instructions="Hang.",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _activity(
    user_id: int,
    *,
    kind: ActivityKind = ActivityKind.CLIMBING,
    duration_minutes: int = 90,
    rpe: int | None = 7,
    client_uuid: uuid.UUID | None = None,
) -> Activity:
    """Fields assigned explicitly, never splatted from a dict — see CLAUDE.md."""
    return Activity(
        user_id=user_id,
        activity_kind=kind,
        occurred_on=date(2026, 8, 21),
        duration_minutes=duration_minutes,
        rpe=rpe,
        client_uuid=client_uuid if client_uuid is not None else uuid.uuid4(),
    )


def test_srpe_load_is_computed_by_the_database(db_session: Session, user: AppUser) -> None:
    """RPE x minutes, and it follows an UPDATE without anything re-deriving it."""
    activity = _activity(user.id, duration_minutes=90, rpe=7)
    db_session.add(activity)
    db_session.flush()
    db_session.refresh(activity)
    assert activity.srpe_load == 630

    activity.duration_minutes = 60
    db_session.flush()
    db_session.refresh(activity)
    assert activity.srpe_load == 420


def test_srpe_load_is_null_when_rpe_is_missing(db_session: Session, user: AppUser) -> None:
    """An activity logged without an RPE has NO load score — not a load score of zero.

    Worth its own test because the tempting `COALESCE(rpe, 0) * duration` would make
    every unrated activity look like a rest day to ACWR, which is exactly backwards for
    a two-hour session somebody could not be bothered to rate.
    """
    activity = _activity(user.id, rpe=None)
    db_session.add(activity)
    db_session.flush()
    db_session.refresh(activity)
    assert activity.srpe_load is None


def test_activity_replay_updates_instead_of_duplicating(db_session: Session, user: AppUser) -> None:
    """`ON CONFLICT (user_id, client_uuid) DO UPDATE` — the outbox's contract.

    Replaying the same flush must leave one row with the newer values. This is the test
    that fails if `uq_activity_user_id_client_uuid` is ever dropped or narrowed to
    `client_uuid` alone.
    """
    client_uuid = uuid.uuid4()

    def replay(duration: int) -> None:
        statement = insert(Activity).values(
            user_id=user.id,
            activity_kind=ActivityKind.CLIMBING.value,
            occurred_on=date(2026, 8, 21),
            duration_minutes=duration,
            rpe=8,
            client_uuid=client_uuid,
        )
        db_session.execute(
            statement.on_conflict_do_update(
                index_elements=[Activity.user_id, Activity.client_uuid],
                set_={"duration_minutes": statement.excluded.duration_minutes},
            )
        )

    replay(45)
    replay(75)
    db_session.flush()

    rows = db_session.scalars(select(Activity).where(Activity.user_id == user.id)).all()
    assert len(rows) == 1
    assert rows[0].duration_minutes == 75
    # The generated column must have followed the upsert, not just the original INSERT.
    assert rows[0].srpe_load == 600


def test_logged_set_replay_updates_instead_of_duplicating(
    db_session: Session, user: AppUser, exercise: Exercise
) -> None:
    """The Tier-2 flush is the one write path that repeats per set, so it replays most.

    `UNIQUE (logged_session_id, client_uuid)` scoped to the session rather than the user:
    that is what the `ON CONFLICT` in the flush names, and a mismatch here is a 500 on a
    retried flush at the end of somebody's session.
    """
    activity = _activity(user.id)
    db_session.add(activity)
    db_session.flush()
    db_session.add(LoggedSession(activity_id=activity.id, discipline=Discipline.BOULDER))
    db_session.flush()

    client_uuid = uuid.uuid4()

    def replay(rpe: int) -> None:
        statement = insert(LoggedSet).values(
            logged_session_id=activity.id,
            client_uuid=client_uuid,
            exercise_id=exercise.id,
            set_index=1,
            actual_reps=5,
            rpe=rpe,
        )
        db_session.execute(
            statement.on_conflict_do_update(
                index_elements=[LoggedSet.logged_session_id, LoggedSet.client_uuid],
                set_={"rpe": statement.excluded.rpe},
            )
        )

    replay(6)
    replay(9)
    db_session.flush()

    rows = db_session.scalars(
        select(LoggedSet).where(LoggedSet.logged_session_id == activity.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].rpe == 9


def test_the_same_client_uuid_from_two_users_is_two_rows(db_session: Session) -> None:
    """The idempotency key is scoped PER USER, and that scope is load-bearing.

    A globally unique `client_uuid` would let one client's collision — or one malicious
    client picking a uuid on purpose — block or overwrite another account's write. Two
    accounts replaying the same uuid must produce two independent rows.
    """
    first = AppUser(email=f"one-{uuid.uuid4().hex}@example.test", password_hash=None)
    second = AppUser(email=f"two-{uuid.uuid4().hex}@example.test", password_hash=None)
    db_session.add_all([first, second])
    db_session.flush()

    shared = uuid.uuid4()
    db_session.add_all(
        [_activity(first.id, client_uuid=shared), _activity(second.id, client_uuid=shared)]
    )
    db_session.flush()

    assert (
        len(db_session.scalars(select(Activity).where(Activity.client_uuid == shared)).all()) == 2
    )


def test_a_logged_session_cannot_attach_to_a_non_climbing_activity(
    db_session: Session, user: AppUser
) -> None:
    """The whole reason `activity` is a supertype, enforced by Postgres rather than hoped for.

    `logged_session` carries a duplicate `activity_kind` with a CHECK and a composite
    foreign key to `activity (id, activity_kind)`. A cardio activity therefore has no
    `(id, 'climbing')` row to reference, so the insert cannot succeed — which is what
    stops "log a run" quietly becoming a second, half-featured session system.
    """
    ride = _activity(user.id, kind=ActivityKind.CARDIO)
    db_session.add(ride)
    db_session.flush()

    db_session.add(LoggedSession(activity_id=ride.id, discipline=Discipline.BOULDER))
    try:
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        # A failed flush poisons the SAVEPOINT; unwind it so teardown stays clean.
        db_session.rollback()


def test_duration_is_bounded_at_twenty_four_hours(db_session: Session, user: AppUser) -> None:
    """1..1440, and both ends of the boundary.

    The bound is not tidiness. `rpe` and `duration_minutes` are both SMALLINT, so the
    uncast `rpe * duration_minutes` resolves as `int2 * int2` and raises `smallint out of
    range` before it can widen into the INTEGER column — a client that sent the duration in
    seconds (a 90-minute session as 5400) would abort the INSERT, and on the outbox path
    that payload retries forever and can never succeed. `srpe_load` now casts, and this
    CHECK is what rejects the value outright instead. An activity is ONE session, so
    anything past 24 h is a unit error rather than a long day.
    """
    limit = _activity(user.id, duration_minutes=1440, rpe=10)
    db_session.add(limit)
    db_session.flush()
    db_session.refresh(limit)
    # Comfortably inside int4, which is the point of the cast.
    assert limit.srpe_load == 14400

    db_session.add(_activity(user.id, duration_minutes=1441))
    try:
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        db_session.rollback()


def test_an_ascent_cannot_carry_an_ordinal_from_a_different_grade(
    db_session: Session, user: AppUser
) -> None:
    """The composite foreign key on (grade_id, grade_ordinal) -> grade (id, ordinal).

    Without it the denormalised ordinal is merely *intended* to match, and because the
    ladders are banded per discipline the band IS the discipline — so a transposed argument
    files a French 7a rope send in the boulder pyramid, with nothing left to recover the
    truth from. Proves the MIGRATION created `uq_grade_id_ordinal` and the FK, not just the
    model.
    """
    grade = db_session.scalars(select(Grade).order_by(Grade.ordinal)).first()
    assert grade is not None, "the grade ladder is seeded by server/seed.py"

    db_session.add(
        Ascent(
            user_id=user.id,
            climbed_on=date(2026, 8, 21),
            grade_id=grade.id,
            # Off by one: a real rung, but not THIS grade's rung.
            grade_ordinal=grade.ordinal + 1,
            style=AscentStyle.FLASH,
            client_uuid=uuid.uuid4(),
        )
    )
    try:
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        db_session.rollback()


def test_an_ascent_is_tagged_from_the_seeded_vocabulary(db_session: Session, user: AppUser) -> None:
    """Tags are a FIXED vocabulary — a lookup plus a join, not `text[]`.

    Reversed 2026-08-21 (Kilian): a free-typed array fragments into 'crimp' / 'crimps' /
    'Crimpy' and defeats the "what do I send on?" aggregate it exists for. This is the
    replacement working end to end against the real seed, which is also what proves the
    tag rows are actually seeded rather than merely defined.
    """
    grade = db_session.scalars(select(Grade).order_by(Grade.ordinal)).first()
    assert grade is not None
    ascent = Ascent(
        user_id=user.id,
        climbed_on=date(2026, 8, 21),
        grade_id=grade.id,
        grade_ordinal=grade.ordinal,
        style=AscentStyle.FLASH,
        client_uuid=uuid.uuid4(),
    )
    db_session.add(ascent)
    db_session.flush()

    tags = db_session.scalars(
        select(AscentTag).where(AscentTag.key.in_(["crimps", "overhang"]))
    ).all()
    assert len(tags) == 2, "ascent_tag is seeded by server/seed.py"
    db_session.add_all(AscentTagLink(ascent_id=ascent.id, ascent_tag_id=tag.id) for tag in tags)
    db_session.flush()

    linked = db_session.scalars(
        select(AscentTag.key)
        .join(AscentTagLink, AscentTagLink.ascent_tag_id == AscentTag.id)
        .where(AscentTagLink.ascent_id == ascent.id)
    ).all()
    assert set(linked) == {"crimps", "overhang"}


def test_the_same_tag_cannot_be_attached_twice(db_session: Session, user: AppUser) -> None:
    """The composite primary key IS the row, so a duplicate is impossible.

    Worth one test because the client will happily re-send a tag list on an edit, and the
    write path relies on this rather than on de-duplicating first.
    """
    grade = db_session.scalars(select(Grade).order_by(Grade.ordinal)).first()
    assert grade is not None
    ascent = Ascent(
        user_id=user.id,
        climbed_on=date(2026, 8, 21),
        grade_id=grade.id,
        grade_ordinal=grade.ordinal,
        style=AscentStyle.FLASH,
        client_uuid=uuid.uuid4(),
    )
    db_session.add(ascent)
    db_session.flush()
    tag = db_session.scalars(select(AscentTag).where(AscentTag.key == "crimps")).one()

    db_session.add(AscentTagLink(ascent_id=ascent.id, ascent_tag_id=tag.id))
    db_session.flush()
    db_session.add(AscentTagLink(ascent_id=ascent.id, ascent_tag_id=tag.id))
    try:
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        db_session.rollback()
