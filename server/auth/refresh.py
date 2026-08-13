"""Opaque refresh tokens, rotation, and reuse detection.

## Opaque, not a JWT

A refresh token is 32 bytes from `secrets.token_urlsafe`. It carries no claims and means
nothing on its own — its entire meaning is the row it matches. That is what makes it
revocable, which is precisely what the stateless access token in `tokens.py` is not.

## sha256, deliberately NOT argon2

Passwords get argon2 because they are low-entropy secrets a human chose; the whole cost
parameter exists to make guessing them expensive. A refresh token is **256 bits of
CSPRNG output** — there is no dictionary, no guessing, and nothing for a work factor to
slow down. Running argon2 on every refresh would buy exactly zero security and spend
46 MiB and tens of milliseconds of a 1-vCPU function doing it. sha256 gives the one
property that is actually needed: a database dump is not a set of working credentials.

## Families and reuse detection — the important part of this file

Every login starts a *family*. Each refresh writes a new row in the same family and
stamps `rotated_at` on the one it replaces, so the family is a chain with exactly one
live link.

If a token is presented whose row is **already rotated or revoked**, that chain has two
holders. Either the legitimate client replayed (it should not — rotation is atomic per
request) or someone captured the cookie. There is no way to tell which from the request,
so the safe response is to **revoke the entire family**: both the attacker and the real
user are logged out, and the real user's next login starts a clean family. Silently
issuing a new token instead would hand a thief an indefinitely renewable session.

Detection only works if the two requests are **serialised**, so `rotate()` reads the row
with `SELECT ... FOR UPDATE`. See the comment at that line: without the lock, a
simultaneous replay is not detected at all — which is the case that matters most.

## Lifetime

30 days. Long enough that a returning user is not asked to log in every week, short
enough that an abandoned cookie stops working. Rotation means a token is normally in use
for hours, not weeks — the 30 days is the *idle* horizon.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from server.models import AuthSession

REFRESH_TTL: Final = timedelta(days=30)

# 32 bytes -> 43 url-safe characters. Comfortably past the point where brute force is
# the attack anyone would choose.
_TOKEN_BYTES: Final = 32


class RefreshRejectedError(Exception):
    """The presented refresh token is unknown, expired, revoked, or replayed.

    One exception for all four, because the client is told the same thing in every case
    — the distinction is useful to an attacker and to nobody else.
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


def issue(session: Session, user_id: int, family_id: uuid.UUID | None = None) -> IssuedRefresh:
    """Mint a token and add its row. Starts a new family unless one is supplied.

    Does not commit — the caller owns the transaction, so the token row and whatever
    else the request wrote land together or not at all.
    """
    now = datetime.now(UTC)
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
    """
    presented_digest = digest(presented_token)
    # `with_for_update()` is LOAD-BEARING — do not remove it to "save a lock".
    #
    # Without it, two requests presenting the SAME token race: both SELECT the row,
    # both see `rotated_at IS NULL`, both pass the reuse check below, and both mint a
    # successor. The family ends up with two live tokens and reuse is never detected —
    # which is exactly the attacker-replays-while-the-victim-refreshes case this whole
    # mechanism exists to catch. READ COMMITTED does not help: the second transaction
    # re-reads the row when it UPDATEs, but the *decision* was already taken from the
    # stale snapshot. `FOR UPDATE` serialises the two on the row, so the loser re-reads
    # after the winner commits, sees `rotated_at` set, and correctly revokes the family.
    #
    # Row locks are transaction-scoped, so this works through PgBouncer's
    # transaction-mode pooler (unlike a session-level advisory lock, which does not).
    row = session.scalars(
        select(AuthSession).where(AuthSession.token_hash == presented_digest).with_for_update()
    ).one_or_none()
    if row is None:
        raise RefreshRejectedError("unknown refresh token")

    # The lookup above was an indexed equality match, so this comparison is redundant
    # today. It is kept because it is the line that stays correct if the row is ever
    # fetched by some other key (by family, say, when adding a device list) and the
    # digests end up compared in Python, where `==` on a secret is a timing side channel.
    if not hmac.compare_digest(row.token_hash, presented_digest):  # pragma: no cover
        raise RefreshRejectedError("digest mismatch")

    now = datetime.now(UTC)

    if row.rotated_at is not None or row.revoked_at is not None:
        # REUSE DETECTED. See the module docstring: kill the whole chain, not just this
        # link, because we cannot tell the thief from the victim and one of them has a
        # currently-valid successor token.
        revoke_family(session, row.family_id)
        raise RefreshRejectedError("refresh token reuse detected; family revoked")

    if row.expires_at <= now:
        raise RefreshRejectedError("refresh token expired")

    row.rotated_at = now
    return issue(session, row.user_id, family_id=row.family_id)


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
