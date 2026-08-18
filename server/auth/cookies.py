"""The refresh cookie — the only cookie this application sets.

Every attribute below is load-bearing. Each one is listed with the thing it prevents,
because "simplify the cookie options" is a plausible-looking change that quietly
removes a control.

- **`httponly=True`** — JavaScript cannot read it, so a stored-XSS bug in the diary
  notes cannot exfiltrate a 30-day credential. This is also why the *access* token
  lives in memory and never in `localStorage`: in the federated mount `localStorage`
  belongs to kilianmc.com, shared with the whole portfolio.

- **NO `domain` attribute** — omitting it makes the cookie **host-only**. Setting
  `Domain=kilianmc.com` would send it to the apex and to every other subdomain,
  i.e. to `portfolio-shell` and any future project. CLAUDE.md is explicit about this.

- **`path="/api/auth"`** — the cookie is only ever attached to the four endpoints that
  need it. Nothing else in the API sees it, so nothing else can accidentally
  authenticate from it.

- **`secure`** from settings, defaulting to on. See `server/settings.py`.

- **`samesite="lax"` — this is the CSRF defence, and it is sufficient here.**
  A cross-site POST from `evil.example` carries no cookie under Lax, so an attacker
  cannot drive `/api/auth/refresh` or `/api/auth/logout` from another origin. The
  federated mount still works because `climb.kilianmc.com` and `kilianmc.com` share a
  registrable domain: they are **cross-origin but same-site**, and SameSite is a
  *site* rule, not an origin rule. A genuine attacker origin is cross-site and blocked.
  (This is also why `*.vercel.app` previews cannot work — the Public Suffix List makes
  every `*.vercel.app` host its own site, so a preview is cross-site to the apex.
  Previews fall back to demo mode; that is expected, not a bug to fix.)

- **No `__Host-` prefix.** It would be a free extra guarantee, but `__Host-` *requires*
  `Path=/`, and scoping the cookie to `/api/auth` is worth more than the prefix: it
  removes the cookie from every non-auth request entirely.

Everything outside `/api/auth` authenticates with a Bearer access token held in memory
and attached explicitly by the client. A header the browser never sends automatically
has **no CSRF surface at all**, which is why there is no CSRF token anywhere in this
codebase — there is nothing for one to protect.
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
