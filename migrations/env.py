"""Alembic environment.

Two rules this file enforces, both of which have bitten real projects:

1. **The URL comes from the environment, and its absence is a loud, specific error** —
   not a `None` that surfaces 20 frames deep as "Could not parse SQLAlchemy URL".
   Nothing here reads a URL from `alembic.ini`, because this repo is public.

2. **Alembic uses the DIRECT (unpooled) endpoint.** DDL and `CREATE TYPE` need a real
   session; running them through Neon's PgBouncer transaction-mode pooler is the
   migration failure that presents as an intermittent hang rather than an error.

3. **A non-local host is REFUSED unless `CT_ALLOW_REMOTE_MIGRATION=1`.** See
   `server/db.py::require_migration_host`. Until 2026-08-21 this file had no guard at all
   and its own docstring recommended the bare command — so with the production URL in
   `.env` (which is how this machine is configured), `uv run alembic upgrade head` typed
   locally applied DDL to production and skipped the approval gate entirely. The
   sanctioned path, `.github/workflows/migrate.yml`, sets the variable itself; nothing
   else should. It is deliberately **not** keyed off `CI`/`GITHUB_ACTIONS`.

Migrations are run **out of band** — a manual `workflow_dispatch` job with
`environment: production` and an approval gate — never automatically on push, because
a migration must never race a deploy. Expand -> deploy -> contract, always. CI proves
the migrations by running `alembic upgrade head` against a throwaway Postgres before
pytest.
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
    f"server.settings, so `uv run alembic ...` needs no `--env-file` flag — though note "
    f"it will REFUSE a non-local host without CT_ALLOW_REMOTE_MIGRATION=1; use the "
    f"Migrate workflow for that. "
    f"flag. Never commit a real value: .env is gitignored and this repo is public."
)


def _require_url() -> str:
    """The URL to migrate, after the host has been vetted.

    ⚠️ **The host is extracted and passed on alone — never the URL.** A URL bound to the
    argument of a function that raises is rendered in the traceback, password included;
    that is a real regression this project has already had once (see `host_of`). Note that
    `url` *is* a local of this frame, which a `--showlocals`-style renderer could print, so
    the refusal is raised from `require_migration_host`'s frame rather than from here, and
    nothing on that side ever sees the string.
    """
    url = direct_database_url()
    if url is None:
        raise RuntimeError(_MISSING_URL)
    require_migration_host(host_of(url))
    return normalise_database_url(url)


# NOTE on `compare_type=True`, set in both modes below: a column type change becomes a
# real autogenerate diff instead of being silently ignored, which is what makes
# `alembic check` worth running. `compare_server_default` is deliberately left OFF —
# Postgres round-trips defaults as rendered SQL text, so it reports cosmetic
# differences constantly and would make `alembic check` cry wolf.


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
