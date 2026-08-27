"""The refresh cookie — the only cookie this application sets.

Every attribute is load-bearing, and "simplify the cookie options" is a plausible-looking
change that quietly removes a control. **`httponly=True`** so a stored-XSS bug in the diary
notes cannot exfiltrate a 30-day credential. **NO `domain` attribute**, which makes it
**host-only**: `Domain=kilianmc.com` would send it to the apex, to `portfolio-shell` and to
every future project. **`path="/api/auth"`**, so nothing else in the API ever sees it and
nothing else can accidentally authenticate from it. **`secure`** from settings, defaulting on.

**`samesite="lax"` is the CSRF defence, and it is sufficient here.** A cross-site POST from
`evil.example` carries no cookie under Lax. The federated mount still works because
`climb.kilianmc.com` and `kilianmc.com` share a registrable domain: **cross-origin but
same-site**, and SameSite is a *site* rule. (It is also why `*.vercel.app` previews cannot
work — the Public Suffix List makes every such host its own site, so a preview is cross-site
and falls back to demo mode. Expected, not a bug.) **No `__Host-` prefix**: it would be a free
extra guarantee but *requires* `Path=/`, and scoping to `/api/auth` is worth more.

Everything outside `/api/auth` authenticates with a Bearer token held in memory and attached
explicitly. A header the browser never sends automatically has **no CSRF surface at all**,
which is why there is no CSRF token anywhere in this codebase.
"""

from typing import Final

from fastapi import Request, Response

from server.auth.refresh import REFRESH_TTL
from server.settings import cookie_secure

REFRESH_COOKIE_NAME: Final = "ct_refresh"

# Must match the router prefix in `routes.py`. A mismatch does not fail loudly — the
# browser simply stops sending the cookie and refresh appears to "randomly" 401.
REFRESH_COOKIE_PATH: Final = "/api/auth"

_SAMESITE: Final = "lax"


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=int(REFRESH_TTL.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        secure=cookie_secure(),
        httponly=True,
        samesite=_SAMESITE,
        # No `domain=` — host-only. See the module docstring.
    )


def clear_refresh_cookie(response: Response) -> None:
    """Expire the cookie.

    **`Path` is the attribute that decides whether this deletes anything.** RFC 6265 §5.3
    keys the cookie store on **(name, domain, path)** and nothing else, so a deletion sent
    with the wrong path is a *different* cookie and the real one survives — which is why
    `REFRESH_COOKIE_PATH` is a constant shared with `set_refresh_cookie` rather than a
    literal repeated here. `httponly` and `samesite` are **not** part of that key and a
    mismatch would still delete; `secure` only matters across schemes, which is moot on an
    HTTPS-only site. They are passed anyway so the two calls cannot drift apart — cheap,
    and it keeps the pair readable as one thing.
    """
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=cookie_secure(),
        httponly=True,
        samesite=_SAMESITE,
    )


def clear_refresh_cookie_header() -> str:
    """The same `Set-Cookie` as `clear_refresh_cookie`, as a header value for a handler
    that **raises**.

    ⚠️ Writing a cookie onto the injected `Response` and then raising `HTTPException` is
    **inert**: FastAPI builds a fresh response for the exception and the injected one's
    headers are dropped, so the deletion never reaches the browser. Verified 2026-08-18 —
    the 401 reuse path in `routes.py` had been silently doing nothing since PR #3, which
    left a revoked family's cookie in the jar and turned every subsequent refresh into a
    `ratelimit` write and another five-minute Neon wake. `HTTPException(headers=...)` is
    the mechanism that works, and this is the only place its value is built.

    Built by letting `clear_refresh_cookie` write onto a throwaway `Response` and reading the
    header back, rather than by formatting a second string. The load-bearing part is `Path`:
    RFC 6265 §5.3 keys the cookie store on (name, domain, path), so a hand-written header
    with a different path deletes nothing and the real cookie survives. The other attributes
    are not part of that key — they come along because deriving the whole header from the one
    function is how it stays identical, not because the browser compares them.
    """
    probe = Response()
    clear_refresh_cookie(probe)
    return probe.headers["set-cookie"]


def read_refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(REFRESH_COOKIE_NAME)
