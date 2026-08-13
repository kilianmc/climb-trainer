"""Deny-by-default, proved by walking the route table rather than trusting a review.

CLAUDE.md: *"Authentication is required unless a route appears on an explicitly
enumerated public-route list. A test walks every registered route and asserts each one
is either on that list or protected."* This is that test, plus its demo-mode twin, which
is the named acceptance criterion for PR #3.

The value of these is entirely in what they catch **later**: an endpoint added in PR #9
that nobody remembered to protect, or a mutating route that a demo token can reach. Both
would pass every test written about the feature itself. Per the testing policy in
CLAUDE.md, this is the "project-wide invariant that silently rots" bullet.

**No database, on purpose — and enforced, not merely hoped for.** Every assertion here
is about a rejection that happens in a dependency, before any handler runs, so this file
must run in the local gate whether or not `DATABASE_URL` is set. The autouse fixture
below replaces `get_session` with one that raises, which does two things: it keeps a
developer's real Neon database out of a test that walks *every* endpoint firing
requests at it, and it makes "this route reached its handler" show up as a 500 rather
than as a quiet, successful write. Server exceptions are converted to 500 responses so
one such route cannot abort the walk before it reaches the rest.
"""

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.app import app
from server.auth.deps import DEMO_WRITE_EXEMPT_ROUTES, MUTATING_METHODS, PUBLIC_ROUTES
from server.auth.tokens import issue_access_token
from server.db import get_session

_PATH_PARAM = re.compile(r"\{[^}]+\}")

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

    HEAD and OPTIONS are dropped: Starlette synthesises HEAD from GET and the CORS
    middleware owns OPTIONS, so neither is a route anyone declared.
    """
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not isinstance(path, str) or not methods:
            continue
        routes.extend(
            (method, path) for method in sorted(methods) if method not in {"HEAD", "OPTIONS"}
        )
    return routes


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
