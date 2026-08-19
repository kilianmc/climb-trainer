"""Refresh rotation and reuse detection.

The single most important behaviour in `server/auth/refresh.py`, and the reason the
`auth_session` table stores a chain rather than one row per session: a replayed token
must take the **whole family** down, including the successor the legitimate client is
holding. Getting this subtly wrong — issuing a fresh token on a replay, or revoking only
the presented row — leaves a thief with an indefinitely renewable session, and nothing
else in the suite would notice.

The other half of the story since issue #27 is the **replay grace window**: a replay that
arrives within `REPLAY_GRACE` of the rotation it lost is a lost race between the two mounts
sharing one cookie, not a theft, so it is answered with a 409 and **no write at all**.

All four clauses of that condition are guarded here — rotated, not revoked, inside the
window, not expired — plus the **magnitude** of the window itself, which the clause tests
cannot see because they backdate relative to the constant. Widening any of them widens the
window in which a real theft goes undetected, which is a security regression no other test
in the suite would notice.

**No `datetime.now()` anywhere in this module, deliberately.** Every timestamp it writes and
every timestamp it compares comes from the **database** clock, through `_db_now` — because
that is the clock `rotate()` uses, and mixing the two turned a boundary assertion into a race
against the test's own runtime. See `_db_now` and `_backdate_rotation`.

**Skips without `DATABASE_URL`** (see `conftest.py`). CI runs them for real.
"""

import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from server.auth import refresh
from server.auth.cookies import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    clear_refresh_cookie_header,
)
from server.db import get_sessionmaker, session_scope
from server.models import AppUser, AuthSession

_HOST = "climb.kilianmc.com"
_COOKIE_PATH = "/api/auth"


def _a_user(session: Session, email: str = "rotator@example.com") -> int:
    # `password_hash` is irrelevant here — nothing in this module verifies a password.
    user = AppUser(email=email, password_hash="unused-in-this-test", is_demo=False)
    session.add(user)
    session.flush()
    return user.id


def _family(session: Session, family_id: object) -> list[AuthSession]:
    return list(
        session.scalars(select(AuthSession).where(AuthSession.family_id == family_id)).all()
    )


def _row(session: Session, token: str) -> AuthSession:
    return session.scalars(
        select(AuthSession).where(AuthSession.token_hash == refresh.digest(token))
    ).one()


def _db_now(session: Session) -> datetime:
    """`transaction_timestamp()` — the exact clock `rotate()` compares against.

    ⚠️ Under `db_session` this value is **frozen for the whole test**, and fixed when the
    fixture's transaction begins (in practice, at the first statement the test issues). The
    fixture opens one transaction that the session joins as a SAVEPOINT, so a handler's
    `commit()` is only a `RELEASE SAVEPOINT`, the outer transaction never ends — and Postgres
    `now()` is transaction-start time, not statement time. That is a property to exploit rather
    than to work around: every timestamp a test writes and every timestamp `rotate()` reads
    come from this one value, so the arithmetic below is exact rather than a race against the
    test's own runtime.
    """
    stamped: datetime | None = session.scalar(select(func.now()))
    # `scalar()` is typed as optional; `select now()` cannot return no row.
    assert stamped is not None
    return stamped


def _backdate_rotation(session: Session, token: str, age: timedelta) -> None:
    """Set a retired row's `rotated_at` to exactly `age` before the database clock.

    **Not `datetime.now(UTC)`, and that was a real flake.** `rotate()` compares against
    `transaction_timestamp()`, which under this fixture is fixed at the test's first SQL
    statement, while a Python clock keeps moving. Backdating by `REPLAY_GRACE + 1s` from a
    moving clock therefore left a measured age of `11s - elapsed`, so the reuse path was only
    reachable while the test had spent under a second — and two of the tests that need it
    call `register` first, which pays a full argon2 hash. One clock on both sides removes the
    budget entirely.
    """
    _row(session, token).rotated_at = _db_now(session) - age
    session.flush()


def _age_rotation(session: Session, token: str) -> None:
    """Push a rotation just OUTSIDE the grace window, so the next replay is read as theft."""
    _backdate_rotation(session, token, refresh.REPLAY_GRACE + timedelta(seconds=1))


def _sessions_snapshot(session: Session) -> list[tuple[object, ...]]:
    """Every `auth_session` row as plain tuples, re-read from the database.

    `expire_all()` first so the comparison sees the DATABASE and not the identity map. This
    is what makes the snapshot catch a **Core-level** write — `revoke_family` is an
    `update()` statement, so it never appears in `session.dirty` and a check on the ORM's
    pending state alone would miss precisely the write this test exists to forbid.
    """
    session.expire_all()
    return [
        (row.id, row.token_hash, row.rotated_at, row.revoked_at, row.expires_at)
        for row in session.scalars(select(AuthSession).order_by(AuthSession.id)).all()
    ]


def test_rotation_replaces_the_token_and_keeps_the_family(db_session: Session) -> None:
    user_id = _a_user(db_session)
    first = refresh.issue(db_session, user_id)

    second = refresh.rotate(db_session, first.token)

    assert second.token != first.token
    assert second.family_id == first.family_id, "a rotation must stay in the same chain"
    assert second.user_id == user_id

    retired = db_session.scalars(
        select(AuthSession).where(AuthSession.token_hash == refresh.digest(first.token))
    ).one()
    assert retired.rotated_at is not None
    assert retired.revoked_at is None


def test_replaying_a_rotated_token_revokes_the_entire_family(db_session: Session) -> None:
    """Reuse detection OUTSIDE the grace window. The successor must die with the replay.

    The aging is what makes this the theft case rather than the lost-race case below.
    """
    user_id = _a_user(db_session)
    first = refresh.issue(db_session, user_id)
    second = refresh.rotate(db_session, first.token)
    _age_rotation(db_session, first.token)

    with pytest.raises(refresh.RefreshRejectedError):
        refresh.rotate(db_session, first.token)

    rows = _family(db_session, first.family_id)
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows), (
        "reuse must revoke every token in the family, not just the one presented"
    )

    # The token the legitimate client is holding is now dead too. That is the intended
    # trade: we cannot tell the victim from the thief, so both are logged out.
    with pytest.raises(refresh.RefreshRejectedError):
        refresh.rotate(db_session, second.token)


def test_the_grace_window_stays_small() -> None:
    """The 10 seconds IS the security trade, so it gets an absolute ceiling of its own.

    Every behavioural test here backdates relative to `refresh.REPLAY_GRACE`, which is the
    right way round — they assert behaviour either side of the window and stay correct if the
    number is ever tuned. The cost is that none of them can see the number being **widened**:
    at a day, or at 29 days, all of them stay green while replay detection quietly stops
    working for a day. `expires_at` is 30 days out, so even absurd values never trip the
    expiry clause either. Hence a bound that is not derived from the constant it guards.

    Needs no database, so unlike its neighbours it runs in the local gate.
    """
    assert refresh.REPLAY_GRACE <= timedelta(seconds=30)


def test_the_clear_cookie_header_matches_the_cookie_it_deletes() -> None:
    """The raising paths clear the cookie through a header; it must delete the SAME cookie.

    **`Path` is the assertion that matters.** RFC 6265 §5.3 keys the cookie store on
    (name, domain, path), so a header rendered with a different path deletes nothing and the
    real cookie stays in the jar — a failure with no symptom on the server side at all.
    `HttpOnly` is checked as a cheap regression on the flags travelling together, not because
    a mismatch there would stop the deletion; it would not.

    Needs no database.
    """
    header = clear_refresh_cookie_header()

    assert header.startswith(f"{REFRESH_COOKIE_NAME}=")
    assert f"Path={REFRESH_COOKIE_PATH}" in header
    assert "Max-Age=0" in header, "a deletion needs a past expiry, or it sets a live cookie"
    assert "HttpOnly" in header


def test_a_replay_inside_the_grace_window_is_superseded_and_writes_nothing(
    db_session: Session,
) -> None:
    """The issue #27 fix: the loser of a concurrent rotation is told to retry, not killed.

    Two mounts on two origins share one cookie, so the loser presents a token that was
    rotated milliseconds ago. It must get `RefreshSupersededError` — and the call must
    write NOTHING, because the winner's successor is a live credential and the loser has
    no claim on the family's state.
    """
    user_id = _a_user(db_session)
    first = refresh.issue(db_session, user_id)
    second = refresh.rotate(db_session, first.token)
    before = _sessions_snapshot(db_session)

    with pytest.raises(refresh.RefreshSupersededError):
        refresh.rotate(db_session, first.token)

    assert not db_session.new and not db_session.dirty and not db_session.deleted, (
        "the grace path must not stage a single write"
    )
    assert _sessions_snapshot(db_session) == before, "the grace path wrote to auth_session"

    rows = _family(db_session, first.family_id)
    assert all(row.revoked_at is None for row in rows), "a lost race must not revoke the family"

    # The winner's token is untouched and still rotatable, which is the point of the fix.
    successor = _row(db_session, second.token)
    assert successor.rotated_at is None
    assert successor.revoked_at is None
    third = refresh.rotate(db_session, second.token)
    assert third.family_id == first.family_id


def test_a_replay_late_in_the_grace_window_is_still_superseded(db_session: Session) -> None:
    """The grace side of the boundary, measured at a NON-ZERO age.

    Worth having because its neighbour above cannot see the window at all: `rotate()` stamps
    `rotated_at` from the same frozen `transaction_timestamp()` the replay is then measured
    against, so that test observes an age of **exactly zero** and would pass with
    `REPLAY_GRACE = 0`. Backdating to one second inside the window is what makes an
    in-fixture test compare two genuinely different timestamps, and together with
    `_age_rotation`'s +1s on the other side it brackets the boundary to ±1 s.

    Deterministic despite looking like a timing test: both sides come from `_db_now`, which
    the fixture freezes, so this is arithmetic and not a race.
    """
    user_id = _a_user(db_session, "late@example.com")
    first = refresh.issue(db_session, user_id)
    refresh.rotate(db_session, first.token)
    _backdate_rotation(db_session, first.token, refresh.REPLAY_GRACE - timedelta(seconds=1))

    with pytest.raises(refresh.RefreshSupersededError):
        refresh.rotate(db_session, first.token)

    assert all(row.revoked_at is None for row in _family(db_session, first.family_id))


def test_a_revoked_row_is_never_graced_even_inside_the_window(db_session: Session) -> None:
    """The guard against widening the grace condition.

    `revoked_at` means a decision was already taken — a logout, or an earlier family
    revocation. Gracing it would resurrect a session someone deliberately ended, and it is
    the clause most likely to be dropped by a future edit "simplifying" the condition.
    """
    user_id = _a_user(db_session)
    first = refresh.issue(db_session, user_id)
    refresh.rotate(db_session, first.token)
    # Rotated milliseconds ago, so squarely inside the window — and then revoked.
    refresh.revoke_family(db_session, first.family_id)
    db_session.flush()

    with pytest.raises(refresh.RefreshRejectedError):
        refresh.rotate(db_session, first.token)

    rows = _family(db_session, first.family_id)
    assert all(row.revoked_at is not None for row in rows), "the family must stay revoked"


def test_a_rotated_row_whose_token_has_expired_is_not_graced(db_session: Session) -> None:
    """The fourth clause: `row.expires_at > db_now`.

    A rotation can land in the last seconds of a 30-day life, so "rotated moments ago" and
    "expired" are not mutually exclusive. Gracing that would tell the client to retry into a
    successor whose own life is over, turning a dead session into a 409/401 loop instead of a
    clean logout. Constructed directly, because reaching it by waiting is not an option.
    """
    user_id = _a_user(db_session, "expired@example.com")
    issued = refresh.issue(db_session, user_id)
    row = _row(db_session, issued.token)
    # Both stamps come from the database clock, so "one second inside the window" and
    # "expired a minute ago" are exact rather than relative to this process's clock.
    stamp = _db_now(db_session)
    row.rotated_at = stamp - timedelta(seconds=1)
    row.expires_at = stamp - timedelta(minutes=1)
    db_session.flush()

    with pytest.raises(refresh.RefreshRejectedError):
        refresh.rotate(db_session, issued.token)

    assert all(r.revoked_at is not None for r in _family(db_session, issued.family_id)), (
        "an expired replay takes the reuse path, so the family must be revoked"
    )


def test_a_superseded_replay_is_not_a_rejected_one(db_session: Session) -> None:
    """A SIBLING exception, not a subclass — the whole point of the hierarchy being flat.

    `routes.py` answers `RefreshRejectedError` with 401 and `RefreshSupersededError` with
    409, two opposite claims about the client's credentials. If the second inherited from
    the first, the only thing keeping them apart would be the ORDER of two `except`
    clauses, and swapping them is a silent, plausible-looking edit. This asserts the
    ordering cannot matter, and fails the moment someone makes it a subclass.
    """
    assert not issubclass(refresh.RefreshSupersededError, refresh.RefreshRejectedError)
    assert not issubclass(refresh.RefreshRejectedError, refresh.RefreshSupersededError)

    # And the behavioural half: an `except RefreshRejectedError` handler cannot swallow it.
    user_id = _a_user(db_session)
    first = refresh.issue(db_session, user_id)
    refresh.rotate(db_session, first.token)
    try:
        refresh.rotate(db_session, first.token)
    except refresh.RefreshRejectedError as caught:  # pragma: no cover - must not be taken
        pytest.fail(f"a superseded replay was caught as a rejection: {caught!r}")
    except refresh.RefreshSupersededError:
        pass


def test_an_unknown_token_is_rejected_without_touching_any_family(db_session: Session) -> None:
    user_id = _a_user(db_session)
    live = refresh.issue(db_session, user_id)

    with pytest.raises(refresh.RefreshRejectedError):
        refresh.rotate(db_session, "not-a-token-anyone-ever-issued")

    assert _family(db_session, live.family_id)[0].revoked_at is None


def test_logout_revokes_the_family_and_is_idempotent(db_session: Session) -> None:
    user_id = _a_user(db_session)
    issued = refresh.issue(db_session, user_id)

    assert refresh.revoke_presented(db_session, issued.token) is True
    assert _family(db_session, issued.family_id)[0].revoked_at is not None

    # Logging out twice, or with a token that was never real, is a no-op — not an error
    # and not a way to learn whether a token exists.
    assert refresh.revoke_presented(db_session, issued.token) is True
    assert refresh.revoke_presented(db_session, "never-issued") is False


def test_reuse_through_the_api_kills_the_session_the_client_is_holding(
    api_client: TestClient,
    db_session: Session,
    invite_code: str,
) -> None:
    """End to end: capture a cookie, let the real client rotate, then replay LATER.

    "Later" is the whole difference from the 409 test below, and it is why the row is aged:
    an immediate replay is now read as a lost race between mounts, not as theft.
    """
    registered = api_client.post(
        "/api/auth/register",
        json={
            "email": "victim@example.com",
            "password": "a-long-enough-passphrase",
            "invite_code": invite_code,
        },
    )
    assert registered.status_code == 201
    captured = api_client.cookies[REFRESH_COOKIE_NAME]

    assert api_client.post("/api/auth/refresh").status_code == 200
    live = api_client.cookies[REFRESH_COOKIE_NAME]
    assert live != captured
    _age_rotation(db_session, captured)

    # The attacker replays the cookie they captured before the rotation.
    api_client.cookies.set(REFRESH_COOKIE_NAME, captured, domain=_HOST, path=_COOKIE_PATH)
    assert api_client.post("/api/auth/refresh").status_code == 401

    # And the victim's current, never-leaked token is now dead as well.
    api_client.cookies.set(REFRESH_COOKIE_NAME, live, domain=_HOST, path=_COOKIE_PATH)
    assert api_client.post("/api/auth/refresh").status_code == 401


def test_a_superseded_refresh_returns_409_and_never_clears_the_cookie(
    api_client: TestClient,
    invite_code: str,
) -> None:
    """The route contract for a lost race, including the one header that must be absent.

    ⚠️ Clearing the cookie here would delete the token the WINNING mount just received —
    the jar is shared — and recreate issue #27 from the other end. There is no way to
    notice that from the status code alone, hence this assertion.

    It catches the form of that mistake which actually reaches a browser: a `set-cookie` in
    `HTTPException(headers=...)`. A bare `clear_refresh_cookie(response)` on a raising path
    is inert — FastAPI discards the injected `Response`'s headers when the handler raises —
    so no assertion here can see one, and there is nothing to see.
    """
    registered = api_client.post(
        "/api/auth/register",
        json={
            "email": "loser@example.com",
            "password": "a-long-enough-passphrase",
            "invite_code": invite_code,
        },
    )
    assert registered.status_code == 201
    captured = api_client.cookies[REFRESH_COOKIE_NAME]

    rotated = api_client.post("/api/auth/refresh")
    assert rotated.status_code == 200
    rotated_cookies = rotated.headers.get_list("set-cookie")
    assert any(REFRESH_COOKIE_NAME in header for header in rotated_cookies), (
        "a successful rotation must still hand back a new cookie"
    )

    api_client.cookies.set(REFRESH_COOKIE_NAME, captured, domain=_HOST, path=_COOKIE_PATH)
    superseded = api_client.post("/api/auth/refresh")

    assert superseded.status_code == 409
    assert superseded.headers.get_list("set-cookie") == [], (
        "the 409 must not touch the cookie: it belongs to the mount that won the rotation"
    )


def test_a_superseded_client_retrying_with_the_current_cookie_succeeds(
    api_client: TestClient,
    invite_code: str,
) -> None:
    """The end-to-end shape of the fix, as the browser actually performs it.

    The client does not need the winner's token handed to it — it re-reads the shared jar
    and rotates whatever is current, which is an ordinary legitimate rotation.
    """
    registered = api_client.post(
        "/api/auth/register",
        json={
            "email": "retrier@example.com",
            "password": "a-long-enough-passphrase",
            "invite_code": invite_code,
        },
    )
    assert registered.status_code == 201
    captured = api_client.cookies[REFRESH_COOKIE_NAME]

    assert api_client.post("/api/auth/refresh").status_code == 200
    current = api_client.cookies[REFRESH_COOKIE_NAME]

    # The losing mount sends the token it read before the winner's response landed.
    api_client.cookies.set(REFRESH_COOKIE_NAME, captured, domain=_HOST, path=_COOKIE_PATH)
    assert api_client.post("/api/auth/refresh").status_code == 409

    # Then it simply sends again; the browser attaches the cookie the winner rotated in.
    api_client.cookies.set(REFRESH_COOKIE_NAME, current, domain=_HOST, path=_COOKIE_PATH)
    retried = api_client.post("/api/auth/refresh")
    assert retried.status_code == 200
    assert api_client.cookies[REFRESH_COOKIE_NAME] not in (captured, current)


def test_the_401_reuse_path_clears_the_dead_cookie(
    api_client: TestClient,
    db_session: Session,
    invite_code: str,
) -> None:
    """The other direction of the cookie contract, and the reason it is not cosmetic.

    With the cookie left in the jar after a family revocation, `refresh_tokens` never reaches
    its `presented is None` short-circuit, so **every** later attempt pays a
    `ratelimit.enforce` upsert — one Postgres write and one restarted five-minute Neon window
    each — until the 30/hour bucket 429s. That is exactly the cost CLAUDE.md's failure-memo
    rule exists to avoid.

    Together with the 409 test above this pins both raising paths: the 401 clears, the 409
    does not, and swapping them fails one of the two.
    """
    registered = api_client.post(
        "/api/auth/register",
        json={
            "email": "revoked@example.com",
            "password": "a-long-enough-passphrase",
            "invite_code": invite_code,
        },
    )
    assert registered.status_code == 201
    captured = api_client.cookies[REFRESH_COOKIE_NAME]

    assert api_client.post("/api/auth/refresh").status_code == 200
    # Aged out of the grace window, so this is the theft path and not a lost race.
    _age_rotation(db_session, captured)
    api_client.cookies.set(REFRESH_COOKIE_NAME, captured, domain=_HOST, path=_COOKIE_PATH)

    rejected = api_client.post("/api/auth/refresh")

    assert rejected.status_code == 401
    cleared = [h for h in rejected.headers.get_list("set-cookie") if REFRESH_COOKIE_NAME in h]
    assert len(cleared) == 1, (
        "the 401 must clear the cookie whose family it just revoked — note a "
        "`clear_refresh_cookie(response)` call here is INERT, because FastAPI discards the "
        "injected response's headers when the handler raises"
    )
    assert "Max-Age=0" in cleared[0]
    # The behavioural half: the client's jar is empty, so its next refresh is free.
    assert REFRESH_COOKIE_NAME not in api_client.cookies


_RACE_EMAIL = "race@example.com"


def _purge_race_user() -> None:
    """Committed rows, so they need explicit cleanup — the savepoint fixture is not used."""
    with session_scope() as cleanup:
        cleanup.execute(delete(AppUser).where(AppUser.email == _RACE_EMAIL))


def test_two_simultaneous_rotations_of_one_token_cannot_both_succeed(seeded: Engine) -> None:
    """The real issue #27 race, at the level it actually happens: two transactions, one token.

    Two properties at once, because they are one behaviour:

    - **`FOR UPDATE` still serialises.** Without it both transactions read
      `rotated_at IS NULL`, both pass every check, and both mint a successor — two live
      tokens in one family and no detection at all. `outcome` would be `"rotated"`.
    - **The loser is SUPERSEDED, not rejected.** It re-reads after the winner commits and
      sees a rotation milliseconds old, which is a lost race between the standalone mount
      and the federated one sharing a cookie — not a replay. Before the grace window it
      revoked the family here, killing the winner's brand-new token: exactly the bug.

    This test does NOT use `db_session`: proving a row lock needs two real transactions on
    two real connections, so the rows are committed and cleaned up by hand.

    ⚠️ **It is therefore the only test in this file that exercises two genuinely distinct
    `transaction_timestamp()` values, which makes it the sole cover for the database-clock
    comparison the grace window is built on.** Everything under `db_session` shares one
    frozen clock by construction (see `_db_now`), so a bug that only shows up when the
    stamping transaction and the measuring transaction are different — the exact case
    two serverless invocations produce — would be invisible everywhere else. Do not "simplify"
    this onto the `db_session` fixture, and do not let it be deleted as slow.

    (The `is_alive` check below is only a guard against the degenerate ordering where the
    second finishes before the first commits; on its own it proves nothing, because an
    unlocked read still blocks later on the UPDATE.)
    """
    _purge_race_user()
    maker = get_sessionmaker()
    first = maker()
    second = maker()
    outcome: dict[str, str] = {}
    started = threading.Event()

    try:
        with session_scope() as setup:
            user = AppUser(email=_RACE_EMAIL, password_hash="unused", is_demo=False)
            setup.add(user)
            setup.flush()
            issued = refresh.issue(setup, user.id)

        # Transaction A rotates but does not commit, so it still holds the row lock.
        refresh.rotate(first, issued.token)

        def _competing_rotation() -> None:
            started.set()
            try:
                refresh.rotate(second, issued.token)
                outcome["result"] = "rotated"
            except refresh.RefreshSupersededError:
                outcome["result"] = "superseded"
            except refresh.RefreshRejectedError:
                outcome["result"] = "rejected"
            except Exception as exc:
                outcome["result"] = f"error: {exc!r}"
            finally:
                try:
                    second.commit()
                except Exception:
                    second.rollback()

        thread = threading.Thread(target=_competing_rotation, daemon=True)
        thread.start()
        assert started.wait(timeout=5), "the competing thread never started"
        thread.join(timeout=1.0)
        assert thread.is_alive(), "the competing rotation did not wait for the first one"

        first.commit()
        thread.join(timeout=15)
        assert not thread.is_alive(), "the competing rotation never unblocked"

        assert outcome["result"] == "superseded", (
            f"the loser of a concurrent rotation was answered with {outcome.get('result')!r}. "
            f'"rotated" means the FOR UPDATE in refresh.rotate() is gone and reuse detection '
            f'is bypassed entirely; "rejected" means the grace window is gone and this race '
            f"revokes the family — i.e. issue #27 is back."
        )

        with session_scope() as check:
            rows = list(
                check.scalars(select(AuthSession).where(AuthSession.family_id == issued.family_id))
            )
        assert len(rows) == 2, "the loser must not have minted a third token"
        assert all(row.revoked_at is None for row in rows), (
            "a lost race must leave the family intact — the winner is holding a live token"
        )
        live_rows = [row for row in rows if row.rotated_at is None]
        assert len(live_rows) == 1, "exactly one link in the chain should still be un-rotated"
        assert live_rows[0].revoked_at is None
    finally:
        first.close()
        second.close()
        _purge_race_user()
