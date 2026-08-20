"""Per-person invite codes, and the row lock that makes spending one atomic.

`EmailStr` validates syntax only, so `POST /api/auth/register` was open to anyone (issue #35).
Email verification would not have closed that — it proves an inbox exists, not that its owner
is someone Kilian knows.

**sha256, not argon2**, as for `auth_session.token_hash`: a code is 128 bits of CSPRNG output,
so there is no dictionary and nothing for a work factor to slow down. Only the digest is
stored, which is why `server.admin create-invite` prints the plaintext once and cannot
recover it afterwards.

**One exception for unknown, expired, revoked and exhausted**, answered by one 400 with one
message. "Expired" would confirm the guess named a real code, so never subclass
`InviteRejectedError` — that leaves the uniform answer one `except` ordering away from
splitting. The work is uniform too: one indexed statement either way, one branch for the
three "exists but unusable" causes, and no rejection path commits. Two residues, both
unexploitable at 128 bits behind `ratelimit.REGISTER` (3/hour), and neither a reason to change
the behaviour — only to state it accurately:

- `SELECT ... FOR UPDATE` stamps `xmax` on the heap tuple, so a *found* code is write-free in
  round trips and in committed state, not in storage.
- Two **concurrent** presentations of one guessed code tell "row exists" from "no row",
  because only the former blocks on the lock. That needs no live code.

**`with_for_update()` is load-bearing, and so is the caller's transaction.** Without the lock,
two registrations of one `max_uses = 1` code both read `uses = 0` and both increment: READ
COMMITTED re-reads at UPDATE time, but the decision was already taken from the stale snapshot.
Without the shared transaction, a registration that fails after the invite was spent burns a
use nobody got an account from — so `consume()` flushes and never commits.
`ck_invite_uses_within_max` backstops both. Row locks are transaction-scoped, so this works
through Neon's transaction-mode pooler, unlike a session-level advisory lock.

Revoking needs no secret and therefore no CLI: stamp `revoked_at` on the row.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.models import Invite

# 16 bytes -> 22 url-safe characters. Short enough to read down a phone line, and 128 bits
# is far past the point where guessing is the attack anyone would choose — particularly
# behind `ratelimit.REGISTER`, which allows 3 attempts per hour per client.
_CODE_BYTES: Final = 16

# The upper bound on the field at the API edge. Generous relative to the 22 characters we
# issue, so a future format change does not need a migration of the request model.
MAX_CODE_LENGTH: Final = 64

# Matches `invite.label`'s `String(64)`.
MAX_LABEL_LENGTH: Final = 64


class InviteRejectedError(Exception):
    """The presented code is unknown, expired, revoked or exhausted.

    **One exception for all four**, because the caller is told the same thing in every
    case — see the module docstring. Never split this into subclasses: the moment a caller
    can tell the causes apart, the uniform response is one `except` clause away from
    becoming an oracle.
    """


@dataclass(frozen=True, slots=True)
class IssuedInvite:
    """The plaintext code (shown to an operator ONCE) plus the row it belongs to."""

    code: str
    invite_id: int
    label: str
    max_uses: int
    expires_at: datetime | None


def digest(code: str) -> str:
    """sha256 hex of an invite code. The only form that is ever persisted."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def generate_code() -> str:
    return secrets.token_urlsafe(_CODE_BYTES)


def create(
    session: Session,
    label: str,
    max_uses: int = 1,
    expires_in: timedelta | None = None,
) -> IssuedInvite:
    """Mint a code and add its row. Does **not** commit — the caller owns the transaction.

    The expiry is stamped from the *operator's* clock, unlike the comparison in `consume()`,
    which uses the database's. That asymmetry is deliberate and safe: minting happens once,
    by hand, against a horizon measured in days, so a few seconds of skew changes nothing —
    while the comparison side spans two serverless invocations and must have one clock.
    """
    code = generate_code()
    invite = Invite(
        code_hash=digest(code),
        label=label,
        max_uses=max_uses,
        uses=0,
        expires_at=None if expires_in is None else datetime.now(UTC) + expires_in,
    )
    session.add(invite)
    session.flush()
    return IssuedInvite(
        code=code,
        invite_id=invite.id,
        label=invite.label,
        max_uses=invite.max_uses,
        expires_at=invite.expires_at,
    )


def consume(session: Session, code: str) -> Invite:
    """Spend one use of `code`, or raise `InviteRejectedError`. Does **not** commit.

    Returns the row, so the caller can record which invite an account came from.

    Raises the same exception for an unknown, expired, revoked or exhausted code, and commits
    nothing on any of those paths — so a failed registration cannot burn a use.
    """
    presented_digest = digest(code)

    # `with_for_update()` is LOAD-BEARING — see the module docstring before removing it to
    # "save a lock". It also takes the DATABASE's clock in the same statement, at no extra
    # round trip, so expiry is never judged against a serverless function's clock.
    found = session.execute(
        select(Invite, func.now()).where(Invite.code_hash == presented_digest).with_for_update()
    ).one_or_none()
    if found is None:
        raise InviteRejectedError("unknown invite code")
    invite: Invite = found[0]
    db_now: datetime = found[1]

    # Redundant today — the lookup was an indexed equality match — and kept for the reason
    # `refresh.rotate` keeps its copy: it stays correct if the row is ever fetched by another
    # key, where `==` on a secret would be a timing side channel.
    if not hmac.compare_digest(invite.code_hash, presented_digest):  # pragma: no cover
        raise InviteRejectedError("digest mismatch")

    # ONE branch for all three remaining causes: no path is shorter than another, and no
    # caller can tell which clause rejected them.
    if (
        invite.revoked_at is not None
        or (invite.expires_at is not None and invite.expires_at <= db_now)
        or invite.uses >= invite.max_uses
    ):
        raise InviteRejectedError("invite code is not usable")

    # Safe as plain Python arithmetic *because* of the lock: the value was read under
    # `FOR UPDATE`, so no concurrent transaction can have moved it since.
    invite.uses += 1
    session.flush()
    return invite
