"""`PUT /api/plans/{plan_id}/name` — the one field of a plan a climber may write.

⚠️ Two claims here are structural rather than about the feature, and both were SHOWN to fail
before they were trusted: a plan that is not the caller's is the SAME 404 as one that does not
exist, and a lifecycle field cannot ride in on the rename. CLAUDE.md records that there is
deliberately no abandon endpoint, and a `status` or `abandoned_at` accepted here would be that
prohibition undone by a route nobody was reviewing for it.
"""

import itertools
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from server.auth.tokens import decode_access_token, issue_access_token
from server.domain.grades import Discipline
from server.models import PLAN_NAME_MAX, Plan
from server.plans.routes import _CACHE_CONTROL, _NO_SUCH_PLAN
from server.seed import DEMO_USER_ID

_EMAIL = "plan-rename@example.com"
_OTHER_EMAIL = "plan-rename-other@example.com"
_PASSWORD = "a-long-enough-passphrase"

# One source IP per registration, from a different range than the other suites use.
_source_ips = itertools.count(10)

_ORIGINAL = "16-week sport plan"


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _EMAIL)


@pytest.fixture
def other_auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _OTHER_EMAIL)


@pytest.fixture
def demo_auth() -> dict[str, str]:
    """A demo-scope bearer for the seeded demo account."""
    return {"Authorization": f"Bearer {issue_access_token(DEMO_USER_ID, 'demo').token}"}


def _register(client: TestClient, invite: str, email: str) -> dict[str, str]:
    """A registered account's bearer header, from its OWN source IP."""
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PASSWORD, "invite_code": invite},
        headers={"x-forwarded-for": f"198.51.100.{next(_source_ips)}"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _user_id(headers: dict[str, str]) -> int:
    """The id inside the bearer, never one the test invented."""
    return decode_access_token(headers["Authorization"].removeprefix("Bearer ")).user_id


def _plan(session: Session, user_id: int, *, lifecycle: str = "active") -> Plan:
    """One plan row in one of its three lifecycle states. No tree: a rename never walks it."""
    activated = datetime.now(UTC) - timedelta(days=42)
    plan = Plan(
        user_id=user_id,
        name=_ORIGINAL,
        discipline=Discipline.SPORT,
        start_date=(activated - timedelta(days=1)).date(),
        week_count=16,
        generator_version="test",
        generator_input={},
        activated_at=activated,
        abandoned_at=activated + timedelta(days=1) if lifecycle == "abandoned" else None,
        completed_at=activated + timedelta(days=2) if lifecycle == "completed" else None,
    )
    session.add(plan)
    session.flush()
    return plan


def _rename(client: TestClient, headers: dict[str, str], plan_id: int, **body: Any) -> Any:
    return client.put(f"/api/plans/{plan_id}/name", json=body, headers=headers)


def _stored_name(session: Session, plan_id: int) -> str | None:
    """Read the column back, not the ORM object the test built."""
    return session.scalar(select(Plan.name).where(Plan.id == plan_id))


@pytest.mark.parametrize("lifecycle", ["active", "completed", "abandoned"])
def test_a_climber_may_rename_any_plan_of_their_own(
    api_client: TestClient, auth: dict[str, str], db_session: Session, lifecycle: str
) -> None:
    """⚠️ **Including a finished one** (Kilian): the diary draws one chart per plan, and the
    name is how last spring's block is told from this one."""
    plan = _plan(db_session, _user_id(auth), lifecycle=lifecycle)

    response = _rename(api_client, auth, plan.id, name="Winter power")

    assert response.status_code == 200, response.text
    assert response.json() == {"id": plan.id, "name": "Winter power"}
    assert _stored_name(db_session, plan.id) == "Winter power"


def test_the_lifecycle_is_untouched_by_a_rename(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """A rename is not a state change: the active plan is still the active plan afterwards."""
    plan = _plan(db_session, _user_id(auth))
    plan_id = plan.id

    assert _rename(api_client, auth, plan_id, name="Renamed").status_code == 200

    row = db_session.execute(
        select(Plan.activated_at, Plan.abandoned_at, Plan.completed_at).where(Plan.id == plan_id)
    ).one()
    assert row.activated_at is not None
    assert (row.abandoned_at, row.completed_at) == (None, None)


def test_the_name_is_stripped_before_it_is_stored(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The response is the STORED value, which is why it is echoed at all."""
    plan = _plan(db_session, _user_id(auth))

    response = _rename(api_client, auth, plan.id, name="  Winter power  ")

    assert response.json()["name"] == "Winter power"
    assert _stored_name(db_session, plan.id) == "Winter power"


def test_the_response_is_private_and_uncacheable(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """One climber's own label for their plan. `private` forbids the CDN, `no-store` the disk."""
    plan = _plan(db_session, _user_id(auth))

    response = _rename(api_client, auth, plan.id, name="Winter power")

    assert response.headers["cache-control"] == _CACHE_CONTROL


def test_renaming_another_climbers_plan_is_the_same_404_as_a_plan_that_does_not_exist(
    api_client: TestClient,
    auth: dict[str, str],
    other_auth: dict[str, str],
    db_session: Session,
) -> None:
    """⚠️ THE guard. Scoped by the token's `user_id`, so not-yours and not-there are one answer:
    a caller must not be able to learn that a stranger's plan exists, and must not touch it."""
    theirs = _plan(db_session, _user_id(other_auth))
    theirs_id = theirs.id

    foreign = _rename(api_client, auth, theirs_id, name="Mine now")
    missing = _rename(api_client, auth, theirs_id + 10_000, name="Mine now")

    assert (foreign.status_code, missing.status_code) == (404, 404)
    assert foreign.json() == missing.json() == {"detail": _NO_SUCH_PLAN}
    assert _stored_name(db_session, theirs_id) == _ORIGINAL


def test_a_demo_principal_cannot_rename_anything(
    api_client: TestClient, demo_auth: dict[str, str], db_session: Session
) -> None:
    """`PUT` is in `MUTATING_METHODS` and this route is not exempt, so `enforce_auth` refuses it
    before the handler. The demo account's OWN plan is what proves the 403 is not a 404."""
    plan = _plan(db_session, DEMO_USER_ID)

    response = _rename(api_client, demo_auth, plan.id, name="Demo rename")

    assert response.status_code == 403, response.text
    assert _stored_name(db_session, plan.id) == _ORIGINAL


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="empty-is-not-a-name"),
        pytest.param("   ", id="whitespace-is-not-a-name-either"),
        pytest.param("a" * (PLAN_NAME_MAX + 1), id="one-past-the-column"),
    ],
)
def test_a_name_outside_the_column_is_a_422(
    api_client: TestClient, auth: dict[str, str], db_session: Session, name: str
) -> None:
    """The bound is a 422 at the edge, not a `DataError` in the middle of a handler."""
    plan = _plan(db_session, _user_id(auth))

    response = _rename(api_client, auth, plan.id, name=name)

    assert response.status_code == 422, response.text
    assert _stored_name(db_session, plan.id) == _ORIGINAL


def test_exactly_the_column_length_is_accepted(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The positive control on the bound, read off the model rather than written down here."""
    plan = _plan(db_session, _user_id(auth))
    name = "a" * PLAN_NAME_MAX

    assert _rename(api_client, auth, plan.id, name=name).status_code == 200
    assert _stored_name(db_session, plan.id) == name


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"abandoned_at": "2026-01-01T00:00:00Z"}, id="abandoned_at"),
        pytest.param({"completed_at": "2026-01-01T00:00:00Z"}, id="completed_at"),
        pytest.param({"status": "abandoned"}, id="status"),
        pytest.param({"week_count": 4}, id="week_count"),
    ],
)
def test_no_second_field_can_ride_in_on_a_rename(
    api_client: TestClient, auth: dict[str, str], db_session: Session, extra: dict[str, Any]
) -> None:
    """⚠️ CLAUDE.md: there is deliberately NO abandon endpoint. `extra="forbid"` is what keeps
    this route from quietly becoming one, so the whole request is refused — the name included."""
    plan = _plan(db_session, _user_id(auth))
    plan_id = plan.id

    response = _rename(api_client, auth, plan_id, name="Renamed", **extra)

    assert response.status_code == 422, response.text
    row = db_session.execute(
        select(Plan.name, Plan.abandoned_at, Plan.completed_at).where(Plan.id == plan_id)
    ).one()
    assert row.name == _ORIGINAL
    assert (row.abandoned_at, row.completed_at) == (None, None)


@contextmanager
def _statements(session: Session) -> Iterator[list[str]]:
    """Every statement the connection executes, minus the harness's savepoint bookkeeping."""
    captured: list[str] = []
    skip = {"SAVEPOINT", "RELEASE", "ROLLBACK", "COMMIT", "BEGIN"}

    def _record(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        head = statement.strip().split(None, 1)[0].upper() if statement.strip() else ""
        if head not in skip:
            captured.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", _record)
    try:
        yield captured
    finally:
        event.remove(bind, "before_cursor_execute", _record)


def test_the_rename_issues_one_statement(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Neon bills awake time — and ownership is the UPDATE's own `WHERE`, never a second
    lookup that could drift from it. One statement is that design, measured."""
    plan_id = _plan(db_session, _user_id(auth)).id

    with _statements(db_session) as captured:
        assert _rename(api_client, auth, plan_id, name="Winter power").status_code == 200

    assert len(captured) == 1, captured
    assert captured[0].strip().upper().startswith("UPDATE")
