"""The auth endpoints against real Postgres.

CLAUDE.md's testing policy names auth explicitly — "register, login, refresh rotation,
logout, demo" — as a core user path that earns tests. These are integration tests on
purpose: the risky parts are the transaction boundaries, the cookie attributes and the
rate limiter's commit, none of which a unit test of the handler would exercise.

**Skips without `DATABASE_URL`** (see `conftest.py`). CI runs them for real.
"""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from server.auth.cookies import REFRESH_COOKIE_NAME
from server.auth.deps import get_request_session
from server.auth.tokens import Principal
from server.models import AppUser
from server.seed import DEMO_USER_EMAIL

_EMAIL = "alex@example.com"
_PASSWORD = "a-long-enough-passphrase"


def _register(
    client: TestClient, invite_code: str, email: str = _EMAIL, password: str = _PASSWORD
) -> str:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "invite_code": invite_code},
    )
    assert response.status_code == 201, response.text
    token: str = response.json()["access_token"]
    return token


def test_register_login_refresh_logout_is_one_working_journey(
    api_client: TestClient, invite_code: str
) -> None:
    access_token = _register(api_client, invite_code)
    assert REFRESH_COOKIE_NAME in api_client.cookies

    # The access token from registration authenticates immediately — no second round
    # trip, and `/me` reads the principal straight out of the token.
    me = api_client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    assert me.json()["scope"] == "user"

    # Email is normalised on both write and lookup, so case must not matter.
    login = api_client.post(
        "/api/auth/login", json={"email": _EMAIL.upper(), "password": _PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["scope"] == "user"

    before_refresh = api_client.cookies[REFRESH_COOKIE_NAME]
    refreshed = api_client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert api_client.cookies[REFRESH_COOKIE_NAME] != before_refresh, (
        "refresh must ROTATE the cookie; reusing the same value defeats reuse detection"
    )

    assert api_client.post("/api/auth/logout").status_code == 200
    assert REFRESH_COOKIE_NAME not in api_client.cookies
    # The family is revoked, not merely forgotten by the browser.
    assert api_client.post("/api/auth/refresh").status_code == 401


def test_logout_without_a_cookie_succeeds(api_client: TestClient) -> None:
    """Idempotent by design — a logout that can fail is a probe and a dead end for users."""
    assert api_client.post("/api/auth/logout").status_code == 200


def test_registering_a_taken_email_is_a_409(api_client: TestClient, invite_code: str) -> None:
    """A deliberate, documented departure from the generic anti-enumeration answer.

    See the reasoning in `register`'s docstring: with no email-verification step, a
    generic success would strand a real user. Rate limiting is the mitigation.
    """
    _register(api_client, invite_code)
    duplicate = api_client.post(
        "/api/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD, "invite_code": invite_code},
    )
    assert duplicate.status_code == 409


def test_login_gives_the_same_generic_401_for_unknown_email_and_wrong_password(
    api_client: TestClient,
    invite_code: str,
) -> None:
    _register(api_client, invite_code)

    wrong_password = api_client.post(
        "/api/auth/login", json={"email": _EMAIL, "password": "not-the-password"}
    )
    unknown_email = api_client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": _PASSWORD}
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    # Identical body: the difference between the two is exactly what an enumeration
    # attack is looking for. (`verify_dummy()` equalises the timing; that part is not
    # assertable here without making the suite flaky.)
    assert wrong_password.json() == unknown_email.json()


def test_the_demo_account_can_never_be_logged_into(api_client: TestClient) -> None:
    """Its `password_hash` is NULL, so there is no password that could match."""
    response = api_client.post(
        "/api/auth/login", json={"email": DEMO_USER_EMAIL, "password": _PASSWORD}
    )
    assert response.status_code == 401


def test_a_demo_principal_cannot_write_at_the_database_level(db_session: Session) -> None:
    """The SECOND line of defence, independent of the 403 in `enforce_auth`.

    `SET LOCAL transaction_read_only` means the database itself refuses, so a future
    handler that somehow bypasses the middleware still cannot mutate anything. This test
    exercises the dependency rather than raw SQL — the thing that could regress is the
    wiring, not Postgres.
    """
    scope = {"type": "http", "method": "POST", "path": "/api/anything", "headers": []}
    request = Request(scope)
    request.state.principal = Principal(user_id=1, scope="demo")

    session = next(get_request_session(request, db_session))
    try:
        with pytest.raises(DBAPIError):
            session.execute(
                insert(AppUser).values(email="should-never-exist@example.com", is_demo=False)
            )
    finally:
        # A failed statement poisons the SAVEPOINT, and the rollback is also what clears
        # the read-only flag for the rest of the fixture's teardown.
        db_session.rollback()

    assert (
        db_session.scalar(
            select(AppUser.id).where(AppUser.email == "should-never-exist@example.com")
        )
        is None
    )
