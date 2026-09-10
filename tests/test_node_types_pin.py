"""`@types/node` is HELD at the runtime major in `.nvmrc`, never moved to the newest major.

Type-checking against a runtime we do not run is a defect TypeScript accepts silently: newer
types describe APIs the installed Node does not have, so `tsc` stays green and the call throws.
Staleness is the CORRECT state here, so no other check in this repo objects to a newer major —
a hold nothing enforces is one the next reader "fixes". The reasoning is archived under
"Dependency policy"; the `@types/*` rule there is general, and Node is the case we have.
"""

import json
import re
from typing import Final

from server.settings import ROOT

NVMRC: Final = ROOT / ".nvmrc"
WEB_PACKAGE_JSON: Final = ROOT / "web" / "package.json"


def _major(spec: str) -> int:
    """First run of digits: `24`, `^24.13.3` and `>=24.15.0` all mean major 24."""
    match = re.search(r"\d+", spec)
    assert match, f"no version number in {spec!r}"
    return int(match.group())


def test_types_node_is_held_at_the_runtime_major() -> None:
    """A newer major is refused, not merged, however routine the bump looks."""
    runtime = _major(NVMRC.read_text(encoding="utf-8"))
    web = json.loads(WEB_PACKAGE_JSON.read_text(encoding="utf-8"))
    types = _major(web["devDependencies"]["@types/node"])
    assert types == runtime, (
        f"@types/node is on major {types} but .nvmrc runs Node {runtime}. Hold the types at "
        f"the runtime major; if the runtime itself moved, move both in the same change."
    )
