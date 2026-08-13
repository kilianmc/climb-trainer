"""Refresh rotation and reuse detection.

The single most important behaviour in `server/auth/refresh.py`, and the reason the
`auth_session` table stores a chain rather than one row per session: a replayed token
must take the **whole family** down, including the successor the legitimate client is
holding. Getting this subtly wrong — issuing a fresh token on a replay, or revoking only
the presented row — leaves a thief with an indefinitely renewable session, and nothing
else in the suite would notice.

**Skips without `DATABASE_URL`** (see `conftest.py`). CI runs them for real.
"""

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from server.auth import refresh
from server.auth.cookies import REFRESH_COOKIE_NAME
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
    """Reuse detection. The successor must die with the replayed token, not survive it."""
    user_id = _a_user(db_session)
    first = refresh.issue(db_session, user_id)
    second = refresh.rotate(db_session, first.token)

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
) -> None:
    """End to end: capture a cookie, let the real client rotate, then replay."""
    registered = api_client.post(
        "/api/auth/register",
        json={"email": "victim@example.com", "password": "a-long-enough-passphrase"},
    )
    assert registered.status_code == 201
    captured = api_client.cookies[REFRESH_COOKIE_NAME]

    assert api_client.post("/api/auth/refresh").status_code == 200
    live = api_client.cookies[REFRESH_COOKIE_NAME]
    assert live != captured

    # The attacker replays the cookie they captured before the rotation.
    api_client.cookies.set(REFRESH_COOKIE_NAME, captured, domain=_HOST, path=_COOKIE_PATH)
    assert api_client.post("/api/auth/refresh").status_code == 401

    # And the victim's current, never-leaked token is now dead as well.
    api_client.cookies.set(REFRESH_COOKIE_NAME, live, domain=_HOST, path=_COOKIE_PATH)
    assert api_client.post("/api/auth/refresh").status_code == 401


_RACE_EMAIL = "race@example.com"


def _purge_race_user() -> None:
    """Committed rows, so they need explicit cleanup — the savepoint fixture is not used."""
    with session_scope() as cleanup:
        cleanup.execute(delete(AppUser).where(AppUser.email == _RACE_EMAIL))


def test_two_simultaneous_rotations_of_one_token_cannot_both_succeed(seeded: Engine) -> None:
    """Regression for the lost-update race that silently bypassed reuse detection.

    Two requests presenting the SAME refresh token at the same time used to both read
    `rotated_at IS NULL`, both pass the reuse check and both mint a successor — leaving
    two live tokens in one family and no detection at all. `rotate()` now reads its row
    `FOR UPDATE`, which serialises them.

    This test does NOT use `db_session`: proving a row lock needs two real transactions
    on two real connections, so the rows are committed and cleaned up by hand.

    **What makes it a genuine proof:** with the lock, the second transaction re-reads
    after the first commits, sees `rotated_at` and is rejected. Without it, the second
    decides from its stale snapshot and returns a successor — `outcome` is `"rotated"`
    and the test fails. (The `is_alive` check below is only a guard against the
    degenerate ordering where the second finishes before the first commits; on its own
    it proves nothing, because an unlocked read still blocks later on the UPDATE.)
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

        assert outcome["result"] == "rejected", (
            f"a concurrent replay was not detected (outcome: {outcome.get('result')!r}). "
            f"This is what happens when the FOR UPDATE in refresh.rotate() is removed."
        )

        with session_scope() as check:
            rows = list(
                check.scalars(select(AuthSession).where(AuthSession.family_id == issued.family_id))
            )
        assert len(rows) == 2, "the loser must not have minted a third token"
        assert all(row.revoked_at is not None for row in rows), "the family must be revoked"
    finally:
        first.close()
        second.close()
        _purge_race_user()
