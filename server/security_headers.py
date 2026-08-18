"""Security response headers for `/api/*`.

`vercel.json` covers what the CDN serves (the SPA document, JS, CSS). This covers the
API's JSON in-process, so it also applies under bare `uvicorn` and can be asserted in
CI — see `tests/test_security_headers.py`.
"""

from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Only features we mean to restrict are listed; an unlisted feature keeps its browser
# default. `screen-wake-lock`, `fullscreen` and `autoplay` are deliberately absent — the
# session player needs all three. Asserted in tests.
PERMISSIONS_POLICY: Final = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), "
    "bluetooth=(), midi=(), display-capture=(), idle-detection=()"
)

# The API returns JSON only, so it needs no sources at all. No `sandbox` directive:
# without `allow-downloads` it would block a future export endpoint.
API_CSP: Final = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

# `frame-ancestors 'none'` and `X-Frame-Options: DENY` are safe here because the shell
# mounts this app as a script (`import('climbTrainer/App')`), never in an iframe.
# `Cross-Origin-Resource-Policy` is deliberately unset — see CLAUDE.md for why.
_HEADERS: Final[tuple[tuple[str, str], ...]] = (
    ("X-Content-Type-Options", "nosniff"),
    # Tighter than the browser default: nothing here needs a referrer.
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", PERMISSIONS_POLICY),
)

# `Strict-Transport-Security` is deliberately not set: Vercel already sends it, and a
# duplicate field is ignored rather than merged. See CLAUDE.md.


class SecurityHeadersMiddleware:
    """Stamps the header set onto every HTTP response.

    A plain ASGI class rather than `BaseHTTPMiddleware`: wrapping `send` is what puts the
    headers on the responses no endpoint produced (401, 403, 404, 422).

    `csp_exempt_paths` is the only route to a response without a CSP. It is passed in from
    `server/app.py`, derived from the configured docs URLs, and is empty in production.
    """

    def __init__(self, app: ASGIApp, *, csp_exempt_paths: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.csp_exempt_paths = csp_exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # `scope["path"]`, not `request.url.path`: the ASGI request target rather than a
        # URL rebuilt from the client-controlled Host header, matched by exact equality.
        send_csp = scope.get("path") not in self.csp_exempt_paths

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # Assignment, not `setdefault`: a route must not be able to weaken these.
                for name, value in _HEADERS:
                    headers[name] = value
                if send_csp:
                    headers["Content-Security-Policy"] = API_CSP
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
