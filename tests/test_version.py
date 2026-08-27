"""The root `package.json` is the only version source of truth.

Not a tautology: it asserts the *wiring* — that the FastAPI app reads the root file rather than
carrying its own literal. A hardcoded `version=` in `server/app.py` would be a fourth version
string that drifts silently on the first `npm run version:dev`, and the OpenAPI schema would
then lie about which build is live. It guards a project-wide invariant, not complex code.

**One test, deliberately**: a grep for a stale literal restates the implementation, and a
fallback for a missing `package.json` is a two-line `except`.
"""

import json

from server.app import app
from server.settings import ROOT


def test_app_version_comes_from_root_package_json() -> None:
    expected = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert app.version == expected
