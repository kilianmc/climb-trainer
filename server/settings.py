"""Runtime configuration, read from the environment.

Secrets live in Vercel env vars and the GitHub Actions `production` environment —
never in this repo, which is public. Note the naming rule that bites hardest here:
anything prefixed `VITE_` is inlined into the client bundle at build time and is
therefore PUBLIC. Never give a secret that prefix.

**This module is also where `.env` gets loaded**, exactly once, at import time — see
`_load_local_dotenv()`. Every entrypoint reaches it (`server.app`, `server.db`,
`server.seed`, `migrations/env.py` and `tests/conftest.py` all import from here), which
is why the load lives here rather than being repeated per entrypoint.
"""

import json
import os
import pathlib
from dataclasses import dataclass, field
from functools import lru_cache

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Fallback only. A wrong-but-obvious version beats an exception at import time, which
# on Vercel would take the whole function down over a cosmetic string.
_UNKNOWN_VERSION = "0.0.0+unknown"

DOTENV_PATH = ROOT / ".env"


def _load_local_dotenv() -> None:
    """Load the gitignored `.env` for local development. Called once, on import.

    Four properties, each deliberate:

    - **Never overrides a real environment variable.** `override=False` (python-dotenv's
      default) means an exported var, a Vercel env var or a CI `env:` block always wins.
      A stale `.env` must never be able to beat what the platform injected.
    - **Skipped entirely in the Vercel runtime.** Vercel sets `VERCEL=1` and
      `VERCEL_ENV`, so a `.env` file that somehow ends up inside a deployment can never
      shadow production config — and a cold start pays no filesystem probe.
    - **Silent no-op when the file is absent.** CI has no `.env` and must stay green.
    - **An explicit path**, not `find_dotenv()`, which walks *up* from the current
      working directory and would happily pick up an unrelated `.env` from a parent
      folder (this repo lives under a shared `Projects/` tree).

    Without this, the whole documented local workflow — `cp .env.example .env` — did
    nothing, and the error messages cheerfully told you to do the thing you had already
    done. That was the bug; do not remove the fix.
    """
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        return
    # Imported here rather than at module scope so the serverless path never touches
    # python-dotenv at all. It IS a real runtime dependency, so this is not a guard
    # against ImportError — it just keeps the cold path empty.
    from dotenv import load_dotenv

    load_dotenv(DOTENV_PATH, override=False)


_load_local_dotenv()


@lru_cache
def app_version() -> str:
    """Read the version from the ROOT `package.json` — the single source of truth.

    `web/package.json` and `pyproject.toml` deliberately stay at 0.0.0, so this is the
    only place the API may learn its version from. Hardcoding it here would make a
    fourth version string that silently drifts on the first `npm run version:dev`.
    A test asserts `app.version` matches the file, so the wiring can't rot.
    """
    try:
        data = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        version = data["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return _UNKNOWN_VERSION
    return version if isinstance(version, str) else _UNKNOWN_VERSION


def _csv(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


# Neon hands out TWO connection strings, and the difference matters:
#
#   DATABASE_URL           -> the *pooled* endpoint (host contains `-pooler`), a
#                             PgBouncer in transaction mode. This is what the app uses.
#   DATABASE_URL_UNPOOLED  -> the *direct* endpoint. Alembic uses this, because DDL
#                             and `CREATE TYPE` need a real session, not a pooled one.
#
# These are Neon's own variable names (its Vercel integration provisions both), so
# don't rename them — a rename means editing the Vercel dashboard too. Both are read
# lazily, never at import time: on Vercel an import-time failure takes the whole
# function down, and locally the SPA-only workflow has no database at all.
POOLED_URL_ENV = "DATABASE_URL"
DIRECT_URL_ENV = "DATABASE_URL_UNPOOLED"


def _env_or_none(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def pooled_database_url() -> str | None:
    """The app's connection string. `None` when no database is configured."""
    return _env_or_none(POOLED_URL_ENV)


def direct_database_url() -> str | None:
    """Alembic's connection string, falling back to the pooled one.

    The fallback exists for CI and local Postgres, where there is only one endpoint
    and no pooler. Against Neon, `DATABASE_URL_UNPOOLED` must be set — running DDL
    through PgBouncer is the migration failure that looks like a random hang.
    """
    return _env_or_none(DIRECT_URL_ENV) or pooled_database_url()


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("VERCEL_ENV", "development"))
    cors_origins: list[str] = field(default_factory=lambda: _csv("CORS_ORIGINS"))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def __post_init__(self) -> None:
        # A wildcard would let any site read authenticated responses. Fail at
        # startup rather than serve one request with it.
        if "*" in self.cors_origins:
            raise RuntimeError("CORS_ORIGINS must be an allowlist, never '*'")


@lru_cache
def get_settings() -> Settings:
    return Settings()
