"""`POST /api/auth/demo`, and the seed contract it depends on.

The headline property is that this endpoint issues **zero SQL**, and it is not a
micro-optimisation: Neon Free allows ~400 awake-hours a month and autosuspend is fixed at five
minutes, so a bot trickling one request a minute at a DB-touching public endpoint keeps the
compute awake permanently — and a Postgres rate limit cannot stop that, because enforcing one
is itself a write. The first test proves zero-SQL the only convincing way, **with no database
configured at all**, and runs in the local gate. The rest cover what pinning `DEMO_USER_ID`
could break: the id sequence, and the demo row landing anywhere other than the pinned id.
"""

from typing import Never

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.app import app
from server.auth.cookies import REFRESH_COOKIE_NAME
from server.auth.tokens import DEMO_TOKEN_TTL, decode_access_token
from server.models import AppUser
from server.seed import DEMO_USER_ID, seed_reference_data
from server.settings import POOLED_URL_ENV

_PASSWORD = "a-long-enough-passphrase"


def test_demo_issues_a_token_with_no_database_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero SQL, proved by taking the database away entirely.

    `DATABASE_URL` is removed *and* the engine factories are booby-trapped, so any attempt
    to open a session — by this handler or by a dependency it acquires — fails loudly. The
    handler has no `Session` parameter, so there is nothing to acquire; a future edit that
    adds one back turns this test red immediately.

    This is deliberately not a statement counter: "the endpoint cannot reach the database"
    is a stronger claim than "the endpoint happened to emit no statements".
    """

    def _explode(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError("POST /api/auth/demo must not touch the database")

    monkeypatch.delenv(POOLED_URL_ENV, raising=False)
    monkeypatch.setattr("server.db.get_engine", _explode)
    monkeypatch.setattr("server.db.get_sessionmaker", _explode)

    client = TestClient(app, base_url="https://climb.kilianmc.com")
    response = client.post("/api/auth/demo")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "demo"
    assert body["expires_in"] == int(DEMO_TOKEN_TTL.total_seconds())
    # No refresh cookie: a demo session expires after an hour and simply ends.
    assert REFRESH_COOKIE_NAME not in client.cookies

    principal = decode_access_token(body["access_token"])
    assert principal.scope == "demo"
    # Straight from the pinned constant — this is what removes the lookup.
    assert principal.user_id == DEMO_USER_ID


def test_a_demo_token_can_read_but_the_route_list_forbids_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only, not blind. `/api/auth/me` is DB-free too, so this needs no database."""
    monkeypatch.delenv(POOLED_URL_ENV, raising=False)
    client = TestClient(app, base_url="https://climb.kilianmc.com")
    token = client.post("/api/auth/demo").json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == {"user_id": DEMO_USER_ID, "scope": "demo"}


def test_the_seed_puts_the_demo_account_at_the_pinned_id(db_session: Session) -> None:
    """Demo tokens carry `DEMO_USER_ID`, so a row anywhere else would be a silent mismatch."""
    row = db_session.scalars(select(AppUser).where(AppUser.id == DEMO_USER_ID)).one()
    assert row.is_demo is True
    assert row.password_hash is None, "the demo account must stay unloggable"


def test_the_seed_advances_the_id_sequence_past_the_demo_user(db_session: Session) -> None:
    """Otherwise the first real registration collides with the demo row's primary key.

    Inserting an explicit id does not consume a sequence value, so on a fresh database
    `nextval` would still return 1 — which is `DEMO_USER_ID`. `_advance_user_id_sequence`
    is what prevents that, and this is the assertion that fails without it (CI's database
    is fresh, so the sequence there has never been advanced by anything else).

    Consuming one value with `nextval` is safe and non-destructive; it never lowers the
    sequence, so it cannot leave the database in a state that collides later.
    """
    seed_reference_data(db_session)

    sequence = func.pg_get_serial_sequence(AppUser.__tablename__, "id")
    next_id = db_session.scalar(select(func.nextval(sequence)))

    assert next_id is not None
    assert next_id > DEMO_USER_ID, (
        f"nextval returned {next_id}, which collides with DEMO_USER_ID {DEMO_USER_ID}. "
        f"The seed must repair app_user_id_seq after inserting an explicit id."
    )


def test_registering_after_the_seed_gets_a_fresh_id(
    api_client: TestClient, invite_code: str
) -> None:
    """The behavioural half of the same guard, from the user's side.

    Without the sequence repair this returns **409 "already registered"** — the register
    handler maps `IntegrityError` to a duplicate-email conflict, so a primary-key
    collision with the demo row would present as a baffling rejection on somebody's very
    first sign-up. That misdirection is the reason this test exists.
    """
    response = api_client.post(
        "/api/auth/register",
        json={
            "email": "first-real-user@example.com",
            "password": _PASSWORD,
            "invite_code": invite_code,
        },
    )
    assert response.status_code == 201, response.text
    assert decode_access_token(response.json()["access_token"]).user_id != DEMO_USER_ID
