"""Engine and session wiring — tuned for a serverless function against Neon.

Read this before changing any engine argument: every one is a deliberate *omission* or an
unusual choice, and each looks like something a well-meaning change would add.

Neon bills **CU-hours = compute size x time awake**, and stays up five minutes after the last
query — so the cost driver is how SPREAD OUT queries are, not how many rows are written. Hence
**`NullPool`** (a frozen invocation cannot use a pool, and Neon's pooled endpoint already
pools); **no `pool_pre_ping`** (a `SELECT 1` restarts the five-minute window); **no
`pool_recycle`** (a timer that fires on its own); **no keepalive or cron ping anywhere** (five
minutes apart is ~730 CU-hr/month against a 100 CU-hr allowance — the free tier gone in four
days, which is why `/api/health` touches no database); and a **lazy engine** that opens no
socket at import. Sessions come from an *unbound* sessionmaker and resolve the engine on their
first statement, because FastAPI resolves dependencies before validating a body — a bound one
turned a malformed body into a 500 and failed the gate on a clone with no database.

Sync SQLAlchemy + psycopg3, not async: latency (autosuspend wake + cold start), not
concurrency, is the bottleneck, Alembic is sync anyway, and async engines bring event-loop and
pool-affinity bugs in a serverless runtime.

⚠️ **Prepared statements are left ENABLED — there is no `prepare_threshold=None`, deliberately,
and it must not be "restored" from an older draft of the plan.** The folklore that PgBouncer
transaction mode breaks them is out of date: SQL-level `PREPARE`/`EXECUTE` are unsupported, but
psycopg3 uses **protocol-level** prepares, which are supported (PgBouncer >= 1.22; Neon runs
`max_prepared_statements=1000`). Verified against
<https://neon.com/docs/connect/connection-pooling>, 2026-08-12. They rarely pay off here
regardless — the cache is per connection and `NullPool` means one connection per invocation.

Other transaction-mode pooler limits, for later PRs: session-level `SET`/`RESET`,
`LISTEN`/`NOTIFY`, `WITH HOLD` cursors and session-level advisory locks do not work pooled.
Transaction-scoped **`SET LOCAL` does**, which the demo path relies on — never a bare `SET`.
"""

import os
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


# ---------------------------------------------------------------------------------
# Which database am I about to touch? — the two guards, and the credential rule
# ---------------------------------------------------------------------------------
#
# Hosts that are safe to run a test suite or an ad-hoc migration against. Loopback covers
# a developer's own Postgres; `postgres` and `db` cover a service container or a compose
# service addressed by name.
#
# `host=None` — a unix-socket URL, or a URL with no host at all — is **not** in here, so
# it fails CLOSED. That is deliberate: an unresolvable host is not evidence of locality.
LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "db"})

# The opt-in that lets a migration run against a remote database. Set by
# `.github/workflows/migrate.yml`, which exists precisely to do that behind an approval
# gate. **Deliberately NOT keyed off `CI` or `GITHUB_ACTIONS`** (Kilian, 2026-08-21):
# trusting an ambient CI variable means any workflow, in any repo, that happens to set it
# inherits permission to migrate production.
REMOTE_MIGRATION_ENV = "CT_ALLOW_REMOTE_MIGRATION"


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database is needed but no connection string is set."""


class RemoteDatabaseRefused(RuntimeError):
    """Refused: this operation would have touched a non-local database."""


def host_of(url: str) -> str | None:
    """The host of a connection string, or `None` when it has none (unix socket).

    ⚠️ **Call this at the boundary and pass the HOST onward — never the URL.** The two
    `require_*` functions below take a host for exactly one reason: a URL bound to a
    parameter or a local of a function that raises is rendered by pytest and by most
    tracebacks, password included. `require_local_host("ep-x.neon.tech")` can only ever
    print a hostname; `require_local_host(url)` prints the credential once per dependent
    test. That happened, in this repo, to the first version of the test-suite guard —
    51 occurrences in one run. Same lesson as `target_host_and_database` above, and the
    same lesson CLAUDE.md draws from `alembic current --verbose`: audit what a tool prints
    at its chosen verbosity, not just what you meant to print.
    """
    return make_url(normalise_database_url(url)).host


def is_local_host(host: str | None) -> bool:
    """Exact membership, never a suffix or substring test.

    A substring or `endswith` check is the classic hole here: `localhost.evil.com`,
    `notlocalhost` and `127.0.0.1.nip.io` all pass one. `2130706433` (loopback as a
    decimal integer) and `::ffff:127.0.0.1` are also correctly refused — they resolve to
    loopback, but they are not spellings anything in this project produces, so refusing
    them costs nothing and keeps the rule a lookup rather than a parser.
    """
    return host in LOCAL_DB_HOSTS


def require_local_host(host: str | None, *, operation: str, remedy: str) -> None:
    """Refuse a non-local host outright. No override, by design.

    Used by `tests/conftest.py`. An environment-variable escape hatch is exactly what gets
    set once in a `.env` and then forgotten, which is the failure this guard exists for —
    so pointing the suite at a remote database is a code change, not a variable.
    """
    if is_local_host(host):
        return
    raise RemoteDatabaseRefused(
        f"refusing to {operation} against database host {host!r}. Allowed hosts: "
        f"{sorted(LOCAL_DB_HOSTS)}. {remedy}"
    )


def require_migration_host(host: str | None) -> None:
    """Refuse a non-local host for Alembic **unless** `CT_ALLOW_REMOTE_MIGRATION=1`.

    ## Why this one has an opt-in and the test guard does not

    `.github/workflows/migrate.yml` exists to run migrations against production — that is
    its entire purpose — so a flat allowlist would break the sanctioned path and leave the
    unsanctioned one working. The opt-in inverts that: the workflow declares its intent,
    and a developer typing `uv run alembic upgrade head` with a production URL in `.env`
    gets stopped.

    ⚠️ **That developer path was live until 2026-08-21.** `.env` on the development machine
    holds the production URL in both variables, `migrations/env.py` had no guard at all, and
    its own docstring recommended the bare command. Migrations here are supposed to run
    out-of-band behind a `workflow_dispatch` approval gate; without this, the approval gate
    was one keystroke away from being optional.

    Read-only Alembic actions are refused too. That is intentional: `alembic current`
    against production is harmless, but allowing it means the guard has to decide which
    subcommand is running, and getting that wrong fails open on the one that writes DDL.
    """
    if is_local_host(host):
        return
    if os.environ.get(REMOTE_MIGRATION_ENV) == "1":
        return
    raise RemoteDatabaseRefused(
        f"refusing to run Alembic against database host {host!r}: migrations run "
        f"OUT-OF-BAND in this project, never from a developer's terminal. Use the "
        f"Migrate workflow — Actions -> Migrate -> Run workflow, or "
        f"`gh workflow run migrate.yml --ref dev -f environment=dev -f action=upgrade` — "
        f"which runs with `environment: production`'s approval gate and sets "
        f"{REMOTE_MIGRATION_ENV}=1 itself. Allowed hosts without that variable: "
        f"{sorted(LOCAL_DB_HOSTS)}. See CLAUDE.md, 'Migrations run out-of-band'."
    )


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
