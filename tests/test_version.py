"""The root `package.json` is the only version source of truth.

This is not a tautology: it asserts the *wiring* — that the FastAPI app actually reads
the root file rather than carrying its own literal. A hardcoded `version=` in
`server/app.py` would be a fourth version string that drifts silently on the first
`npm run version:dev`, and the OpenAPI schema would start lying about which build is
live. Per the testing policy in CLAUDE.md this earns a test because it guards a
project-wide invariant, not because the code is complex.

**One test, deliberately.** PR #1 also asserted that no literal had crept back into the
source and that a missing `package.json` falls back instead of raising. Both were cut
in PR #2: the first greps the implementation rather than testing behaviour (and this
test already fails if a stale literal is ever wrong), and the second tests a two-line
`except` clause. Per the policy, a test that restates the implementation is maintenance
cost with no safety value.
"""

import json

from server.app import app
from server.settings import ROOT


def test_app_version_comes_from_root_package_json() -> None:
    expected = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert app.version == expected
