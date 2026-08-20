"""Shared fixtures, and the rule for database-backed tests.

**Tests that need Postgres SKIP when `DATABASE_URL` is unset.** There is no local
Postgres and no Docker on the development machine, so `npm run check` must stay green
without one; CI provides a real Postgres service container, runs
`alembic upgrade head` against it, and therefore is where these tests actually execute.

**SQLite is NOT an option here** and must never be introduced as a stand-in. The schema
depends on native enums, `text[]`, `GENERATED ... STORED`, GIN indexes and window
functions — a SQLite run would pass while proving nothing, which is worse than a skip
because a skip is visible.

Transaction handling per test: the fixture opens a connection, begins a transaction the
session joins as a SAVEPOINT, and rolls the whole thing back afterwards. So tests see
the seeded reference data, can write freely, and leave nothing behind — and the seed
runs once per session rather than once per test.

`AUTH_SECRET` is injected for the whole run by an autouse fixture, so the *pure* auth
tests (JWT shapes, the public-route table) execute in the local gate with no database
and no local configuration.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from server.app import app
from server.auth import invites
from server.db import get_engine, get_session, session_scope
from server.seed import seed_reference_data
from server.settings import AUTH_SECRET_ENV, POOLED_URL_ENV, pooled_database_url

_SKIP_REASON = (
    f"{POOLED_URL_ENV} is not set — this test needs real Postgres. Local development "
    f"has no database by design; CI runs it against the postgres service container."
)

# Long enough to clear the 32-character floor, and constructed by repetition so it has
# almost no entropy — gitleaks scans this repo's full history and a random-looking
# string next to the word "secret" is exactly what its generic rule looks for.
_FAKE_AUTH_SECRET = "not-a-real-secret-" * 3

# Enough uses that no test has to think about the invite it borrowed from `invite_code`.
_FIXTURE_INVITE_USES = 50


@pytest.fixture(scope="session", autouse=True)
def _auth_secret() -> Iterator[None]:
    """A deterministic signing key for the whole test session.

    Set unconditionally, overriding any real `AUTH_SECRET` from a developer's `.env`, so
    a token minted in one test always verifies in another and a local run cannot behave
    differently from CI.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(AUTH_SECRET_ENV, _FAKE_AUTH_SECRET)
        yield


@pytest.fixture(scope="session")
def engine() -> Engine:
    """A real Postgres engine, or a clean skip.

    Also asserts the migrations have been applied, because "relation does not exist"
    on line 40 of an unrelated test is a much worse error message than this one.
    """
    if pooled_database_url() is None:
        pytest.skip(_SKIP_REASON)

    db_engine = get_engine()
    tables = set(inspect(db_engine).get_table_names())
    missing = {
        "alembic_version",
        "grade_system",
        "grade",
        "app_user",
        "auth_session",
        "invite",
        "rate_limit",
    } - tables
    if missing:
        raise RuntimeError(
            f"database is reachable but not migrated (missing: {sorted(missing)}). "
            f"Run `uv run alembic upgrade head` first."
        )
    return db_engine


@pytest.fixture(scope="session")
def seeded(engine: Engine) -> Engine:
    """Reference data, seeded once per test session from the production seed module."""
    with session_scope() as session:
        seed_reference_data(session)
    return engine


@pytest.fixture
def db_session(seeded: Engine) -> Iterator[Session]:
    connection = seeded.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def invite_code(db_session: Session) -> str:
    """A usable invite code, because `POST /api/auth/register` is invite-gated.

    Generous `max_uses` so one fixture covers a test that registers several accounts. The
    invite table's own behaviour — expiry, revocation, exhaustion, the concurrent spend —
    belongs to `tests/test_auth_invites.py`; everywhere else this is just a door key.
    """
    return invites.create(db_session, label="test fixture", max_uses=_FIXTURE_INVITE_USES).code


@pytest.fixture
def api_client(db_session: Session) -> Iterator[TestClient]:
    """A `TestClient` whose requests run inside the test's rolled-back transaction.

    Overriding `get_session` (rather than letting the app open its own) is what keeps
    endpoint tests from leaving rows behind: handlers commit freely, but a commit on a
    savepoint-joined session only releases the savepoint — the outer transaction is
    still rolled back in `db_session`'s teardown.

    **The base URL is https on purpose.** The refresh cookie carries `Secure`, and
    httpx's cookie jar silently discards a `Secure` cookie received over http — every
    refresh test would then fail for a reason that has nothing to do with the code.
    """

    def _use_test_session() -> Iterator[Session]:
        # No close(): the session belongs to `db_session`, which tears it down.
        yield db_session

    app.dependency_overrides[get_session] = _use_test_session
    try:
        with TestClient(app, base_url="https://climb.kilianmc.com") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
