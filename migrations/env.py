"""Alembic environment: the DIRECT (unpooled) endpoint, and a remote host is REFUSED.

DDL through Neon's transaction-mode PgBouncer pooler HANGS rather than errors, so the pooled
URL is only a fallback where there is one endpoint (CI, local Postgres). The refusal exists
because on 2026-08-21 this file had no guard and its own docstring recommended the bare
command: with the production URL in `.env`, a local `uv run alembic upgrade head` applied DDL
to production and skipped the approval gate. See CLAUDE.md, "Migrations run out-of-band", and
`server.db.require_migration_host`.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from server.db import host_of, normalise_database_url, require_migration_host
from server.models import Base

# Importing server.settings is also what loads the local `.env` (once, on import), so
# `uv run alembic ...` picks it up with no --env-file flag. Keep this import.
from server.settings import DIRECT_URL_ENV, DOTENV_PATH, POOLED_URL_ENV, direct_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate and `alembic check` compare the live database against this.
target_metadata = Base.metadata

_MISSING_URL = (
    f"No database URL. Set {DIRECT_URL_ENV} (Neon's *direct*, non-pooler connection "
    f"string — DDL must not go through the transaction-mode pooler), or {POOLED_URL_ENV} "
    f"when there is only one endpoint, as in CI and local Postgres. Locally: "
    f"`cp .env.example .env` and fill it in — {DOTENV_PATH} is loaded automatically via "
    f"server.settings, so `uv run alembic ...` needs no `--env-file` flag. Note that a "
    f"non-local host is REFUSED without CT_ALLOW_REMOTE_MIGRATION=1; use the Migrate "
    f"workflow for that, and never commit a real value — .env is gitignored and this repo "
    f"is public."
)


def _require_url() -> str:
    """Vets the HOST alone: a URL in a frame local or argument prints password-and-all in a
    traceback (a regression this repo has had), so `require_migration_host` raises, not us."""
    url = direct_database_url()
    if url is None:
        raise RuntimeError(_MISSING_URL)
    require_migration_host(host_of(url))
    return normalise_database_url(url)


# `compare_type=True`, set in BOTH modes below: a column type change becomes a real
# autogenerate diff instead of being silently ignored. `compare_server_default` stays OFF.


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: emit SQL without connecting."""
    context.configure(
        url=_require_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # NullPool: a migration run is one connection, once. Nothing to pool, and no idle
    # connection left holding Neon's compute awake after the last statement.
    engine = create_engine(_require_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
