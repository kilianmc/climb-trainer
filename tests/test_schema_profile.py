"""`user_profile.show_body_metrics` — a real state, so it gets a real test.

DB-backed, so it **skips without `DATABASE_URL`** and runs in CI. It has to be: the
default is a `server_default`, which the ORM does not apply — nothing in Python knows
the value. A test that asserted `UserProfile().show_body_metrics is True` would pass
against a database where the column defaulted to false.

Per the testing policy this is not "a column type the ORM already declares". Turning the
switch off **hides the weight trend and every %BW figure and stops any weigh-in prompt**,
so it is behaviour, and the persisted value is the input to that behaviour. The UI half
lands with the screens that read it; this is the half the schema owns.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.domain.grades import Discipline
from server.models import AppUser, UserProfile


@pytest.fixture
def profile(db_session: Session) -> UserProfile:
    """A profile created WITHOUT mentioning `show_body_metrics` at all.

    That omission is the test: the value has to come from the database's default, not
    from anything this file passes in.
    """
    account = AppUser(email=f"profile-{uuid.uuid4().hex}@example.test", password_hash=None)
    db_session.add(account)
    db_session.flush()
    row = UserProfile(
        user_id=account.id,
        primary_discipline=Discipline.BOULDER,
        sessions_per_week=3,
        # Mon/Wed/Fri: bits 0, 2 and 4.
        available_weekdays=0b0010101,
    )
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    return row


def test_body_metrics_are_shown_by_default(profile: UserProfile) -> None:
    """On unless asked otherwise: %BW is the most useful strength number in climbing.

    A default of off would make the whole feature undiscoverable, which is a different
    failure from the one the switch exists to prevent.
    """
    assert profile.show_body_metrics is True


def test_body_metrics_can_be_turned_off_and_stays_off(
    db_session: Session, profile: UserProfile
) -> None:
    """The off state persists — read back from the database, not from the identity map.

    `expire` before the read is what makes this a round trip rather than an assertion
    about the object still in memory.
    """
    profile.show_body_metrics = False
    db_session.flush()
    db_session.expire(profile)

    stored = db_session.scalars(
        select(UserProfile).where(UserProfile.user_id == profile.user_id)
    ).one()
    assert stored.show_body_metrics is False
