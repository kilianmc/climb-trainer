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
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.auth import invites, ratelimit, refresh
from server.auth.cookies import (
    clear_refresh_cookie,
    clear_refresh_cookie_header,
    read_refresh_cookie,
    set_refresh_cookie,
)
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

# The 409 body for a refresh that lost a concurrent rotation. The client matches on the
# STATUS, not on this string — it is here for a human reading a failed request.
_SUPERSEDED_REFRESH_DETAIL: Final = "Refresh token superseded. Retry with the current cookie."

# 254 is the RFC 5321 maximum and matches `app_user.email`.
_MAX_EMAIL_LENGTH: Final = 254

# A length floor and nothing else. NIST dropped composition rules (a digit, a symbol,
# mixed case) years ago: they push users towards `Password1!`, which is both weaker and
# more annoying than a long passphrase. 128 is an upper bound because argon2 hashes the
# whole input and an unbounded field is a cheap way to burn CPU.
#
# PUBLIC, and imported by `server/devseed.py` and `server/admin.py`: both write a
# `password_hash` directly, and a password outside this range would create an account the
# app's own policy could never recreate or reset. One definition, not three.
MIN_PASSWORD_LENGTH: Final = 12
MAX_PASSWORD_LENGTH: Final = 128

# The whole of what a caller learns about a rejected invite. Unknown, expired, revoked and
# exhausted all land here — see `server/auth/invites.py` for why telling them apart is an
# oracle. **400, not 403**: 403 already means "demo mode is read-only" on every auth route
# (`enforce_auth`), so reusing it would leave the client unable to write correct copy for
# either. 422 is Pydantic's and means "the shape is wrong", which this is not.
#
# The second sentence is load-bearing, not padding. The commonest way to see this message is
# not an attack: it is somebody re-entering the single-use code they already registered with,
# or retrying after a lost response. "Not valid" alone sends that person off to ask for a new
# code they do not need, and the invite check runs BEFORE the email lookup precisely so a
# stranger cannot be told the account exists — so the copy has to carry the way out instead.
# It must stay ONE message: nothing here may hint at which of the four causes applied.
_INVITE_REJECTED: Final = (
    "That invite code is not valid or has already been used. If you already have an "
    "account, log in instead."
)


def normalise_email(value: str) -> str:
    """Lowercase and strip. `app_user.email` has no `citext`, so this is the invariant.

    Every write and every lookup goes through here. If one path skips it, two accounts
    differing only in case become possible and the unique constraint stops meaning what
    it appears to mean.
    """
    return value.strip().lower()


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[EmailStr, Field(max_length=_MAX_EMAIL_LENGTH)]
    password: Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]
    # Bounded, stripped, and with NO minimum beyond non-empty: a too-short code must get
    # the same answer as a wrong one, so nothing about a code's shape is decided here.
    # Stripping is for the person pasting a code out of a message with a trailing space;
    # the value is case-sensitive base64url and is never lowercased.
    invite_code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=invites.MAX_CODE_LENGTH),
    ]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Bounded, but with no minimum: enforcing the registration floor here would tell an
    # attacker the password policy from a 422, and would reject legitimate users whose
    # password predates a future policy change.
    email: Annotated[EmailStr, Field(max_length=_MAX_EMAIL_LENGTH)]
    password: Annotated[str, Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)]


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

    **Invite-gated since issue #35.** A valid, unexpired, unrevoked, not-exhausted code is
    required, and spending it happens in this handler's transaction so that a registration
    which fails afterwards does not burn a use. The invite's id is recorded on the account,
    so a use is attributable to a person and not merely to a counter.
    """
    ratelimit.enforce(session, request, ratelimit.REGISTER)

    # Checked BEFORE the email lookup, deliberately. The 409 below is an account-existence
    # oracle that this route accepts for the reason in the docstring — but there is no
    # reason to hand it to a caller who has not shown they were invited at all.
    #
    # It stays in the SAME transaction as the insert below: `consume` flushes and does not
    # commit, so every failure path from here on rolls the increment back with everything
    # else and a failed registration cannot burn a use. See `server/auth/invites.py`.
    try:
        invite = invites.consume(session, payload.invite_code)
    except invites.InviteRejectedError:
        # ONE status and ONE message for unknown / expired / revoked / exhausted. Nothing
        # was written on any of those paths, so there is nothing to roll back here.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_INVITE_REJECTED
        ) from None

    email = normalise_email(payload.email)
    if session.scalar(select(AppUser.id).where(AppUser.email == email)) is not None:
        # ⚠️ ROLLBACK, then raise — the invite was consumed a few lines up and this path must
        # not leave that increment behind. `get_session` closing the session would roll it
        # back anyway, but relying on teardown for a security property is not something a
        # reader can see, a test can observe, or a future refactor will preserve. The
        # `IntegrityError` path below does the same thing, for the same reason.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email is already registered."
        )

    # Explicit assignment, never `AppUser(**payload.model_dump())` — `is_demo` is set
    # here and must not be settable by the request.
    user = AppUser(
        email=email,
        password_hash=hash_password(payload.password),
        is_demo=False,
        # Attribution. Taken from the row `consume` locked, never from the request.
        invite_id=invite.id,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        # Lost the race against a concurrent registration of the same address. The
        # SELECT above is the friendly path; the unique constraint is the correct one. The
        # rollback also returns the invite use this request had already spent.
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
    email = normalise_email(payload.email)

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

    **409** means the cookie presented was rotated seconds ago by another mount or tab and
    the client should simply send it again; **401** means there is no usable family left.
    Documented here rather than in a `responses=` block because no route in this module
    declares one — `register`'s 409 and `login`'s 401 are described the same way, and
    `/openapi.json` is off in production anyway.
    """
    presented = read_refresh_cookie(request)
    if presented is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    ratelimit.enforce(session, request, ratelimit.REFRESH)

    try:
        issued = refresh.rotate(session, presented)
    except refresh.RefreshSupersededError:
        # 409, deliberately NOT 401. A 401 says "your credentials are gone", and here the
        # opposite is true: the credentials are fine and NEWER than what this request sent.
        # The correct client reaction is to retry, which a 401 would never prompt.
        #
        # ⚠️ DO NOT clear the refresh cookie here. It is shared with the mount that just
        # won the rotation — it holds that mount's brand-new token — so clearing it would
        # destroy a live credential and recreate the very bug this path exists to fix, from
        # the other end. The 401 path below now clears it through
        # `HTTPException(headers=...)`, which is the mechanism that actually reaches a
        # browser, so this path's silence is a real difference and not an accident of how
        # the header is written. `test_auth_refresh.py` asserts both directions.
        #
        # The commit is not protecting a write of `rotate`'s: the grace path writes nothing,
        # and `ratelimit.enforce` above already committed its own upsert (`enforce_all`:
        # "This commits."). It ends the transaction, releasing the `FOR UPDATE` lock on the
        # presented row before the client's retry arrives to take it.
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_SUPERSEDED_REFRESH_DETAIL
        ) from None
    except refresh.RefreshRejectedError:
        # `rotate` may have revoked an entire family on the reuse path. That revocation
        # is a WRITE and it has to be committed before the 401 goes out — rolling it back
        # would leave the stolen chain live, which is the whole point of detecting reuse.
        session.commit()
        # The cookie is dead, so clearing it is what makes the NEXT request free: without
        # the `Set-Cookie`, `read_refresh_cookie` keeps returning a value, the
        # `presented is None` short-circuit above is never taken, and every later 401 pays a
        # `ratelimit.enforce` upsert — one Postgres write and one restarted five-minute Neon
        # window each, until the 30/hour bucket 429s. It goes through the exception's headers
        # because a cookie written onto `response` is discarded on a raising path; see
        # `cookies.clear_refresh_cookie_header`.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"set-cookie": clear_refresh_cookie_header()},
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
