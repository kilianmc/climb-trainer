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

# ⚠️ **A FALLBACK, applied only when the response declares no `cache-control` of its own.**
#
# The invariant is "an API response that does not say how it may be cached must not be
# cacheable", and it exists because a route that sets the header on its injected `Response`
# loses it the moment an `HTTPException` propagates — FastAPI builds the error response from
# scratch, so every 401/404/409/422/500 left `/api/plans*` with no directive at all.
#
# ⚠️ **`setdefault`, never assignment, and blanketing `/api/*` would be a real regression.**
# `GET /api/library` deliberately serves `public, s-maxage=31536000, immutable` from the
# shared CDN — a load-bearing compute-budget decision — and overwriting it would send every
# cold start back to Postgres. That is why this is the ONE header here read with
# `setdefault` while `_HEADERS` above are assigned: those are security headers a route must
# not be able to weaken, and this one is a default a route is expected to override.
_FALLBACK_CACHE_CONTROL: Final = "private, no-store"


class SecurityHeadersMiddleware:
    """Stamps the header set onto every HTTP response.

    A plain ASGI class rather than `BaseHTTPMiddleware`: wrapping `send` is what puts the
    headers on the responses no endpoint produced (401, 403, 404, 422).

    `csp_exempt_paths` is the only route to a response without a CSP. It is passed in from
    `server/app.py`, derived from the configured docs URLs, and is empty in production.

    ⚠️ **One documented gap, pre-existing and accepted:** Starlette's `ServerErrorMiddleware`
    sits OUTSIDE `user_middleware`, so a bare unhandled exception's 500 never passes through
    here and carries none of these headers. Every `HTTPException` — including the 500s
    `server/plans/routes.py` raises deliberately — does pass through, which is why that
    module raises rather than re-raising. Closing the gap needs an `ExceptionMiddleware`
    handler, not a change here.
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
                if "cache-control" not in headers:
                    headers["cache-control"] = _FALLBACK_CACHE_CONTROL
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
