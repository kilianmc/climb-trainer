"""Guards the routing contract that spike S0 established.

These assertions look trivial but each one encodes a failure that actually happened
or was a live risk during the spike.
"""

from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app, base_url="https://climb.kilianmc.com")


def test_health_returns_json() -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_unmatched_api_path_is_a_json_404_not_spa_html() -> None:
    """The headline S0 acceptance criterion.

    If the SPA rewrite ever swallows /api/*, this returns 200 text/html instead —
    and `res.ok` is true while `res.json()` throws, which is the worst possible
    failure to debug from the client side.
    """
    res = client.get("/api/definitely-not-a-route")
    assert res.status_code == 404
    assert "application/json" in res.headers["content-type"]


def test_cors_allowlist_never_accepts_a_wildcard() -> None:
    from server.settings import Settings

    try:
        Settings(cors_origins=["*"])
    except RuntimeError:
        return
    raise AssertionError("Settings must reject '*' in cors_origins at startup")
