"""Deny-by-default authentication, demo read-only enforcement, and the request session.

## Why this is a single GLOBAL dependency

`enforce_auth` is registered once, on the application
(`FastAPI(dependencies=[Depends(enforce_auth)])`), and therefore runs for **every**
route FastAPI serves. The alternative — a dependency per router, or a decorator per
endpoint — **fails open**: the failure mode of forgetting it is an unprotected endpoint
that behaves perfectly in every test anyone thought to write. CLAUDE.md states the rule
directly: authentication is required unless a route appears on an explicitly enumerated
public list, and a test walks every registered route to prove it.

So the only way to make a route public is to add it to `PUBLIC_ROUTES` below, in a diff,
where a reviewer sees it. An unmatched or unrecognised route is **not** public.

## Where a user id may come from

`Principal.user_id`, taken from the verified token. Nowhere else. **Every query is
scoped by `user_id` from the token, never from a client-supplied id, path parameter or
body field** — IDOR is the realistic extraction risk in this product: a single unscoped
`WHERE id = :id` hands over every user's training history. That is why the `CurrentUser`
dependency exposes the principal and there is deliberately no dependency, helper or
Pydantic field anywhere that reads a user id out of a request.

## Demo mode, enforced twice

1. **Here** — a `demo`-scope token on any mutating method gets a 403 before the handler
   runs. The only exception is `POST /api/auth/demo` itself, enumerated below.
2. **In the database** — `get_request_session` issues `SET LOCAL transaction_read_only`
   for a demo principal, so even a handler that ignores rule 1 cannot write.

Two layers because the first is a policy that a future refactor could route around, and
the second is the database refusing. CLAUDE.md asks for both.

Note for PR #6 (the auth UI): because the demo ban covers *every* mutating route, a
client that is in demo mode must **drop its demo token before calling
`/api/auth/login` or `/api/auth/register`**, or those calls will 403. That is the
intended contract — a demo token has no business being attached to a real login.
"""

from collections.abc import Iterator
from typing import Annotated, Final

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.auth.tokens import InvalidAccessTokenError, Principal, decode_access_token
from server.db import get_session

# (method, path) pairs that do NOT require authentication. `path` is the route's
# registered template, exactly as FastAPI stores it — not the requested URL.
#
# Adding a line here is the only way to make an endpoint public, and it is the line a
# reviewer should stop on. `tests/test_auth_routes_enumerated.py` fails if any other
# route answers an unauthenticated request with anything but 401.
PUBLIC_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        # Liveness. Deliberately touches no database — see server/db.py.
        ("GET", "/api/health"),
        # The auth endpoints themselves: you cannot present a token to get one.
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/login"),
        # Authenticated by the refresh cookie, not by a Bearer token.
        ("POST", "/api/auth/refresh"),
        # Idempotent and must work with an expired or absent session.
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/demo"),
        # Swagger and the schema. Listed for completeness of the enumeration test:
        # FastAPI registers these as plain Starlette routes, so application-level
        # dependencies never run for them anyway, and both are switched OFF entirely in
        # production (`_docs_enabled` in server/app.py) because an OpenAPI document is a
        # map of the attack surface.
        ("GET", "/api/docs"),
        ("GET", "/api/openapi.json"),
    }
)

MUTATING_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# The routes a demo token may POST to. Enumerated rather than pattern-matched, so widening
# it is a visible diff — and this list is deliberately tiny, because it is the one place
# "demo mode is read-only" can be undone. **A reviewer should stop on any addition here.**
#
# 1. `POST /api/auth/demo` mints the token, so a client that already holds one must still be
#    able to call it. It issues zero SQL.
# 2. `POST /api/plans/preview` **writes nothing**, and that is enforced three ways rather
#    than asserted:
#      - the generator is a pure module — no DB, no clock, no RNG — held pure by the ruff
#        `TID251` rule in `server/domain/.ruff.toml`, which bans `server.db`, `server.models`
#        and `sqlalchemy` inside `server/domain/`;
#      - the handler in `server/plans/routes.py` issues only `SELECT`s, and
#        `tests/test_plans_api.py` proves it behaviourally by counting `plan`, `mesocycle`
#        and `planned_session` rows after a successful preview;
#      - for a demo principal `get_request_session` below has already issued
#        `SET LOCAL transaction_read_only`, so **Postgres itself** would refuse a write.
#    It is a POST only because a per-user body on a cacheable verb is the `/api/library` CDN
#    trap; without this entry the demo mount 403s and the plan screen is dead there, which
#    is the one screen the portfolio exists to show.
DEMO_WRITE_EXEMPT_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {("POST", "/api/auth/demo"), ("POST", "/api/plans/preview")}
)

# A literal constant. There is no interpolation here and there must never be any — this
# is the one place in the codebase that passes a string to `text()`, and it passes a
# fixed one. Do not "parameterise" it; `SET LOCAL` takes no bind parameters anyway.
#
# `SET LOCAL`, never a bare `SET`: Neon's pooled endpoint is PgBouncer in transaction
# mode, where a session-level `SET` either leaks to the next borrower of the connection
# or is silently dropped. `SET LOCAL` is scoped to the transaction and works pooled.
_READ_ONLY_TRANSACTION: Final = text("SET LOCAL transaction_read_only = on")

# One message for every authentication failure. The client is never told whether the
# token was missing, expired, malformed or forged — that difference is only useful to
# someone probing.
_UNAUTHENTICATED = "Not authenticated."
_DEMO_READ_ONLY = "Demo mode is read-only."


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_UNAUTHENTICATED,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bearer_token(header: str | None) -> str | None:
    """Extract the credential from an `Authorization: Bearer <token>` header."""
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def enforce_auth(request: Request) -> None:
    """Application-wide gate. Runs before every endpoint and every route dependency.

    Reads the matched route from `request.scope["route"]` — routing has already happened
    by the time dependencies are solved, so this is the route template FastAPI actually
    selected, not a re-derived guess at one.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if not isinstance(path, str):
        # No matched route, or something that is not an HTTP route. Unreachable in
        # normal operation (an unmatched path 404s before dependencies run), and
        # treated as protected rather than public if it ever happens.
        raise _unauthenticated()

    # Starlette answers HEAD from the GET handler, so the public list stays keyed on GET.
    method = "GET" if request.method == "HEAD" else request.method
    is_public = (method, path) in PUBLIC_ROUTES

    principal: Principal | None = None
    token = _bearer_token(request.headers.get("authorization"))
    if token is not None:
        try:
            principal = decode_access_token(token)
        except InvalidAccessTokenError:
            # A bad token on a public route is simply ignored; on a protected one it is
            # indistinguishable from no token at all.
            if not is_public:
                raise _unauthenticated() from None

    # Recorded even when it is None, so `get_request_session` and `current_principal`
    # never have to re-parse the header (and can never disagree with this decision).
    request.state.principal = principal

    if (
        principal is not None
        and principal.scope == "demo"
        and method in MUTATING_METHODS
        and (method, path) not in DEMO_WRITE_EXEMPT_ROUTES
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_DEMO_READ_ONLY)

    if is_public:
        return

    if principal is None:
        raise _unauthenticated()


def current_principal(request: Request) -> Principal:
    """The authenticated principal, for handlers that need it.

    `enforce_auth` has already run and already rejected the unauthenticated case, so the
    `None` branch here is a wiring error (a handler asking for a principal on a route
    listed as public), not a client error.
    """
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise _unauthenticated()
    return principal


CurrentUser = Annotated[Principal, Depends(current_principal)]


def get_request_session(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Iterator[Session]:
    """`get_session`, plus the database-level half of demo read-only enforcement.

    Wrapping rather than editing `server/db.py` keeps the dependency arrow pointing one
    way: `db.py` stays importable by Alembic and the seed with no auth stack loaded.

    Executing `SET LOCAL` also opens the transaction, which is exactly what is wanted —
    the flag has to be in place before the handler's first statement. It lasts until the
    transaction ends, so a handler that commits mid-request drops it; nothing on the demo
    path commits, and the 403 in `enforce_auth` is the layer that covers the case where
    someone later writes one that does.
    """
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal) and principal.scope == "demo":
        session.execute(_READ_ONLY_TRANSACTION)
    yield session


RequestSession = Annotated[Session, Depends(get_request_session)]
