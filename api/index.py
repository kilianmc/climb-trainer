"""Vercel Python entrypoint.

Thin by design: the application lives in `server/`. Spike S0 confirmed a function in
`api/` can import it, provided the deployment root is on `sys.path`.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from server.app import app  # noqa: E402

__all__ = ["app"]
