"""The `/api/auth/*` endpoints.

Every request body is a Pydantic model with `extra="forbid"` and bounded string lengths,
and every ORM object is built by **assigning fields explicitly**. Never
`AppUser(**payload)`: mass assignment from a client dict is how `is_demo` or a `user_id`
gets set by whoever asks nicely.

## These routes use `get_session`, not `RequestSession`

Deliberate. `RequestSession` applies `SET LOCAL transaction_read_only` for a demo
principal, and `POST /api/auth/demo` is the one route a demo token may still POST to.
That route now takes no session at all, but the distinction still matters for the others:
none of them run under a demo principal, and none should acquire a read-only transaction
by accident. Everything outside this module should use `RequestSession`.

## Rate limiting comes first in every handler that has it

`ratelimit.enforce` / `enforce_all` commit, so they must run before the handler starts
building anything it would be sad to have committed early. Being first in the body also
means the expensive work (argon2, in `register` and `login`) is never reached by a client
that is already over the limit. The only thing that may precede it is normalising the
email, which `login`'s account-keyed bucket needs as its subject.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.auth import ratelimit, refresh
from server.auth.cookies import clear_refresh_cookie, read_refresh_cookie, set_refresh_cookie
from server.auth.deps import CurrentUser
from server.auth.passwords import hash_password, needs_rehash, verify_dummy, verify_password
from server.auth.tokens import Scope, issue_access_token
from server.db import get_session
from server.models import AppUser
from server.seed import DEMO_USER_ID

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Plain session — see the module docstring for why these routes opt out of the
# demo read-only wrapper.
DbSession = Annotated[Session, Depends(get_session)]

# One message for "no such account" and for "wrong password". Anything more specific is
# an account-enumeration oracle; `verify_dummy()` makes the *timing* match too.
_GENERIC_LOGIN_FAILURE: Final = "Incorrect email or password."

# 254 is the RFC 5321 maximum and matches `app_user.email`.
_MAX_EMAIL_LENGTH: Final = 254

# A length floor and nothing else. NIST dropped composition rules (a digit, a symbol,
# mixed case) years ago: they push users towards `Password1!`, which is both weaker and
# more annoying than a long passphrase. 128 is an upper bound because argon2 hashes the
# whole input and an unbounded field is a cheap way to burn CPU.
_MIN_PASSWORD_LENGTH: Final = 12
_MAX_PASSWORD_LENGTH: Final = 128


def _normalise_email(value: str) -> str:
    """Lowercase and strip. `app_user.email` has no `citext`, so this is the invariant.

    Every write and every lookup goes through here. If one path skips it, two accounts
    differing only in case become possible and the unique constraint stops meaning what
    it appears to mean.
    """
    return value.strip().lower()


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[EmailStr, Field(max_length=_MAX_EMAIL_LENGTH)]
    password: Annotated[
        str, Field(min_length=_MIN_PASSWORD_LENGTH, max_length=_MAX_PASSWORD_LENGTH)
    ]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Bounded, but with no minimum: enforcing the registration floor here would tell an
    # attacker the password policy from a 422, and would reject legitimate users whose
    # password predates a future policy change.
    email: Annotated[EmailStr, Field(max_length=_MAX_EMAIL_LENGTH)]
    password: Annotated[str, Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)]


class TokenResponse(BaseModel):
    """The access token, for the client to hold **in memory only**.

    Never `localStorage`: in the federated mount that storage belongs to kilianmc.com and
    is shared with the whole portfolio (CLAUDE.md). The refresh token is not in this body
    at all — it is the httpOnly cookie.
    """

    access_token: str
    # The OAuth 2.0 `token_type` value, not a credential — ruff's S105 keys off the
    # word "token" in the field name, hence the suppression.
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    scope: Scope


class MeResponse(BaseModel):
    user_id: int
    scope: Scope


class LogoutResponse(BaseModel):
    status: Literal["ok"] = "ok"


def _token_response(user_id: int, scope: Scope) -> TokenResponse:
    issued = issue_access_token(user_id, scope)
    return TokenResponse(
        access_token=issued.token, expires_in=issued.expires_in, scope=issued.scope
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> TokenResponse:
    """Create an account, log it in, and start a refresh family.

    **A duplicate email returns 409, and that is a considered trade-off.** The textbook
    anti-enumeration answer is a generic "check your inbox" that reveals nothing — but it
    only works when there IS an inbox step. This product has no email verification, so a
    generic response would leave a real person staring at a form that appears to have
    worked while no account exists, with no way to discover that they already have one.
    Being honest here is worth more than hiding a fact that `/api/auth/login` timing and
    a password-reset flow would eventually expose anyway. **Rate limiting is the
    mitigation**: `REGISTER` is 3 per hour per client, which makes enumerating a list of
    addresses impractical.
    """
    ratelimit.enforce(session, request, ratelimit.REGISTER)

    email = _normalise_email(payload.email)
    if session.scalar(select(AppUser.id).where(AppUser.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email is already registered."
        )

    # Explicit assignment, never `AppUser(**payload.model_dump())` — `is_demo` is set
    # here and must not be settable by the request.
    user = AppUser(email=email, password_hash=hash_password(payload.password), is_demo=False)
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        # Lost the race against a concurrent registration of the same address. The
        # SELECT above is the friendly path; the unique constraint is the correct one.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email is already registered."
        ) from None

    issued = refresh.issue(session, user.id)
    session.commit()

    set_refresh_cookie(response, issued.token)
    return _token_response(user.id, "user")


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> TokenResponse:
    """Exchange credentials for an access token and a fresh refresh family."""
    # Normalised first because the account-keyed bucket below keys on the normalised
    # form — `Kilian@x.com` and `kilian@x.com` must share one budget.
    email = _normalise_email(payload.email)

    # TWO buckets, ONE statement: by client IP (stops one machine hammering) and by the
    # ATTEMPTED EMAIL (stops the same attack spread across many machines, which the
    # per-IP rule cannot). The email counter increments for every address tried, whether
    # or not it exists, so the resulting 429 is identical either way and can never be
    # used to discover whether an account exists.
    ratelimit.enforce_all(
        session,
        (ratelimit.LOGIN, ratelimit.client_ip(request)),
        (ratelimit.LOGIN_ACCOUNT, email),
    )

    user = session.scalars(select(AppUser).where(AppUser.email == email)).one_or_none()

    # A NULL `password_hash` is the seeded demo account: it has no password and can
    # never be logged into this way. Same branch as "no such user", same generic 401.
    if user is None or user.password_hash is None:
        # Equalise the response time so this path is not distinguishable from a wrong
        # password. Without it the generic message below is decoration.
        verify_dummy()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_GENERIC_LOGIN_FAILURE)

    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_GENERIC_LOGIN_FAILURE)

    if needs_rehash(user.password_hash):
        # The only moment the plaintext exists, and the request is committing anyway —
        # so raising the argon2 parameters later migrates users as they sign in, with no
        # extra round trip and no downtime.
        user.password_hash = hash_password(payload.password)

    issued = refresh.issue(session, user.id)
    session.commit()

    set_refresh_cookie(response, issued.token)
    return _token_response(user.id, "user")


@router.post("/refresh")
def refresh_tokens(
    request: Request,
    response: Response,
    session: DbSession,
) -> TokenResponse:
    """Rotate the refresh cookie and mint a new access token.

    The client calls this **lazily, only after a 401** — never on a timer. A periodic
    refresh is a periodic database write, which is the largest avoidable consumer of the
    compute budget (CLAUDE.md).
    """
    presented = read_refresh_cookie(request)
    if presented is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    ratelimit.enforce(session, request, ratelimit.REFRESH)

    try:
        issued = refresh.rotate(session, presented)
    except refresh.RefreshRejectedError:
        # `rotate` may have revoked an entire family on the reuse path. That revocation
        # is a WRITE and it has to be committed before the 401 goes out — rolling it back
        # would leave the stolen chain live, which is the whole point of detecting reuse.
        session.commit()
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
        ) from None

    session.commit()
    set_refresh_cookie(response, issued.token)
    return _token_response(issued.user_id, "user")


@router.post("/logout")
def logout(request: Request, response: Response, session: DbSession) -> LogoutResponse:
    """Revoke the presented refresh family and clear the cookie.

    Idempotent, and never an error: no cookie, an expired cookie or a forged one all
    return the same success. A logout that could fail would be a way to probe which
    tokens are real, and a client stuck unable to log out is worse than useless.
    """
    presented = read_refresh_cookie(request)
    if presented is not None:
        refresh.revoke_presented(session, presented)
        session.commit()
    clear_refresh_cookie(response)
    return LogoutResponse()


@router.post("/demo")
def demo() -> TokenResponse:
    """Issue a 1-hour, read-only token for the seeded demo account. **Issues ZERO SQL.**

    ## The empty signature is the security control

    Note what is *not* a parameter: there is no `Session`, no `Request`, nothing that can
    reach the database. That is deliberate and structural — zero-DB holds **by
    construction**, not by a test or a convention, and reintroducing a query means adding
    a dependency back to this line, which is a visible diff a reviewer will stop on.
    Do not "just look up the demo user", do not cache or memoise a lookup: the handler
    must remain unable to query. `DEMO_USER_ID` is pinned in `server/seed.py` precisely so
    the token's `sub` needs no lookup.

    ## Why, with the arithmetic

    Neon Free is 100 CU-hr/month at the 0.25 CU floor = **400 awake-hours** in a 730-hour
    month, and autosuspend is fixed at 5 minutes (not configurable on Free). A bot
    trickling **one request per minute** at a DB-touching public endpoint therefore keeps
    the compute awake 100% of the time, costs ~182 CU-hr/month and busts the whole
    allowance by itself — while staying inside any rate limit we are able to configure.
    The old Postgres rate limit could not stop that, because enforcing it was itself a
    write. So the query is gone instead, and the rate limit moved to a **Vercel WAF rule
    on `/api/auth/*`**. Unlimited minting now costs invocations and CPU, and zero Neon
    time, which is what makes it an acceptable worst case.

    ## Consequence: the 503 is gone, and that is on purpose

    This used to return 503 when the seed had not run. It cannot detect that any more, so
    **demo mode always issues a token** — against an unseeded database the user simply
    sees empty data. That is the better failure: the endpoint stays up, and an empty demo
    is a visibly wrong deployment rather than a broken one. Nobody should have to discover
    it, hence this paragraph.
    """
    return _token_response(DEMO_USER_ID, "demo")


@router.get("/me")
def me(principal: CurrentUser) -> MeResponse:
    """The authenticated principal, straight from the verified token.

    **Touches no database at all.** Two reasons, both in CLAUDE.md: access-token
    verification is stateless precisely so an authenticated request does not wake Neon,
    and there must be no `last_seen` / `last_used_at` column — a write-per-read is the
    classic accident that defeats every other compute rule here. Profile data (email,
    target grade, settings) belongs to the profile endpoint in a later PR, where reading
    it is the point of the request.
    """
    return MeResponse(user_id=principal.user_id, scope=principal.scope)
