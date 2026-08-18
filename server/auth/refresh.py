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

## The replay grace window — a deliberate narrowing of the paragraph above

A replay presented within `REPLAY_GRACE` of the rotation it lost, whose row is **not**
revoked, does not revoke the family. `rotate()` writes nothing at all on that path and
raises `RefreshSupersededError`, which `routes.py` turns into a **409** meaning "your
cookie is older than the jar; send it again".

**This has to live here, on the server, because no client can cover the case.** Three
realms are in play and they do not line up: the client's in-flight dedupe covers one
**mount**, a Web Lock covers one **origin**, and the refresh cookie covers the whole
**site**. The standalone app (`climb.kilianmc.com`) and the federated mount inside the
portfolio (`kilianmc.com`) are two *origins* — two independent lock managers — sharing
**one** cookie, because they are same-site. So both mounts can present the same
pre-rotation token, and the row lock above then guarantees the loss: `FOR UPDATE`
*serialises* the two presentations, it does not deduplicate them, so the loser re-reads
the row, sees `rotated_at`, and used to revoke the family — killing the winner's
brand-new token too. Both mounts logged out, with no theft anywhere (issue #27).

"Try again" is a sound answer only because the cookie is per-**site**. The loser is not
handed the winner's token — the successor's plaintext does not exist in the row (see the
sha256 note above) and is never recoverable — and it does not need it: a mount does not
own a token, the shared cookie jar does. Re-reading that jar yields the winner's fresh
token, and rotating *that* is an ordinary legitimate rotation.

### What this does NOT guarantee — three bounds, all deliberate

None of these is a reason to widen the window; they are the shape of the trade, and they
must stay written down rather than be discovered later.

1. **The retry is not certain to find the winner's cookie.** The winner's response is
   dispatched after its `commit()` — which is what releases this row lock — and the loser
   then pays its own commit round trip before answering, so the winner leads by roughly one
   database round trip. That is a **margin, not an ordering guarantee**: the two responses
   travel independently, and if the loser's 409 is processed first its retry re-presents the
   same token, gets a second 409, and that mount stops refreshing for the rest of the page
   load. The family survives and a reload recovers it.
2. **One retry converges exactly TWO realms.** With three same-site origins presenting
   concurrently, two lose, both retry against the same fresh token, and one of them loses
   again with no retry left. Today there are two (the standalone origin and the shell's), so
   the cap is correct and it saves a Postgres write. **Revisit it if a third same-site origin
   ever mounts this app** — the client, not this module, is where the retry count lives.
3. **A loser that arrives more than `REPLAY_GRACE` after the winner's commit is still read
   as theft** and still revokes the family. Issue #27 is therefore **narrowed, not
   eliminated**: a request whose journey from reading the cookie to reaching `rotate()`
   exceeds 10 s (a stalled radio, a queued cold start) hits the original failure.

**The security trade, stated plainly, because it is a loss and not a free win.** This is
separate from the three bounds above: those are cases the fix does not reach, this is
ground the fix gives up. Inside the window, replaying an already-rotated token no longer
revokes the family. What a
replayer gains: nothing directly. The 409 carries no token, and the successor is only
reachable by whoever already holds the shared cookie jar — i.e. the browser. What is
lost: a genuine theft whose replay happens to land inside the window goes **undetected**,
where it would previously have burned the family. Reuse detection is therefore narrower
than it was. Accepted, because the alternative is that the portfolio's own two-origin
configuration logs real users out for free. Outside the window — and for a revoked row at
any age — the revoke-the-family behaviour is exactly as it was.

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
    # `with_for_update()` is LOAD-BEARING — do not remove it to "save a lock".
    #
    # Without it, two requests presenting the SAME token race: both SELECT the row,
    # both see `rotated_at IS NULL`, both pass the reuse check below, and both mint a
    # successor. The family ends up with two live tokens and reuse is never detected —
    # which is exactly the attacker-replays-while-the-victim-refreshes case this whole
    # mechanism exists to catch. READ COMMITTED does not help: the second transaction
    # re-reads the row when it UPDATEs, but the *decision* was already taken from the
    # stale snapshot. `FOR UPDATE` serialises the two on the row, so the loser re-reads
    # after the winner commits and sees `rotated_at` set — then either graces it or revokes
    # the family, per the grace window below.
    #
    # Row locks are transaction-scoped, so this works through PgBouncer's
    # transaction-mode pooler (unlike a session-level advisory lock, which does not).
    #
    # It also selects the DATABASE's clock, in the same statement and at no extra round trip.
    # The grace comparison below spans **two serverless invocations**, so taking each side
    # from a local `datetime.now(UTC)` would measure a 10-second window across two
    # unsynchronised clocks: 2 s of skew is 20 % of the window, and skew in the unsafe
    # direction turns a lost race into a family revocation. One clock, one source.
    #
    # `func.now()` is Postgres `transaction_timestamp()` — the start of THIS transaction, not
    # `clock_timestamp()`, and that choice is deliberate. `ratelimit.enforce` commits before
    # `rotate` runs, so this SELECT *opens* the transaction and the timestamp is taken when
    # the statement is issued, BEFORE it blocks on the row lock. That dates the presenter's
    # ARRIVAL rather than the length of its wait, which is exactly the question the grace
    # window asks — a loser stuck behind a slow winner stays inside the window. The bias is
    # therefore towards gracing, and it is bounded: a transaction cannot begin before it
    # begins, so a rotation that happened well before this request started still measures
    # old and is still rejected. ⚠️ The one way to widen that bias is to do other database
    # work in this transaction before calling `rotate` — that would age `now()` by however
    # long the work takes. Don't.
    found = session.execute(
        select(AuthSession, func.now())
        .where(AuthSession.token_hash == presented_digest)
        .with_for_update()
    ).one_or_none()
    if found is None:
        raise RefreshRejectedError("unknown refresh token")
    row: AuthSession = found[0]
    # `func.now()` is `Any` to mypy, so this annotation is where the TIMESTAMPTZ claim is
    # made. `Base.type_annotation_map` pins every `datetime` column to `timezone=True`, and
    # Postgres `now()` is `timestamptz`, so both sides of the comparison below are aware.
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
