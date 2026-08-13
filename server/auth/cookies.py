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

    The attributes have to match the ones it was set with or the browser treats it as a
    different cookie and leaves the original in place.
    """
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=cookie_secure(),
        httponly=True,
        samesite=_SAMESITE,
    )


def read_refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(REFRESH_COOKIE_NAME)
