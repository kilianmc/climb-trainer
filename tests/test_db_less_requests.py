"""What the API must still do with NO database configured.
Its own file because `test_auth_flow.py`'s fixtures skip without `DATABASE_URL` and this needs the
exact opposite condition. The bug it records: resolving the `DbSession` dependency used to build
the engine, which happens BEFORE FastAPI validates the body — so a malformed body 500'd instead of
422 whenever `DATABASE_URL` was unset, and `npm run check` was red on a fresh clone, against the
promise that the local gate passes with no database.
CI and the development machine both DO have `DATABASE_URL`, so the test forces the no-database
condition itself and restores the caches afterwards; without that it passes vacuously and leaves a
poisoned engine behind for the rest of the session.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.db import get_engine, get_sessionmaker
from server.settings import POOLED_URL_ENV


@pytest.fixture
def no_database_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def clear_caches() -> None:
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()

    monkeypatch.delenv(POOLED_URL_ENV, raising=False)
    clear_caches()
    yield
    clear_caches()


def test_an_invalid_body_is_a_422_even_with_no_database_url(
    no_database_configured: None,
) -> None:
    client = TestClient(app, base_url="https://climb.kilianmc.com", raise_server_exceptions=False)
    response = client.post("/api/auth/login")

    assert response.status_code == 422, (
        f"expected a validation 422, got {response.status_code} — resolving the session "
        f"dependency must not require configuration, or a malformed body 500s."
    )
