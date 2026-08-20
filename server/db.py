"""Engine and session wiring — tuned for a serverless function against Neon.

Read this whole docstring before changing any engine argument below. Every one of
them is a deliberate *omission* or an unusual choice, and each looks like something a
well-meaning change would add or "fix".

## The billing model drives the configuration

Neon bills **CU-hours = compute size x time awake**, and the compute stays up for five
minutes after the *last* query. The cost driver is therefore how *spread out* queries
are, not how many rows are written. Consequences, which are the reason for the
omissions below:

- **`NullPool`.** No pool is held. A serverless invocation is frozen between requests,
  so a live pool would be a set of idle connections nobody can use, and Neon's pooled
  endpoint is already doing the pooling for us.
- **No `pool_pre_ping`.** A pre-ping is a `SELECT 1` before handing out a connection.
  With `NullPool` there is nothing stale to check, and every ping is a query that
  restarts the five-minute awake window.
- **No `pool_recycle`.** A recycle timer only has meaning for pooled connections, and
  a timer that can fire on its own is exactly the background chatter to avoid.
- **No liveness/keepalive query anywhere.** `/api/health` deliberately does not touch
  the database. Never add a cron ping to "keep the DB warm": a five-minute ping is
  ~730 CU-hr/month against a 100 CU-hr allowance, i.e. the free tier gone in ~4 days.
- **Lazy engine, no connect at import.** `get_engine()` builds the engine on first
  use; nothing here opens a socket when the module is imported.

## The request session is bound lazily, not at construction

Sessions come from an *unbound* sessionmaker and resolve the engine on their first
statement. FastAPI resolves dependencies before it validates the request body, so a
sessionmaker that needed `DATABASE_URL` turned a malformed body into a 500 instead of a
422 — and made `npm run check` fail on a clone with no database, which the gate promises
it will not.

## Sync SQLAlchemy + psycopg3, not async, not asyncpg

Sync, with `def` endpoints running in FastAPI's anyio threadpool: latency (Neon
autosuspend wake + Python cold start), not concurrency, is the bottleneck at this
scale; Alembic is sync regardless; and it avoids the event-loop and pool-affinity bugs
that async engines produce in a serverless runtime. psycopg3 rather than asyncpg for
the same reason plus better sync ergonomics.

## Prepared statements are left ENABLED — this was checked, twice

Neon's pooled endpoint is PgBouncer in transaction mode, and the folklore is that this
breaks prepared statements. That folklore is out of date, and it is the reason this
comment is long:

- **SQL-level `PREPARE` / `EXECUTE` are not supported** through the pooler.
- **Protocol-level prepared statements ARE supported** (PgBouncer >= 1.22; Neon runs
  its pooler with `max_prepared_statements=1000`). psycopg3 uses the extended query
  protocol, so its prepares are protocol-level and therefore fine.

So there is **no `prepare_threshold=None`** here, deliberately. Do not add one, and do
not "restore" it from an older draft of the plan. Verified against
<https://neon.com/docs/connect/connection-pooling> (2026-08-12).

Note psycopg3's prepare cache is *per connection*, and `NullPool` means one connection
per invocation — so prepares rarely pay off here either way. Leaving them at the
driver default is the no-surprises choice, not an optimisation.

## Other transaction-mode pooler constraints (for later PRs)

Session-level `SET` / `RESET`, `LISTEN` / `NOTIFY`, `WITH HOLD` cursors and
session-level advisory locks do not work through the pooled endpoint. Transaction-
scoped `SET LOCAL` does — which is what the demo path's `SET LOCAL
transaction_read_only` relies on (PR #3). Keep it `SET LOCAL`, never a bare `SET`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from server.settings import DOTENV_PATH, POOLED_URL_ENV, pooled_database_url

# psycopg3's SQLAlchemy dialect. Neon (and CI) hand out plain `postgresql://` URLs,
# which SQLAlchemy would route to psycopg2 — a dependency this project does not have.
_DRIVER = "postgresql+psycopg"
_REWRITABLE_PREFIXES = ("postgresql://", "postgres://")

# Fail a connection attempt rather than hang. Neon's autosuspend wake is ~300-800 ms,
# so 10 s is generous; without a timeout a network fault burns the function's whole
# 300 s budget. This is a connect option, not periodic traffic.
_CONNECT_ARGS: dict[str, object] = {"connect_timeout": 10}


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database is needed but no connection string is set."""


def normalise_database_url(url: str) -> str:
    """Force the psycopg3 driver onto an otherwise driver-less Postgres URL.

    Left alone if the URL already names a driver (`postgresql+psycopg://`), so an
    explicit choice is never silently overridden.
    """
    for prefix in _REWRITABLE_PREFIXES:
        if url.startswith(prefix):
            return f"{_DRIVER}://{url[len(prefix) :]}"
    return url


def target_host_and_database() -> tuple[str, str]:
    """The **host** and **database name** of `DATABASE_URL` — and nothing else from it.

    The single redaction point for "which database am I about to write to?", used by the
    interactive confirmations in `server/admin.py` and `server/devseed.py`. Never returns
    the URL, the driver, the user or the password: this repository is public, and so is a
    terminal transcript pasted into an issue. Both callers print the result, so this is the
    one string in the codebase that has to stay clean by construction rather than by the
    caller remembering to trim it.

    `tests/test_devseed.py::test_target_host_never_returns_a_credential` pins that property.
    """
    url = pooled_database_url()
    if url is None:
        return ("(no DATABASE_URL configured)", "(none)")
    parsed = make_url(normalise_database_url(url))
    return (parsed.host or "(local socket)", parsed.database or "(default)")


def require_database_url() -> str:
    url = pooled_database_url()
    if url is None:
        raise DatabaseNotConfiguredError(
            f"{POOLED_URL_ENV} is not set. Locally: `cp .env.example .env` and paste "
            f"the Neon *pooled* connection string (the host containing '-pooler'). "
            f"{DOTENV_PATH} is loaded automatically by server/settings.py, so no "
            f"`--env-file` flag and no shell-sourcing are needed, and an exported "
            f"variable takes precedence over it. On Vercel, .env is deliberately NOT "
            f"read — set the variable in the project's environment variables instead."
        )
    return normalise_database_url(url)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The process-wide engine, built on first use.

    Cached so a warm invocation reuses it, but note that with `NullPool` the engine
    holds no connections — reuse buys dialect setup, not sockets. See the module
    docstring before adding any pool argument.
    """
    return create_engine(
        require_database_url(),
        poolclass=NullPool,
        connect_args=_CONNECT_ARGS,
        # `future`-style 2.0 behaviour is the default in SQLAlchemy 2; stated only so
        # nobody wonders. No `echo` — query logs in a serverless function are billed
        # CPU and land nowhere useful.
    )


class LazyBindSession(Session):
    """A session that asks for the engine when it first runs a statement, not before."""

    def get_bind(self, *args: Any, **kwargs: Any) -> Engine:
        return get_engine()


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    # No `bind=`: see the docstring. Scripts and seeds therefore hit the missing-URL
    # error at their first query rather than at session construction — same message.
    #
    # expire_on_commit=False: after committing, a response serialiser reading an
    # attribute would otherwise trigger a fresh SELECT, i.e. a second round trip to a
    # database we are trying to keep asleep.
    return sessionmaker(class_=LazyBindSession, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts, seeds and background-free one-shot work.

    Commits on success, rolls back on any exception, always closes.
    """
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one connection per request, released at response time.

    Deliberately does NOT commit — endpoints commit explicitly, so a read path never
    opens a write transaction it does not need.
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
