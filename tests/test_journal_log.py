"""`PUT /api/journal/{client_uuid}` — the WRITE path, against real Postgres.

The half of PR B that can lose what a climber typed: it is the only way a diary entry becomes a
row, and the box that calls it is retried by hand and resubmitted by anybody who reopens the
summary. Every assertion here is about what survives a replay, a resubmission, or a lie in the
payload. `tests/test_journal_validation.py` owns the DB-free edge bounds.

⚠️ **Every guard here was SABOTAGED and watched go red** (CLAUDE.md); the edits and their
failures are in the PR. **Skips without `CT_TEST_DATABASE_URL`** (`conftest.py`).
"""

import itertools
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.auth.tokens import issue_access_token
from server.domain.grades import Discipline
from server.domain.vocabulary import ActivityKind
from server.journal.routes import _CACHE_CONTROL, _NO_SESSION
from server.models import Activity, JournalEntry
from server.seed import DEMO_USER_ID

_EMAIL = "journal@example.com"
_OTHER_EMAIL = "journal-other@example.com"
_PASSWORD = "a-long-enough-passphrase"
_TODAY = datetime.now(UTC).date()

# One source address per registration: `ratelimit.REGISTER` is 3/hour/IP. TEST-NET-3.
_source_ips = itertools.count(20)

# A string no other field could produce, so "is it echoed?" is a substring test with no
# false positive available to it.
_BODY_MARKER = "SECRET-BETA-CRIMP-MARKER"


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


def _entry(**overrides: Any) -> dict[str, Any]:
    """One valid entry, so every case below differs in exactly what it names."""
    payload: dict[str, Any] = {"entry_date": _TODAY.isoformat(), "feel": 3}
    return payload | overrides


def _put(client: TestClient, headers: dict[str, str], client_uuid: str, **overrides: Any) -> Any:
    return client.put(f"/api/journal/{client_uuid}", json=_entry(**overrides), headers=headers)


def _logged_session_id(client: TestClient, headers: dict[str, str]) -> int:
    """A real `logged_session` through the REAL endpoint, never a hand-built row."""
    response = client.put(
        f"/api/sessions/{uuid.uuid4()}",
        json={
            "occurred_on": _TODAY.isoformat(),
            "duration_minutes": 5,
            "discipline": Discipline.BOULDER.value,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def _rows(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(JournalEntry)) or 0)


def test_an_entry_is_written_and_the_ack_names_it(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The positive control, and the ack the client retires the draft on."""
    client_uuid = str(uuid.uuid4())
    response = _put(
        api_client,
        auth,
        client_uuid,
        body=_BODY_MARKER,
        feel=4,
        sleep_quality=5,
        skin=2,
        body_weight_kg="71.4",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_uuid"] == client_uuid
    assert body["entry_date"] == _TODAY.isoformat()
    assert body["logged_session_id"] is None

    stored = db_session.scalars(select(JournalEntry)).one()
    assert stored.id == body["id"]
    assert stored.body == _BODY_MARKER
    assert (stored.feel, stored.sleep_quality, stored.skin) == (4, 5, 2)
    assert stored.body_weight_kg == Decimal("71.4")


def test_the_response_ECHOES_NO_FREE_TEXT(api_client: TestClient, auth: dict[str, str]) -> None:
    """⚠️ Nothing that needs escaping downstream may be in this body. `SessionLogResponse`'s rule."""
    response = _put(api_client, auth, str(uuid.uuid4()), body=_BODY_MARKER)
    assert response.status_code == 200, response.text
    assert _BODY_MARKER not in response.text, f"the body is echoed here: {response.text}"


def test_the_response_is_PRIVATE_AND_NO_STORE(api_client: TestClient, auth: dict[str, str]) -> None:
    """One climber's diary. A shared-cache entry would hand a stranger their notes."""
    response = _put(api_client, auth, str(uuid.uuid4()))
    assert response.headers["cache-control"] == _CACHE_CONTROL


def test_a_REPLAYED_put_leaves_ONE_ROW_and_an_IDENTICAL_response(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ The whole reason the uuid is in the path. A retried write must not duplicate."""
    client_uuid = str(uuid.uuid4())
    first = _put(api_client, auth, client_uuid, body=_BODY_MARKER, feel=4)
    second = _put(api_client, auth, client_uuid, body=_BODY_MARKER, feel=4)
    assert (first.status_code, second.status_code) == (200, 200), second.text
    # Byte-identical, including the status: the client does not branch on either.
    assert first.json() == second.json()
    assert _rows(db_session) == 1


def test_a_RESUBMISSION_REPLACES_the_entry_rather_than_adding_one(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Reopening the summary and saving again edits the entry. ⚠️ REPLACE, so a field can be
    CLEARED — under merge semantics "I emptied the weight box" would be unexpressible."""
    client_uuid = str(uuid.uuid4())
    assert (
        _put(
            api_client, auth, client_uuid, body="first thoughts", feel=2, body_weight_kg="71.4"
        ).status_code
        == 200
    )
    assert _put(api_client, auth, client_uuid, body="on reflection", feel=5).status_code == 200

    stored = db_session.scalars(select(JournalEntry)).one()
    assert stored.body == "on reflection"
    assert stored.feel == 5
    assert stored.body_weight_kg is None, "an omitted field must be cleared, not merged"


def test_TWO_USERS_may_hold_the_SAME_client_uuid(
    api_client: TestClient, auth: dict[str, str], other_auth: dict[str, str], db_session: Session
) -> None:
    """The unique key is `(user_id, client_uuid)`, so one climber's uuid cannot collide with —
    or overwrite — another's. Two rows here, one each."""
    client_uuid = str(uuid.uuid4())
    assert _put(api_client, auth, client_uuid, body="mine").status_code == 200
    assert _put(api_client, other_auth, client_uuid, body="theirs").status_code == 200
    assert _rows(db_session) == 2


def test_ANOTHER_USERS_session_id_is_a_404_IDENTICAL_TO_THE_MISSING_CASE(
    api_client: TestClient, auth: dict[str, str], other_auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ Both arms assert the SAME detail string: a different message for "not yours" is the
    disclosure that answering identically exists to prevent."""
    theirs = _logged_session_id(api_client, other_auth)
    mine = _put(api_client, auth, str(uuid.uuid4()), logged_session_id=theirs)
    assert mine.status_code == 404, mine.text
    assert mine.json()["detail"] == _NO_SESSION

    absent = _put(api_client, auth, str(uuid.uuid4()), logged_session_id=theirs + 10_000)
    assert absent.status_code == 404, absent.text
    assert absent.json()["detail"] == _NO_SESSION
    assert _rows(db_session) == 0, "a refused write must leave nothing behind"


def test_MY_OWN_session_id_LINKS_the_entry(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The other half of the ownership arm: without it, the 404 test passes on a broken route."""
    mine = _logged_session_id(api_client, auth)
    response = _put(api_client, auth, str(uuid.uuid4()), logged_session_id=mine)
    assert response.status_code == 200, response.text
    assert response.json()["logged_session_id"] == mine
    assert db_session.scalars(select(JournalEntry)).one().logged_session_id == mine


def test_a_NON_CLIMBING_activity_id_is_a_404(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`logged_session_id` FKs to `logged_session`, not `activity`: a bike ride has no subtype
    row, so its id names nothing this column can hold. The join is what makes that a 404."""
    # The climber's id read off their OWN session, so the cardio row below belongs to THEM:
    # a stranger's would be refused by the ownership arm and prove nothing about the join.
    mine = _logged_session_id(api_client, auth)
    user_id = db_session.scalar(select(Activity.user_id).where(Activity.id == mine))
    assert user_id is not None
    cardio_kind = next(kind for kind in ActivityKind if kind != ActivityKind.CLIMBING)
    cardio = Activity(
        user_id=user_id,
        client_uuid=uuid.uuid4(),
        activity_kind=cardio_kind,
        occurred_on=_TODAY,
        duration_minutes=30,
    )
    db_session.add(cardio)
    db_session.flush()

    response = _put(api_client, auth, str(uuid.uuid4()), logged_session_id=cardio.id)
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == _NO_SESSION


def test_an_EMPTY_ENTRY_is_a_422_AND_NOT_A_500(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ The `not_empty` CHECK must be met at the edge. A 500 here is a payload that retries
    forever and can never succeed, and it reads to the climber as our fault."""
    response = api_client.put(
        f"/api/journal/{uuid.uuid4()}",
        json={"entry_date": _TODAY.isoformat()},
        headers=auth,
    )
    assert response.status_code == 422, response.text
    assert _rows(db_session) == 0


def test_the_route_REQUIRES_A_TOKEN(api_client: TestClient) -> None:
    """Deny-by-default is wired once in `server/app.py`; this is that gate, on this route."""
    response = api_client.put(f"/api/journal/{uuid.uuid4()}", json=_entry())
    assert response.status_code == 401, response.text


def test_a_DEMO_TOKEN_CANNOT_WRITE_AN_ENTRY(
    api_client: TestClient, demo_auth: dict[str, str], db_session: Session
) -> None:
    """Demo mode is read-only, and this route is deliberately NOT in `DEMO_WRITE_EXEMPT_ROUTES`."""
    response = _put(api_client, demo_auth, str(uuid.uuid4()), body=_BODY_MARKER)
    assert response.status_code == 403, response.text
    assert _rows(db_session) == 0
