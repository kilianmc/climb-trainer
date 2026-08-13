"""Access tokens: HS256 JWTs, verified WITHOUT touching the database.

## Statelessness is the whole point

Every authenticated request presents one of these. If validating one required a lookup,
every request would wake Neon — and Neon bills awake time, not queries (see the
compute-budget section of CLAUDE.md). So verification is signature + claims only. The
cost is that a token cannot be revoked before it expires; the refresh family in
`refresh.py` is where revocation actually lives, and the short-ish access lifetime is
what bounds the window.

## Why three hours, and not fifteen minutes

Refresh rotation is a database **write**. A 15-minute access token means a write every
15 minutes for as long as the app is open — across a 45-90 minute training session, plus
planning and diary time, that is the single largest consumer of the free tier's compute
allowance, spent entirely on ceremony. **3 hours** covers a session end to end with one
refresh at most, and the client refreshes lazily (only after a 401), never on a timer.
This is a recorded decision in CLAUDE.md, not an oversight. Demo tokens get **1 hour**
and no refresh at all, because a demo session is a few minutes of looking around.

## Claims, and why `typ` exists

`sub` (user id as a string, per RFC 7519), `scope`, `iat`, `exp`, `iss`, and `typ`.
`typ` is `"access"` and is *required*: today it is the only kind of JWT this app mints,
but the moment a second one exists (an email-verification link, a share token) the
absence of a type claim makes each one accepted wherever the other is — a confused
deputy that is free to prevent now and expensive to retrofit.

## `algorithms=["HS256"]` is explicit, always

Decoding without pinning the algorithm list lets the *token* choose, which is the
`alg: none` forgery and the HMAC-vs-RSA confusion attack in one. `require=[...]` closes
the matching hole at the claim level: a token that simply omits `exp` must not be
treated as one that never expires.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, cast

import jwt

from server.settings import auth_secret

Scope = Literal["user", "demo"]

ISSUER: Final = "climb-trainer"
ALGORITHM: Final = "HS256"
# The value of the `typ` claim, not a secret — ruff's S105 only sees "TOKEN" in the name.
TOKEN_TYPE: Final = "access"  # noqa: S105

# See the module docstring. These are budget decisions as much as security ones.
USER_TOKEN_TTL: Final = timedelta(hours=3)
DEMO_TOKEN_TTL: Final = timedelta(hours=1)

_TTL_BY_SCOPE: Final[dict[Scope, timedelta]] = {
    "user": USER_TOKEN_TTL,
    "demo": DEMO_TOKEN_TTL,
}

# Every claim the verifier depends on. A token missing any of them is rejected outright
# rather than defaulting — an absent `exp` must never read as "no expiry".
_REQUIRED_CLAIMS: Final[list[str]] = ["sub", "scope", "iat", "exp", "iss", "typ"]


class InvalidAccessTokenError(Exception):
    """The token is absent, malformed, expired, tampered with, or of the wrong type.

    Deliberately one exception for all of those: the caller turns it into a single
    generic 401, so the failure reason never reaches the client and becomes a probe.
    """


@dataclass(frozen=True, slots=True)
class Principal:
    """Who the request is, as proven by the token — and nothing else.

    `user_id` here is the ONLY acceptable source of a user id for a query. Never take
    one from a path parameter, a query string or a request body: an unscoped
    `WHERE id = :id` is the IDOR that hands over every user's training history.
    """

    user_id: int
    scope: Scope


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    expires_in: int
    scope: Scope


def issue_access_token(user_id: int, scope: Scope) -> AccessToken:
    now = datetime.now(UTC)
    ttl = _TTL_BY_SCOPE[scope]
    payload = {
        # RFC 7519 says `sub` is a string; PyJWT enforces it. The int round-trips in
        # `decode_access_token`, which is also where a non-numeric `sub` is rejected.
        "sub": str(user_id),
        "scope": scope,
        "typ": TOKEN_TYPE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(payload, auth_secret(), algorithm=ALGORITHM)
    return AccessToken(token=token, expires_in=int(ttl.total_seconds()), scope=scope)


def decode_access_token(token: str) -> Principal:
    """Verify and unpack a token. Raises `InvalidAccessTokenError` for every failure.

    Does not query the database, and must not start: see the module docstring.
    """
    try:
        claims = jwt.decode(
            token,
            auth_secret(),
            # Pinned, never read from the token's own header.
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError as exc:
        raise InvalidAccessTokenError("access token rejected") from exc

    if claims.get("typ") != TOKEN_TYPE:
        raise InvalidAccessTokenError("wrong token type")

    scope = claims.get("scope")
    if scope not in ("user", "demo"):
        raise InvalidAccessTokenError("unknown scope")

    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise InvalidAccessTokenError("malformed subject") from exc

    return Principal(user_id=user_id, scope=cast(Scope, scope))
