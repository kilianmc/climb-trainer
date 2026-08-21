"""Shared fixtures, and the rule for database-backed tests.

**Tests that need Postgres SKIP when `DATABASE_URL` is unset.** There is no local
Postgres and no Docker on the development machine, so `npm run check` must stay green
without one; CI provides a real Postgres service container, runs
`alembic upgrade head` against it, and therefore is where these tests actually execute.

**SQLite is NOT an option here** and must never be introduced as a stand-in. The schema
depends on native enums, composite foreign keys, `GENERATED ... STORED`, GIN expression
indexes and window functions — a SQLite run would pass while proving nothing, which is
worse than a skip because a skip is visible.

⚠️ **The database host is checked STRUCTURALLY, and that is not paranoia.** Until
2026-08-21 the only thing keeping this suite off the production Neon database was an
env-var assignment inside a shell string in `package.json` — `npm run check:server` sets
`DATABASE_URL="${CT_TEST_DATABASE_URL:-}"`, and running plain `uv run pytest` instead picks
up the real `DATABASE_URL` from `.env` and connects. That was survivable only by accident:
the revision check below happened to fail first because production was still at `0003`.
**The moment `0004` is applied to production, that accident stops protecting anything** —
the `seeded` fixture calls `seed_reference_data` inside `session_scope()`, which
**commits**, so a stray `uv run pytest` would write to production and (per the seed's own
docstring) force the demo account's `password_hash` back to NULL. `server.db.require_local_host`
is the fix, and it is a structural one: an npm script is a convention, and this repo's rule
is that a data-loss guard must not be a convention.

⚠️ **The URL is resolved to a HOST at the boundary, and only the host is passed on.** The
first version of this guard took the URL as a parameter, and pytest renders every frame's
arguments — so one failing run printed the production password **51 times**, once per
dependent test, while the guard's own docstring claimed it never would. The message was
clean; the traceback was not. `server/db.py::host_of` carries the full story and
`tests/test_db_guards.py` pins it.

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
from server.db import (
    get_engine,
    get_session,
    host_of,
    require_database_url,
    require_local_host,
    session_scope,
)
from server.seed import seed_reference_data
from server.settings import AUTH_SECRET_ENV, POOLED_URL_ENV, pooled_database_url

_SKIP_REASON = (
    f"{POOLED_URL_ENV} is not set — this test needs real Postgres. Local development "
    f"has no database by design; CI runs it against the postgres service container."
)

# The allowlist and the refusal both live in `server/db.py`, so this file and
# `migrations/env.py` share one copy of "is that host local?" rather than two that drift.
_REMEDY = (
    "Tests seed reference data and COMMIT, so a non-local database would be written to — "
    "including forcing the demo account's password_hash back to NULL. Use "
    "`npm run check:server` (which clears DATABASE_URL), or set CT_TEST_DATABASE_URL to a "
    "local Postgres. If you genuinely need a remote test database, change LOCAL_DB_HOSTS "
    "in server/db.py deliberately — this guard has no environment-variable override."
)

# Canary table -> the revision that creates it. Used to turn "reachable but not migrated"
# into a SKIP that names what is missing, rather than 47 errors: migrations here run
# out-of-band behind a manual approval gate, so there is a legitimate window between a
# schema PR merging and the migration actually running.
_REQUIRED_TABLES = {
    "alembic_version": "0001",
    "grade_system": "0001",
    "grade": "0001",
    "app_user": "0002",
    "auth_session": "0002",
    "rate_limit": "0002",
    "invite": "0003",
    # One canary per new table family rather than all twenty-four: a database stuck at
    # 0003 is missing `activity` just as visibly as it is missing everything else.
    #
    # It is a CANARY LIST, not an inventory of what the suite touches — the tests also
    # write to `ascent`, `ascent_tag_link`, `exercise` and `user_profile`, and adding those
    # would buy nothing, because no revision creates one without creating these. If a
    # future revision adds a table to a NEW family, add one canary for it here.
    "climbing_aspect": "0004",
    "user_profile": "0004",
    "activity": "0004",
    "logged_session": "0004",
    "logged_set": "0004",
    "journal_entry": "0004",
}

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

    Also checks the migrations have been applied, because "relation does not exist"
    on line 40 of an unrelated test is a much worse message than this one — and does it
    as a SKIP rather than an error, because migrations run out-of-band and the window
    between this PR merging and `0004` being applied is expected, not broken.
    """
    if pooled_database_url() is None:
        pytest.skip(_SKIP_REASON)
    # `host_of(...)` inline, with no intermediate variable, so the URL is never bound to a
    # name in this frame either — `pytest --showlocals` renders fixture locals. Only the
    # host crosses the call boundary.
    require_local_host(
        host_of(require_database_url()), operation="run the test suite", remedy=_REMEDY
    )

    db_engine = get_engine()
    tables = set(inspect(db_engine).get_table_names())
    missing = sorted(set(_REQUIRED_TABLES) - tables)
    if missing:
        revisions = sorted({_REQUIRED_TABLES[table] for table in missing})
        pytest.skip(
            f"database is reachable but not migrated to head: missing {missing}, which "
            f"revision(s) {revisions} create. Run `uv run alembic upgrade head` locally, "
            f"or dispatch `migrate.yml` — migrations here are out-of-band behind an "
            f"approval gate, so this is a skip rather than a failure."
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
