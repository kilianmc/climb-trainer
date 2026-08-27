"""Login's two rate-limit dimensions.

The per-IP bucket alone is weak: an attacker with a hundred addresses gets a hundred fresh
budgets. `LOGIN_ACCOUNT` keys on the attempted email instead, so the limit binds to the
*target*. Three properties make that worth having and safe to have — it trips independently of
the IP bucket, it is not an account-existence oracle, and it costs no extra round trip. The
single-statement test guards a design decision that is invisible from behaviour.

**Skips without `DATABASE_URL`** (`conftest.py`); CI runs them for real.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from server.auth import ratelimit
from server.models import RateLimit

_PASSWORD = "a-long-enough-passphrase"
_KNOWN = "resident@example.com"
_UNKNOWN = "ghost@example.com"


def _login(client: TestClient, email: str, ip: str) -> Any:
    """One login attempt from a stated client address.

    `x-forwarded-for` is what `ratelimit.client_ip` reads. On Vercel the platform sets
    that header and a client cannot; here it is the only way to simulate distinct
    sources, and it is exactly why the local limiter is bypassable in development.
    """
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": _PASSWORD},
        headers={"x-forwarded-for": ip},
    )


def _preload_bucket(session: Session, rule: ratelimit.Rule, subject: str, count: int) -> None:
    """Put a bucket one request away from its limit, without making that many requests.

    Uses the module's own key and window helpers, so a change to either is caught here
    rather than producing a test that silently stops exercising the limit.
    """
    session.execute(
        insert(RateLimit).values(
            bucket=ratelimit.bucket_key(rule, subject),
            window_start=ratelimit.window_start_for(rule, datetime.now(UTC)),
            count=count,
        )
    )
    session.commit()


def test_the_per_ip_bucket_trips_at_its_threshold(api_client: TestClient, invite_code: str) -> None:
    """The counter has to survive the endpoint's own transaction, or it never trips.

    `REGISTER` (3/hour) is the bucket used here because it is the tightest IP-keyed rule
    and each attempt is a real expense — an argon2 hash plus a row. Requests 1-3 create
    accounts; the fourth is refused before any hashing happens.
    """
    for attempt in range(ratelimit.REGISTER.limit):
        response = api_client.post(
            "/api/auth/register",
            json={
                "email": f"newcomer{attempt}@example.com",
                "password": _PASSWORD,
                "invite_code": invite_code,
            },
        )
        assert response.status_code == 201, f"attempt {attempt + 1}: {response.text}"

    blocked = api_client.post(
        "/api/auth/register",
        json={
            "email": "one-too-many@example.com",
            "password": _PASSWORD,
            "invite_code": invite_code,
        },
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_the_per_email_bucket_trips_even_though_every_request_has_a_different_ip(
    api_client: TestClient,
) -> None:
    """The whole point of the account-keyed rule: rotating source addresses does not help.

    Each attempt comes from a unique address, so the per-IP `LOGIN` bucket (10 per 15 min)
    never reaches its limit — every one of these sits at a count of 1. Only the
    account-keyed bucket accumulates.
    """
    for attempt in range(ratelimit.LOGIN_ACCOUNT.limit):
        response = _login(api_client, _UNKNOWN, f"203.0.113.{attempt}")
        assert response.status_code == 401, f"attempt {attempt + 1}: {response.text}"

    blocked = _login(api_client, _UNKNOWN, "198.51.100.7")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_the_429_is_identical_for_an_existing_and_a_nonexistent_address(
    api_client: TestClient, db_session: Session, invite_code: str
) -> None:
    """The account-keyed limit must not become an account-existence oracle.

    The email counter increments for **any** address attempted, so an address that has
    never been registered exhausts its bucket exactly like a real one — and the rejection
    is byte-identical. If `enforce_all` ever skipped the count for unknown addresses, or
    named the bucket that tripped, this would fail.
    """
    registered = api_client.post(
        "/api/auth/register",
        json={"email": _KNOWN, "password": _PASSWORD, "invite_code": invite_code},
    )
    assert registered.status_code == 201

    for email in (_KNOWN, _UNKNOWN):
        _preload_bucket(db_session, ratelimit.LOGIN_ACCOUNT, email, ratelimit.LOGIN_ACCOUNT.limit)

    known = _login(api_client, _KNOWN, "203.0.113.10")
    unknown = _login(api_client, _UNKNOWN, "203.0.113.11")

    assert known.status_code == 429
    assert unknown.status_code == 429
    assert known.json() == unknown.json()
    # Header *names* rather than values: Retry-After is a countdown and the two requests
    # are a few milliseconds apart, so the values may legitimately differ by a second.
    assert sorted(known.headers) == sorted(unknown.headers)
    assert "retry-after" in known.headers


def test_login_counts_both_buckets_in_a_single_statement(
    api_client: TestClient, db_session: Session
) -> None:
    """Two dimensions for the cost of one round trip — the reason `enforce_all` exists.

    Not a restatement of the implementation: the whole justification for adding an
    account-keyed limit was that it costs no extra latency and no extra Neon wake-up. If
    someone later "simplifies" it into two `enforce()` calls that property is gone, and
    nothing about the observable behaviour would change.
    """
    captured: list[tuple[str, Any]] = []

    def _record(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        captured.append((statement, parameters))

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", _record)
    try:
        assert _login(api_client, _UNKNOWN, "203.0.113.20").status_code == 401
    finally:
        event.remove(bind, "before_cursor_execute", _record)

    writes = [
        (statement, parameters)
        for statement, parameters in captured
        if "rate_limit" in statement and statement.lstrip().upper().startswith("INSERT")
    ]
    assert len(writes) == 1, (
        f"login must count all of its buckets in ONE statement, saw {len(writes)}: "
        f"{[statement for statement, _ in writes]}"
    )

    _, parameters = writes[0]
    buckets = {value for key, value in dict(parameters).items() if "bucket" in key}
    assert len(buckets) == 2, f"expected the IP and account buckets in one statement: {buckets}"
