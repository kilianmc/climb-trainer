"""Deny-by-default, proved by walking the route table rather than trusting a review.
CLAUDE.md: authentication is required unless a route appears on an explicitly enumerated
public-route list, and a test walks every registered route. This is that test plus its demo-mode
twin. The value is entirely in what they catch **later** — an endpoint nobody remembered to
protect, or a mutating route a demo token can reach, both of which pass every test written about
the feature itself.
**No database, and enforced rather than hoped for**: every assertion is about a rejection that
happens in a dependency before any handler runs, so the autouse fixture replaces `get_session`
with one that raises. That keeps a real Neon database out of a test that fires requests at
*every* endpoint, and makes "this route reached its handler" a 500 rather than a quiet write.
"""

import re
from collections.abc import Iterator

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.app import app
from server.auth.deps import DEMO_WRITE_EXEMPT_ROUTES, MUTATING_METHODS, PUBLIC_ROUTES
from server.auth.tokens import issue_access_token
from server.db import get_session

_PATH_PARAM = re.compile(r"\{[^}]+\}")

# A route that exists today, is NOT public, and is reached through `include_router`.
# `test_the_walk_actually_sees_routes_behind_include_router` asserts the walk finds it —
# see that test for the incident it guards.
_CANARY_PROTECTED_ROUTE = ("GET", "/api/auth/me")

client = TestClient(
    app,
    base_url="https://climb.kilianmc.com",
    raise_server_exceptions=False,
)


@pytest.fixture(autouse=True)
def _no_database() -> Iterator[None]:
    def _refuse() -> Iterator[Session]:
        raise AssertionError(
            "a route in the enumeration walk reached its handler and asked for a "
            "database session; these tests must be decided by dependencies alone"
        )

    app.dependency_overrides[get_session] = _refuse
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _registered_routes() -> list[tuple[str, str]]:
    """Every `(method, path)` the application actually serves.

    **Must go through `iter_route_contexts`, not `app.routes`.** Since FastAPI 0.137,
    `include_router` stores an intermediate node instead of copying routes onto the
    parent, so `app.routes` is a tree and iterating it directly returns one opaque object
    in place of every router-mounted endpoint. `iter_route_contexts` flattens it and
    yields the effective path, with the router prefix applied.

    HEAD and OPTIONS are dropped: Starlette synthesises HEAD from GET and the CORS
    middleware owns OPTIONS, so neither is a route anyone declared.
    """
    routes: list[tuple[str, str]] = []
    for route in iter_route_contexts(app.routes):
        path = route.path
        methods = route.methods
        if not isinstance(path, str) or not methods:
            continue
        routes.extend(
            (method, path) for method in sorted(methods) if method not in {"HEAD", "OPTIONS"}
        )
    return routes


def test_the_walk_actually_sees_routes_behind_include_router() -> None:
    """A floor under the other tests here: an empty walk must fail, not pass vacuously.

    Every assertion below is decided by the route table, so they all succeed trivially if
    `_registered_routes()` stops finding routes. A change that hid only the *protected*
    routes would break nothing else in this file.
    """
    registered = set(_registered_routes())
    assert _CANARY_PROTECTED_ROUTE in registered, (
        f"{_CANARY_PROTECTED_ROUTE} is registered by server/auth/routes.py but the walk "
        f"did not find it, so the other tests here are passing vacuously. Found: "
        f"{sorted(registered)}. Fix `_registered_routes()` — do not update this canary."
    )
    assert _CANARY_PROTECTED_ROUTE not in PUBLIC_ROUTES, (
        f"{_CANARY_PROTECTED_ROUTE} is now public, so it no longer canaries the protected "
        f"half of the walk. Point this at another protected route."
    )


def _requestable(path: str) -> str:
    """Fill in path parameters so the request reaches the route it is aimed at."""
    return _PATH_PARAM.sub("1", path)


def test_every_route_is_public_by_declaration_or_rejects_anonymous_requests() -> None:
    """A route that is neither listed nor protected is the bug this test exists to find."""
    offenders: list[str] = []
    for method, path in _registered_routes():
        if (method, path) in PUBLIC_ROUTES:
            continue
        status_code = client.request(method, _requestable(path)).status_code
        if status_code != 401:
            offenders.append(f"  {method} {path} -> {status_code}")
    assert not offenders, (
        "these routes answered an UNAUTHENTICATED request with something other than 401 "
        "and are not in PUBLIC_ROUTES:\n"
        + "\n".join(offenders)
        + "\n\nEither protect the route, or add it to PUBLIC_ROUTES in "
        "server/auth/deps.py with a comment saying why it is public."
    )


def test_public_route_list_has_no_entries_for_routes_that_do_not_exist() -> None:
    """A stale or typo'd entry silently protects the route it was meant to open.

    The failure is confusing when it happens (the endpoint 401s and the list "clearly"
    says it is public), so catch it here where the message can say so.
    """
    stale = sorted(PUBLIC_ROUTES - set(_registered_routes()))
    assert not stale, (
        f"PUBLIC_ROUTES names routes that are not registered: {stale}. "
        f"A typo here does not fail open — it leaves the real route protected."
    )


def test_every_mutating_route_forbids_a_demo_token() -> None:
    """The PR #3 acceptance criterion: demo mode cannot write, anywhere.

    `POST /api/auth/demo` is the single enumerated exception — it is the endpoint that
    issues the token, so a client that already has one must still be able to call it.
    """
    # Any user id will do: the ban is decided from the token's scope, and nothing gets
    # far enough to look the account up. Minted inside the test because the AUTH_SECRET
    # fixture has not run at collection time.
    headers = {"Authorization": f"Bearer {issue_access_token(1, 'demo').token}"}
    offenders: list[str] = []
    for method, path in _registered_routes():
        if method not in MUTATING_METHODS:
            continue
        status_code = client.request(method, _requestable(path), headers=headers).status_code
        if (method, path) in DEMO_WRITE_EXEMPT_ROUTES:
            assert status_code != 403, f"{method} {path} is exempt but was still forbidden"
            continue
        if status_code != 403:
            offenders.append(f"  {method} {path} -> {status_code}")
    assert not offenders, (
        "a demo-scope token was NOT rejected with 403 on these mutating routes:\n"
        + "\n".join(offenders)
        + "\n\nDemo mode is read-only (CLAUDE.md). If a route genuinely must accept a "
        "demo write, add it to DEMO_WRITE_EXEMPT_ROUTES and justify it in the diff."
    )
