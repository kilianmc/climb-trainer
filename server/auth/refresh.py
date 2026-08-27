"""Opaque refresh tokens, rotation, and reuse detection.

32 bytes from `secrets.token_urlsafe`, stored as a **sha256** digest — not argon2: a work
factor buys nothing against 256 bits of CSPRNG output, and sha256 already gives the one
property needed, that a database dump is not a set of working credentials. Every login starts
a *family*; each refresh stamps `rotated_at` on the row it replaces, so a family is a chain
with one live link. A token whose row is already rotated or revoked has two holders, and the
request cannot say which, so the safe answer is to revoke the whole family. That only works if
the two presentations are SERIALISED — hence `SELECT ... FOR UPDATE`; see the comment there.

## The replay grace window — a deliberate NARROWING of the paragraph above

A replay inside `REPLAY_GRACE` whose row is not *revoked* writes nothing and raises
`RefreshSupersededError`, which `routes.py` answers **409**: "your cookie is older than the
jar; send it again". It has to live server-side because no client can cover the case — the
in-flight dedupe covers one **mount**, a Web Lock one **origin**, the cookie the whole
**site**, so the standalone app and the federated mount are two origins sharing one cookie and
`FOR UPDATE` *guarantees* the loser re-reads a rotated row (issue #27). The retry is sound
because a mount does not own a token, the shared jar does.

Three bounds, none of them a reason to widen the window. (1) The winner leads by about one
database round trip — a **margin, not an ordering guarantee**; a 409 processed first re-presents
the same token, gets a second 409, and that mount stops refreshing until a reload. (2) One
retry converges exactly TWO realms; revisit the count if a third same-site origin mounts this
app. (3) A loser slower than `REPLAY_GRACE` still trips reuse detection and still revokes the
family — issue #27 is narrowed, not eliminated.

⚠️ **The trade is a real loss, not a free win.** Inside the window a replayed token no longer
revokes its family, so a genuine theft landing there goes **undetected**. The replayer gains
no token (the 409 carries none, and the successor is reachable only by whoever holds the jar).
Accepted because the alternative is that our own two-origin configuration logs real users out.
`revoked_at` rows are never graced, at any age. Lifetime is 30 days — the *idle* horizon.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from server.models import AuthSession

REFRESH_TTL: Final = timedelta(days=30)

# How long after a rotation a replay of the retired token is treated as a lost race
# rather than as theft. See the grace-window section of the module docstring.
#
# 10 seconds, and what the margin is for is worth getting right. It covers delay in the
# LOSER'S ARRIVAL — the gap between reading the shared cookie and reaching this function: a
# stalled radio, a queued request, a cold start on its own invocation. It does **not** need
# to cover a slow winner. A loser waiting on the row lock is dated by its own transaction
# start (see the grace branch), so however long it waits, the rotation it eventually sees is
# not aged by the waiting. Under a second would fail exactly when the network is bad;
# minutes would widen the undetected-theft window for nothing. `test_auth_refresh.py` pins
# the magnitude, because the number *is* the trade.
REPLAY_GRACE: Final = timedelta(seconds=10)

# 32 bytes -> 43 url-safe characters. Comfortably past the point where brute force is
# the attack anyone would choose.
_TOKEN_BYTES: Final = 32


class RefreshRejectedError(Exception):
    """The presented refresh token is unknown, expired, revoked, or replayed.

    One exception for all four, because the client is told the same thing in every case
    — the distinction is useful to an attacker and to nobody else.
    """


class RefreshSupersededError(Exception):
    """The presented token was rotated moments ago: a lost race, not a replay attack.

    **A SIBLING of `RefreshRejectedError`, never a subclass.** Every existing handler
    catches `RefreshRejectedError` and answers 401, and this case must answer 409 — the
    opposite claim about the client's credentials. Subclassing would make the ordering of
    two `except` clauses the only thing standing between the two answers, and reordering
    them is a silent, plausible-looking edit. `web/src/auth/messages.ts` already carries
    that footgun for `NotJsonError extends ApiError` and needs a comment to survive it;
    this hierarchy is flat so it cannot happen at all. `test_auth_refresh.py` asserts the
    two are unrelated.

    Nothing is written before this is raised, so a caller may commit or roll back.
    """


@dataclass(frozen=True, slots=True)
class IssuedRefresh:
    """The plaintext token (returned to the client ONCE) plus what the caller needs."""

    token: str
    user_id: int
    family_id: uuid.UUID
    expires_at: datetime


def digest(token: str) -> str:
    """sha256 hex of a refresh token. The only form that is ever persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(
    session: Session,
    user_id: int,
    family_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> IssuedRefresh:
    """Mint a token and add its row. Starts a new family unless one is supplied.

    Does not commit — the caller owns the transaction, so the token row and whatever
    else the request wrote land together or not at all.

    `now` lets `rotate()` pass the **database** clock, so the retired row's `rotated_at` and
    its successor's `issued_at` come from one source. `register` and `login` leave it unset:
    the only sub-minute comparison in this module is the grace window, and both of those
    start a family rather than measuring one.
    """
    now = now if now is not None else datetime.now(UTC)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    family = family_id if family_id is not None else uuid.uuid4()
    expires_at = now + REFRESH_TTL

    session.add(
        AuthSession(
            user_id=user_id,
            family_id=family,
            token_hash=digest(token),
            issued_at=now,
            expires_at=expires_at,
        )
    )
    session.flush()
    return IssuedRefresh(token=token, user_id=user_id, family_id=family, expires_at=expires_at)


def rotate(session: Session, presented_token: str) -> IssuedRefresh:
    """Validate, retire the presented token, and issue its successor in the same family.

    Raises `RefreshRejectedError` on anything unexpected. **On the replay path this
    method writes** (it revokes the family) and then raises, so the caller must commit
    before turning the exception into a 401 — a rolled-back revocation would leave the
    stolen family live, which is the entire bug this function exists to prevent.

    Raises `RefreshSupersededError` for a replay inside `REPLAY_GRACE` of an unrevoked
    row's rotation. That path writes **nothing** — no rotation, no issue, no revocation —
    and means "retry with the cookie you now hold". See the module docstring.
    """
    presented_digest = digest(presented_token)
    # `with_for_update()` is LOAD-BEARING. Unlocked, two presentations of one token both see
    # `rotated_at IS NULL`, both pass the reuse check below and both mint a successor, so reuse
    # is never detected — the exact case this mechanism exists for. READ COMMITTED does not
    # help: the loser's UPDATE re-reads the row, but the decision was taken from the stale
    # snapshot. Proved by `tests/test_auth_refresh.py::
    # test_two_simultaneous_rotations_of_one_token_cannot_both_succeed`, which needs two real
    # transactions. A row lock is transaction-scoped, so it works through PgBouncer's
    # transaction-mode pooler — a session-level advisory lock would not.
    found = session.execute(
        select(AuthSession, func.now())
        .where(AuthSession.token_hash == presented_digest)
        .with_for_update()
    ).one_or_none()
    if found is None:
        raise RefreshRejectedError("unknown refresh token")
    row: AuthSession = found[0]
    # The database's clock, selected in the statement above at no extra round trip, because the
    # grace comparison spans TWO serverless invocations and 2 s of skew is 20 % of a 10 s window.
    # `func.now()` is `transaction_timestamp()`, NOT `clock_timestamp()`: it dates the
    # presenter's ARRIVAL rather than the length of its wait, so a loser stuck behind a slow
    # winner stays inside the window. Guarded by `tests/test_auth_refresh.py::
    # test_the_grace_comparison_uses_the_transaction_clock_not_the_wall_clock`. ⚠️ Doing other
    # database work in this transaction before `rotate` ages `now()` by however long it takes;
    # the test fixture breaks that by construction and production must not. The annotation is
    # where the TIMESTAMPTZ claim is made — `func.now()` is `Any` to mypy.
    db_now: datetime = found[1]

    # The lookup above was an indexed equality match, so this comparison is redundant
    # today. It is kept because it is the line that stays correct if the row is ever
    # fetched by some other key (by family, say, when adding a device list) and the
    # digests end up compared in Python, where `==` on a secret is a timing side channel.
    if not hmac.compare_digest(row.token_hash, presented_digest):  # pragma: no cover
        raise RefreshRejectedError("digest mismatch")

    # A LOST RACE, not a replay. Checked before reuse detection, and every clause is
    # load-bearing — widening any of them widens the window in which a real theft goes
    # undetected:
    #
    #   rotated_at is not None  -> there is a successor, so there is something to retry with
    #   revoked_at is None      -> NEVER grace a revoked row. Revoked means a logout or an
    #                              earlier family revocation; both are decisions already
    #                              taken, and gracing one would resurrect a killed session.
    #   within REPLAY_GRACE     -> the loser of a concurrent refresh, not a token found
    #                              in a log file next week
    #   not expired             -> a 30-day-old cookie has no live successor to retry into
    #
    # This branch writes NOTHING. The client is told to present the cookie again: the jar
    # is per-site and now holds the winner's fresh token, so its next attempt is an
    # ordinary rotation. See the grace-window section of the module docstring for the
    # security trade this accepts.
    if (
        row.rotated_at is not None
        and row.revoked_at is None
        and db_now - row.rotated_at <= REPLAY_GRACE
        and row.expires_at > db_now
    ):
        raise RefreshSupersededError("refresh token was rotated moments ago; retry")

    if row.rotated_at is not None or row.revoked_at is not None:
        # REUSE DETECTED. See the module docstring: kill the whole chain, not just this
        # link, because we cannot tell the thief from the victim and one of them has a
        # currently-valid successor token.
        revoke_family(session, row.family_id)
        raise RefreshRejectedError("refresh token reuse detected; family revoked")

    if row.expires_at <= db_now:
        raise RefreshRejectedError("refresh token expired")

    # Stamped from the same database clock the next presentation will be measured against,
    # so a family's chain is dated consistently no matter which instance rotated it.
    row.rotated_at = db_now
    return issue(session, row.user_id, family_id=row.family_id, now=db_now)


def revoke_family(session: Session, family_id: uuid.UUID) -> int:
    """Revoke every live token in a family. Returns how many rows were affected.

    Only touches rows that are not already revoked, so calling it twice is a no-op
    rather than a rewrite of history.
    """
    # `Session.execute` is typed as returning `Result`, which has no `rowcount`; a DML
    # statement always yields a `CursorResult`, which does. The cast says that.
    result = cast(
        CursorResult[Any],
        session.execute(
            update(AuthSession)
            .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        ),
    )
    return result.rowcount


def revoke_presented(session: Session, presented_token: str) -> bool:
    """Logout: revoke the family the presented token belongs to. Idempotent.

    Returns whether a matching row existed. An unknown token is not an error — logging
    out with a stale or forged cookie must still clear the cookie and return success,
    or logout becomes a way to probe which tokens are real.
    """
    row = session.scalars(
        select(AuthSession).where(AuthSession.token_hash == digest(presented_token))
    ).one_or_none()
    if row is None:
        return False
    revoke_family(session, row.family_id)
    return True
