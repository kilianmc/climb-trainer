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
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from server.db import get_engine, session_scope
from server.seed import seed_reference_data
from server.settings import POOLED_URL_ENV, pooled_database_url

_SKIP_REASON = (
    f"{POOLED_URL_ENV} is not set — this test needs real Postgres. Local development "
    f"has no database by design; CI runs it against the postgres service container."
)


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
    missing = {"alembic_version", "grade_system", "grade"} - tables
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
