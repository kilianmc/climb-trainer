"""Shared fixtures, and the rule for database-backed tests.
**Tests needing Postgres SKIP when `DATABASE_URL` is unset**, so `npm run check` stays green on
a clone with no database; export `CT_TEST_DATABASE_URL` and `npm run db:up` to run them. CI
always runs them. **SQLite is NOT an option and must never be introduced as a stand-in** — the
schema needs native enums, composite FKs, `GENERATED ... STORED`, GIN expression indexes and
window functions, so a SQLite run would pass while proving nothing, which is worse than a
visible skip. ⚠️ **The database host is checked STRUCTURALLY** (`server.db.require_local_host`):
an npm script setting `DATABASE_URL=""` is a convention, and a plain `uv run pytest` picks the
real URL out of `.env` — the `seeded` fixture **commits**, so that would write to production and
force the demo account's `password_hash` back to NULL. ⚠️ **Only the HOST is passed on, never
the URL**: pytest renders every frame's arguments, and one failing run printed the production
password 51 times. Per test: a connection, a transaction the session joins as a SAVEPOINT, and
a rollback — so tests write freely and leave nothing behind. `AUTH_SECRET` is autouse, so the
pure auth tests run in the local gate with no database and no local configuration.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.orm import Session

from server.app import app
from server.auth import invites
from server.contentseed import seed_exercise_library
from server.db import (
    get_engine,
    get_session,
    host_of,
    require_database_url,
    require_local_host,
    session_scope,
)
from server.models import AppUser
from server.seed import seed_reference_data
from server.settings import AUTH_SECRET_ENV, POOLED_URL_ENV, pooled_database_url

_SKIP_REASON = (
    f"{POOLED_URL_ENV} is not set — this test needs real Postgres. Export "
    f"CT_TEST_DATABASE_URL and run `npm run db:up` to run these locally; CI always runs them "
    f"against its postgres service container."
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

# ⚠️ **Column granularity, because the list above cannot see a revision that adds no
# table.** `0007` adds two columns to `exercise` and nothing else, and the session-scoped
# `seeded` fixture writes one of them — so against a database still at `0006` the
# table check passed, the fixture raised `UndefinedColumn`, and every DB-backed test
# ERRORED out of a session-scoped fixture instead of skipping. That is precisely the
# failure the skip exists to prevent: migrations here run out-of-band behind an approval
# gate, so a developer whose `CT_TEST_DATABASE_URL` points at an un-upgraded database
# should be told to upgrade, not handed a wall of red.
#
# Same discipline as the table list: **one canary per revision that adds only columns**,
# not an inventory of every column the suite touches. Add an entry when a revision adds a
# column that a FIXTURE or a widely-used helper writes — a column only one test reads can
# stay out, because that test fails on its own and reads clearly.
_REQUIRED_COLUMNS: dict[tuple[str, str], str] = {
    # Both written by `seed_exercise_library` on every run of the `seeded` fixture.
    ("exercise", "substitution_hint"): "0007",
    ("exercise", "retired_at"): "0007",
    # ⚠️ Written by no fixture — a judgement call against the rule above, and the reason is
    # blast radius rather than reach. `POST /api/plans` writes both columns on every call,
    # and #11b's test suite exercises that endpoint from a dozen tests plus a shared
    # persist helper; against a database still at `0007` each one would raise
    # `UndefinedColumn` from inside the handler, which is the wall of red this skip exists
    # to replace. One canary per revision, so `plan` stands in for `session_block` too.
    ("plan", "current_grade_id"): "0008",
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
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    missing = {
        table: revision for table, revision in _REQUIRED_TABLES.items() if table not in tables
    }
    if not missing:
        # Only worth asking once the tables are all there: `get_columns` on a table that
        # does not exist raises rather than returning nothing, and the table-level answer
        # is the more useful message anyway.
        present = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in {table for table, _ in _REQUIRED_COLUMNS}
        }
        missing = {
            f"{table}.{column}": revision
            for (table, column), revision in _REQUIRED_COLUMNS.items()
            if column not in present[table]
        }
    if missing:
        pytest.skip(
            f"database is reachable but not migrated to head: missing "
            f"{sorted(missing)}, which revision(s) {sorted(set(missing.values()))} create. "
            f"Run `uv run alembic upgrade head` locally, or dispatch `migrate.yml` — "
            f"migrations here are out-of-band behind an approval gate, so this is a skip "
            f"rather than a failure."
        )
    return db_engine


def _refuse_a_polluted_database(session: Session) -> None:
    """Fail loudly when the database carries accounts no test created.

    `npm run dev:api` reads `CT_TEST_DATABASE_URL`, so the database you click the app
    against IS the one the suite runs on. One hand-made account leaves rows behind, and the
    tests that assert a GLOBAL row count then fail naming *profile validation* — a red
    pointing at the code instead of at the database. CI is unaffected; its Postgres is
    per-run and empty.
    """
    stray = session.scalar(select(func.count()).select_from(AppUser).where(~AppUser.is_demo))
    if stray:
        raise RuntimeError(
            f"{stray} non-demo app_user row(s) present before seeding. This database has "
            f"accounts the suite did not create — most likely from clicking through "
            f"`npm run dev:api`. Tests asserting global row counts would fail for the wrong "
            f"reason. Run `npm run db:reset` then `uv run alembic upgrade head`."
        )


@pytest.fixture(scope="session")
def seeded(engine: Engine) -> Engine:
    """Reference data AND the exercise library, from the two production seed modules.

    Both, in production's order: `server/contentseed.py` resolves aspect, equipment and
    injury *keys* to ids, so it needs the vocabularies to exist first. Same argument as the
    fixture itself — a test fixture that hand-wrote its own exercises would be testing a
    library production never has.
    """
    with session_scope() as session:
        _refuse_a_polluted_database(session)
        seed_reference_data(session)
        seed_exercise_library(session)
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
