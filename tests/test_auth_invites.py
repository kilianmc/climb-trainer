"""The invite gate on `POST /api/auth/register`.

Registration is the one endpoint that creates state from an anonymous request, so it earns
tests under two of CLAUDE.md's bullets at once: "core user paths — auth" and "project-wide
invariants that silently rot". Four properties are asserted here and nothing else, because
everything else about invites is either the schema (CI's `alembic check`) or a CLI a human
runs by hand:

1. **A rejection says nothing.** Unknown, expired, revoked and exhausted are one status and
   one body. An "expired" that differed from "unknown" would confirm a code exists, which is
   most of what a guesser wants.
2. **`max_uses` binds**, sequentially and under real concurrency. The concurrent arm is the
   only test that can see `with_for_update()` doing its job.
3. **A failed registration does not burn a use**, because consuming and inserting share one
   transaction.
4. **The gate is not optional** — a request with no code at all is refused.

Behaviour, not implementation: nothing here asserts on the SQL, the lock, or the number of
statements. The concurrency test infers the lock from the outcome.

**Skips without `DATABASE_URL`** (see `conftest.py`). CI runs them for real.
"""

import itertools
import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.auth import invites
from server.db import get_sessionmaker, session_scope
from server.models import AppUser, Invite

_PASSWORD = "a-long-enough-passphrase"

# Committed by the concurrency test, so it cleans up by label rather than by savepoint.
_RACE_LABEL = "invite race"

# `ratelimit.REGISTER` is 3 per hour per IP, and several tests here need more attempts than
# that. Each one comes from its own TEST-NET-3 address so the limiter never decides the
# outcome of a test about invites — the limiter has its own file.
_source_ips = itertools.count(1)


def _db_now(session: Session) -> datetime:
    """`transaction_timestamp()` — the clock `invites.consume` compares expiry against.

    Frozen for the whole test under `db_session` (one long transaction joined as a
    savepoint), which is exactly what makes the arithmetic below exact instead of a race
    against the suite's own runtime. Same reasoning as `tests/test_auth_refresh.py::_db_now`.
    """
    stamped: datetime | None = session.scalar(select(func.now()))
    assert stamped is not None
    return stamped


def _attempt(client: TestClient, code: str, email: str) -> Response:
    response: Response = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PASSWORD, "invite_code": code},
        headers={"x-forwarded-for": f"203.0.113.{next(_source_ips)}"},
    )
    return response


def _register(client: TestClient, code: str, email: str) -> int:
    return _attempt(client, code, email).status_code


def _row(session: Session, code: str) -> Invite:
    return session.scalars(select(Invite).where(Invite.code_hash == invites.digest(code))).one()


def _uses(session: Session, code: str) -> int:
    used = session.scalar(select(Invite.uses).where(Invite.code_hash == invites.digest(code)))
    assert used is not None
    return used


def test_registration_without_an_invite_code_is_refused(api_client: TestClient) -> None:
    """The gate is the point of the whole change: no field, no account.

    A 422 rather than the uniform 400 below, and that is fine — "you sent no code" is a
    statement about the request's shape, not about which codes exist. The body is checked, not
    just the status: a 422 for a *different* reason (a mistyped email in this payload, say)
    would otherwise pass and this test would stop asserting that the field is required at all.
    `tests/test_validation_errors.py` owns the separate question of what that body must not
    contain.
    """
    response = api_client.post(
        "/api/auth/register",
        json={"email": "uninvited@example.com", "password": _PASSWORD},
    )
    assert response.status_code == 422, response.text
    assert [error["loc"] for error in response.json()["detail"]] == [["body", "invite_code"]]


def test_a_valid_code_registers_exactly_once_and_increments_its_usage(
    api_client: TestClient, db_session: Session
) -> None:
    single = invites.create(db_session, label="one person", max_uses=1)

    assert _register(api_client, single.code, "invited@example.com") == 201
    assert _uses(db_session, single.code) == 1

    # The same code again, from a different address: the count is what stops it, not the
    # email uniqueness constraint.
    assert _register(api_client, single.code, "second@example.com") == 400
    assert _uses(db_session, single.code) == 1


def test_max_uses_cannot_be_exceeded(api_client: TestClient, db_session: Session) -> None:
    """A two-use invite creates exactly two accounts, and the third attempt is refused."""
    shared = invites.create(db_session, label="a couple", max_uses=2)

    assert _register(api_client, shared.code, "first@example.com") == 201
    assert _register(api_client, shared.code, "second@example.com") == 201
    assert _register(api_client, shared.code, "third@example.com") == 400

    assert _uses(db_session, shared.code) == 2
    assert (
        db_session.scalar(
            select(func.count()).select_from(AppUser).where(AppUser.email == "third@example.com")
        )
        == 0
    )


def test_a_failed_registration_does_not_consume_a_use(
    api_client: TestClient, db_session: Session
) -> None:
    """The atomicity property, from the side a real person hits it.

    Mistyping an address that already exists must not silently spend the one invite they
    were given — they would be left unable to register at all, with nothing on screen
    explaining why. `consume()` does not commit, so the 409 unwinds the increment with the
    rest of the request.
    """
    single = invites.create(db_session, label="one person", max_uses=1)
    assert _register(api_client, single.code, "taken@example.com") == 201
    assert _uses(db_session, single.code) == 1

    second = invites.create(db_session, label="another person", max_uses=1)
    assert _register(api_client, second.code, "taken@example.com") == 409
    assert _uses(db_session, second.code) == 0, (
        "a registration that failed on a duplicate email burned a use — the invite is now "
        "dead and its holder can never register"
    )

    # And the invite is genuinely still usable, which is the property that matters.
    assert _register(api_client, second.code, "retried@example.com") == 201
    assert _uses(db_session, second.code) == 1


def test_unknown_expired_revoked_and_exhausted_codes_are_indistinguishable(
    api_client: TestClient, db_session: Session
) -> None:
    """One status, one body, for all four causes.

    The four rows are built to differ only in the field under test. If any branch of
    `invites.consume` ever gets its own status, message or shape — an "invite expired" that
    a caller can tell from "no such invite" — this fails, and that is the whole point:
    knowing a code exists is most of the way to using it.
    """
    now = _db_now(db_session)

    expired = invites.create(db_session, label="expired", max_uses=1)
    revoked = invites.create(db_session, label="revoked", max_uses=1)
    exhausted = invites.create(db_session, label="exhausted", max_uses=1)

    _row(db_session, expired.code).expires_at = now - timedelta(seconds=1)
    _row(db_session, revoked.code).revoked_at = now
    _row(db_session, exhausted.code).uses = 1
    db_session.flush()

    unknown = invites.generate_code()

    responses = {
        name: _attempt(api_client, code, f"probe-{name}@example.com")
        for name, code in (
            ("unknown", unknown),
            ("expired", expired.code),
            ("revoked", revoked.code),
            ("exhausted", exhausted.code),
        )
    }

    answers = {
        name: (response.status_code, response.json()) for name, response in responses.items()
    }
    assert len(set(map(repr, answers.values()))) == 1, (
        f"the four rejection causes are distinguishable: {answers}. A caller must not be "
        f"able to tell an unknown code from one that exists but cannot be used."
    )
    assert all(status == 400 for status, _ in answers.values()), answers

    # No account was created by any of them, so this is a refusal and not a partial success.
    assert (
        db_session.scalar(
            select(func.count()).select_from(AppUser).where(AppUser.email.like("probe-%"))
        )
        == 0
    )


def test_the_account_records_which_invite_created_it_and_the_link_cannot_be_deleted_away(
    api_client: TestClient, db_session: Session
) -> None:
    """Attribution, and the reason it is a `RESTRICT` foreign key rather than a nice-to-have.

    A counter says an invite was used; `app_user.invite_id` says by whom. `RESTRICT` is what
    keeps that true: deleting a spent invite would erase the record, so the database refuses
    and revoking stays the only supported way to retire one.
    """
    issued = invites.create(db_session, label="Bob, from the gym", max_uses=1)
    assert _register(api_client, issued.code, "bob@example.com") == 201

    invite_id = _row(db_session, issued.code).id
    assert (
        db_session.scalar(select(AppUser.invite_id).where(AppUser.email == "bob@example.com"))
        == invite_id
    )

    try:
        with pytest.raises(IntegrityError):
            db_session.execute(delete(Invite).where(Invite.id == invite_id))
            db_session.flush()
    finally:
        db_session.rollback()


def test_the_database_refuses_to_let_an_invite_be_over_spent(db_session: Session) -> None:
    """Proves the MIGRATION created `ck_invite_uses_within_max`, not just the model.

    The row lock in `consume()` is the application's guarantee; this is the database's, and it
    is the one that still holds if a future write path forgets the lock. Same shape as
    `test_seed.py::test_database_rejects_two_labels_on_the_same_rung`.
    """
    single = invites.create(db_session, label="one person", max_uses=1)
    _row(db_session, single.code).uses = 2
    try:
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        # A failed flush poisons the SAVEPOINT; unwind it so teardown stays clean.
        db_session.rollback()


def _purge_race_rows() -> None:
    """Committed rows need explicit cleanup — the concurrency test cannot use a savepoint."""
    with session_scope() as cleanup:
        cleanup.execute(delete(Invite).where(Invite.label == _RACE_LABEL))


def test_two_simultaneous_registrations_cannot_both_spend_the_last_use(
    seeded: Engine,
) -> None:
    """The race `with_for_update()` exists for, at the level it actually happens.

    Two transactions, one single-use code. Without the row lock both read `uses = 0`, both
    pass the check, and both increment — one invite, two accounts, and no other test in the
    suite would notice. With it, the second blocks until the first commits, then re-reads and
    is rejected.

    This does NOT use `db_session`: proving a row lock needs two real transactions on two
    real connections, so the rows are committed and cleaned up by hand. Do not "simplify" it
    onto the savepoint fixture — a savepoint on one connection cannot race itself.

    (The `is_alive` check is only a guard against the degenerate ordering where the second
    thread finishes before the first commits; on its own it proves nothing.)
    """
    _purge_race_rows()
    maker = get_sessionmaker()
    first = maker()
    second = maker()
    outcome: dict[str, str] = {}
    started = threading.Event()

    try:
        with session_scope() as setup:
            issued = invites.create(setup, label=_RACE_LABEL, max_uses=1)

        # Transaction A spends the use but does not commit, so it still holds the row lock.
        invites.consume(first, issued.code)

        def _competing_consume() -> None:
            started.set()
            try:
                invites.consume(second, issued.code)
                outcome["result"] = "consumed"
            except invites.InviteRejectedError:
                outcome["result"] = "rejected"
            except Exception as exc:
                outcome["result"] = f"error: {exc!r}"
            finally:
                try:
                    second.commit()
                except Exception:
                    second.rollback()

        thread = threading.Thread(target=_competing_consume, daemon=True)
        thread.start()
        assert started.wait(timeout=5), "the competing thread never started"
        thread.join(timeout=1.0)
        assert thread.is_alive(), "the competing registration did not wait for the first one"

        first.commit()
        thread.join(timeout=15)
        assert not thread.is_alive(), "the competing registration never unblocked"

        assert outcome["result"] == "rejected", (
            f"the loser of two simultaneous registrations was answered with "
            f'{outcome.get("result")!r}. "consumed" means the FOR UPDATE in '
            f"invites.consume() is gone and one invite can mint unlimited accounts."
        )

        with session_scope() as check:
            spent = check.scalar(
                select(Invite.uses).where(Invite.code_hash == invites.digest(issued.code))
            )
        assert spent == 1, f"a single-use invite ended up with uses={spent}"
    finally:
        first.close()
        second.close()
        _purge_race_rows()
