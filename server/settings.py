"""Runtime configuration, read from the environment.

Secrets live in Vercel env vars and the GitHub Actions `production` environment —
never in this repo, which is public. Note the naming rule that bites hardest here:
anything prefixed `VITE_` is inlined into the client bundle at build time and is
therefore PUBLIC. Never give a secret that prefix.
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
