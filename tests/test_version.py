"""The root `package.json` is the only version source of truth.

This is not a tautology: it asserts the *wiring* — that the FastAPI app actually reads
the root file rather than carrying its own literal. A hardcoded `version=` in
`server/app.py` would be a fourth version string that drifts silently on the first
`npm run version:dev`, and the OpenAPI schema would start lying about which build is
live. Per the testing policy in CLAUDE.md this earns a test because it guards a
project-wide invariant, not because the code is complex.
"""

import json

import pytest

from server.app import app
from server.settings import ROOT, app_version


def _root_package_version() -> str:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def test_app_version_comes_from_root_package_json() -> None:
    assert app.version == _root_package_version()


def test_app_version_is_not_hardcoded_in_the_python_source() -> None:
    """Catches someone "fixing" a version mismatch by pasting a literal back in."""
    source = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert f'version="{_root_package_version()}"' not in source
    assert "version=app_version()" in source


def test_app_version_falls_back_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing/corrupt package.json must not take the whole function down on Vercel."""
    app_version.cache_clear()
    monkeypatch.setattr("server.settings.ROOT", ROOT / "does-not-exist", raising=True)
    try:
        assert app_version() == "0.0.0+unknown"
    finally:
        app_version.cache_clear()
