"""Alembic environment.

Two rules this file enforces, both of which have bitten real projects:

1. **The URL comes from the environment, and its absence is a loud, specific error** —
   not a `None` that surfaces 20 frames deep as "Could not parse SQLAlchemy URL".
   Nothing here reads a URL from `alembic.ini`, because this repo is public.

2. **Alembic uses the DIRECT (unpooled) endpoint.** DDL and `CREATE TYPE` need a real
   session; running them through Neon's PgBouncer transaction-mode pooler is the
   migration failure that presents as an intermittent hang rather than an error.

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

from server.db import normalise_database_url
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
    f"server.settings, so plain `uv run alembic ...` is enough, with no `--env-file` "
    f"flag. Never commit a real value: .env is gitignored and this repo is public."
)


def _require_url() -> str:
    url = direct_database_url()
    if url is None:
        raise RuntimeError(_MISSING_URL)
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
