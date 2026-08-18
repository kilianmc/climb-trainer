"""The `/api/*` security headers, asserted against real responses.

A header set can stop being sent without anything failing, which is why the testing
policy in CLAUDE.md earns this a file. `vercel.json` is deliberately not asserted here —
that would restate config; it is verified on the real deploy and mirrored into
`vite preview`.

Error responses matter as much as the happy path: an ordering mistake shows up on a 401
or a 404, not on a 200.
"""

import pytest
from fastapi.testclient import TestClient

from server.app import _CSP_EXEMPT_PATHS, app
from server.security_headers import API_CSP, PERMISSIONS_POLICY
from server.settings import get_settings

client = TestClient(app, base_url="https://climb.kilianmc.com", raise_server_exceptions=False)

# Every header the middleware is responsible for, with the exact value expected.
_EXPECTED = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": PERMISSIONS_POLICY,
    "content-security-policy": API_CSP,
}

_CORS_ORIGINS = get_settings().cors_origins


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("GET", "/api/health", 200),
        # Responses no endpoint produced: a 401 from the auth gate, FastAPI's own JSON
        # 404, and a validation 422. These are the ones a misplaced middleware loses.
        ("GET", "/api/auth/me", 401),
        ("GET", "/api/definitely-not-a-route", 404),
        ("POST", "/api/auth/login", 422),
    ],
)
def test_every_header_is_set_on_success_and_on_errors(
    method: str, path: str, expected_status: int
) -> None:
    res = client.request(method, path)
    assert res.status_code == expected_status, (
        f"{method} {path} returned {res.status_code}, not {expected_status} — this test's "
        f"premise (that it exercises that response path) no longer holds."
    )
    wrong = [
        f"  {name}: expected {expected!r}, got {res.headers.get(name)!r}"
        for name, expected in _EXPECTED.items()
        if res.headers.get(name) != expected
    ]
    assert not wrong, (
        f"{method} {path} -> {res.status_code} did not carry the expected security "
        f"headers:\n" + "\n".join(wrong)
    )


def test_the_csp_permits_nothing_dangerous() -> None:
    """`unsafe-eval` and a bare `*` are how a CSP becomes decorative."""
    assert "unsafe-eval" not in API_CSP
    assert "unsafe-inline" not in API_CSP
    assert "*" not in API_CSP
    assert "default-src 'none'" in API_CSP
    assert "frame-ancestors 'none'" in API_CSP


def test_permissions_policy_does_not_deny_the_features_the_player_needs() -> None:
    """Unlisted means default, not denied — only list what you mean to restrict.

    The session player owns a "Keep screen on" toggle and plays audio cues full-screen, so
    denying these here would break it. This guards against a well-meant "deny everything
    we are not using" change.
    """
    assert "screen-wake-lock" not in PERMISSIONS_POLICY
    assert "fullscreen" not in PERMISSIONS_POLICY
    assert "autoplay" not in PERMISSIONS_POLICY
    assert "camera=()" in PERMISSIONS_POLICY
    assert "geolocation=()" in PERMISSIONS_POLICY


def test_docs_routes_are_exempt_from_the_csp_but_keep_the_other_headers() -> None:
    """Swagger UI loads its assets from a CDN, which `default-src 'none'` would block.

    The exemption must stay derived from the configured docs URLs rather than hardcoded,
    so it empties itself when production turns the docs off.
    """
    assert _CSP_EXEMPT_PATHS == {p for p in (app.docs_url, app.openapi_url) if p is not None}, (
        "the CSP exemption must be derived from app.docs_url / app.openapi_url"
    )
    assert app.docs_url is not None  # docs are on outside production

    res = client.get(app.docs_url)
    assert res.status_code == 200
    assert "content-security-policy" not in res.headers
    # The exemption covers the CSP and nothing else.
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"


@pytest.mark.skipif(
    not _CORS_ORIGINS,
    reason="CORS_ORIGINS is unset, so CORSMiddleware is not installed. Both "
    "`npm run check:server` and CI set it.",
)
def test_cors_is_undisturbed_by_the_outer_headers_middleware() -> None:
    """An allowed origin is echoed with `Vary: Origin`; an unknown origin gets no ACAO.

    The headers middleware sits outside CORSMiddleware, so it could shadow it. The
    preflight is checked too — CORS short-circuits it without reaching a route.
    """
    allowed = _CORS_ORIGINS[0]

    res = client.get("/api/health", headers={"Origin": allowed})
    assert res.headers["access-control-allow-origin"] == allowed
    assert "origin" in res.headers.get("vary", "").lower()

    preflight = client.options(
        "/api/auth/login",
        headers={
            "Origin": allowed,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == allowed
    # Outermost placement means even the preflight carries the header set.
    assert preflight.headers["x-content-type-options"] == "nosniff"

    unknown = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in unknown.headers
    # Still defended, even for an origin we refuse to talk to.
    assert unknown.headers["content-security-policy"] == API_CSP
