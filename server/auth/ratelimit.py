"""Fixed-window rate limiting, counted in Postgres.

No Redis and no workers: a frozen serverless instance cannot hold a counter, so `rate_limit`
is the only shared durable place. `enforce_all()` counts every one of a route's buckets in ONE
`INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING bucket` — atomic, so there is no
read-then-write race, and one round trip however many dimensions a route has. The key is
`"<rule>:<hmac-sha256(AUTH_SECRET, subject)>"`: no IP and no email is ever stored, and keyed
HMAC rather than a bare hash because both spaces are small enough to enumerate offline.
`LOGIN_ACCOUNT` keys on the attempted email, so rotating IPs does not help. Accepted trade: an
attacker can hold a real user at 429. It self-heals within the hour and nothing here disables
an account — a rate limit, never a lockout. The 429 is identical whichever bucket tripped and
the email counter increments for addresses that do not exist, so it is no existence oracle.

⚠️ **This is an ABUSE control, NOT a compute-budget control** (the original plan claimed
otherwise). `enforce()` upserts and COMMITS before it looks at the limit, so a rejected
request has already written and already restarted Neon's five-minute window. Do not invert it
to check-then-count: that is the race above, and rejected attempts must be counted or the
limit is trivially evaded. Awake-time protection sits at the EDGE, in a Vercel WAF rule on
`/api/auth/*`, outside this repository. `purge()` is called opportunistically from
`enforce_all()` because a cron that pings Neon is the ~730 CU-hr/month mistake.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from fastapi import HTTPException, Request, status
from sqlalchemy import CursorResult, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from server.models import RateLimit
from server.settings import auth_secret


@dataclass(frozen=True, slots=True)
class Rule:
    """`limit` requests per `window`, per subject, per `name`.

    The *subject* is whatever the rule keys on — a client IP for most of these, the
    attempted email for `LOGIN_ACCOUNT`. `name` keeps the two namespaces apart, so the
    same string used as two different kinds of subject can never share a bucket.
    """

    name: str
    limit: int
    window: timedelta


# Keyed on the client IP: stops one machine.
#
# LOGIN and REFRESH are deliberately GENEROUS, and lowering them buys nothing. Both are a
# single write, so the Neon cost of an attempt is the same five-minute wake whether we
# allow 3 of them or 30 — the limit does not change the cost, only who it inconveniences.
# Cutting LOGIN would punish a person mistyping their password on a phone and would not
# slow a real attacker, who is bounded by LOGIN_ACCOUNT and by the edge rule instead.
# If you are here to "tighten security" by lowering these: it does not work. Read the
# ABUSE-control section above first.
LOGIN: Final = Rule("login", limit=10, window=timedelta(minutes=15))
REFRESH: Final = Rule("refresh", limit=30, window=timedelta(hours=1))

# REGISTER is the exception, and it is tight (3/hour, down from 5 on 2026-08-13). A real
# person registers ONCE, so a low ceiling costs a legitimate user nothing, while each
# attempt is a genuine expense: a full argon2 hash (46 MiB, ~1 vCPU) plus a row.
REGISTER: Final = Rule("register", limit=3, window=timedelta(hours=1))

# There is deliberately NO `DEMO` rule. It was removed on 2026-08-13 — do not add one
# back, and do not read its absence as an oversight.
#
# It could not work. Enforcing a limit here is itself a Postgres write, so a REJECTED
# demo request restarted Neon's five-minute autosuspend window exactly as an accepted one
# did: the control cost the very resource it existed to protect. The arithmetic, so nobody
# has to re-derive it — Neon Free is 100 CU-hr/month at the 0.25 CU floor, i.e. **400
# awake-hours** against a 730-hour month, and autosuspend is fixed at 5 minutes and is
# NOT configurable on Free (paid plans can only disable it, not shorten it). A bot
# trickling **one request per minute** therefore keeps the compute awake 100% of the time,
# costs ~182 CU-hr/month, and exhausts the allowance on its own — while sitting
# comfortably inside any limit this table was permitted to configure.
#
# `POST /api/auth/demo` now issues ZERO SQL (no `Session` in its signature at all), so
# hammering it costs Vercel invocations and CPU but **no Neon time**. Its rate limit lives
# at the edge instead, as a **Vercel WAF rule on `/api/auth/*`** — which is OUTSIDE this
# repository. See the warning in CLAUDE.md's compute-budget section: deleting that WAF
# rule silently removes the only rate limit on demo-token minting, and nothing in the
# codebase will hint at it.

# Keyed on the ATTEMPTED EMAIL, login only: stops an attacker spread across many
# machines, which the per-IP rule cannot. 30/hour is deliberately generous — see "Two
# dimensions on login" in the module docstring for the number and for the accepted
# trade-off (an attacker can hold a real user at 429; it self-heals hourly and is never
# an account lockout).
LOGIN_ACCOUNT: Final = Rule("login_account", limit=30, window=timedelta(hours=1))

# Rows older than this are dead weight; the newest window they could belong to closed
# long ago. Generous relative to the longest window above (1 h).
RETENTION: Final = timedelta(days=1)

_PURGE_INTERVAL_SECONDS: Final = 3600.0

# Soft throttle for the opportunistic purge. Process-local by nature — a warm instance
# purges at most hourly, a fleet of cold starts purges a little more often. Both are
# fine; the point is only that nothing here runs on a timer.
_last_purge_at = 0.0


def client_ip(request: Request) -> str:
    """The client address, used ONLY as HMAC input — never stored, never echoed.

    **On Vercel this header is platform-set and NOT client-controllable.** Vercel's
    request-headers reference is explicit about it:

    > If you are trying to use Vercel behind a proxy, we currently overwrite the
    > `X-Forwarded-For` header and do not forward external IPs. This restriction is in
    > place to prevent IP spoofing.

    So a value supplied by the caller is discarded and replaced with the real client IP,
    and there is exactly **one** entry — which means leftmost and rightmost are the same
    string and the choice between them does not exist. `x-real-ip` and
    `x-vercel-forwarded-for` are documented as identical to this header. Verified against
    <https://vercel.com/docs/headers/request-headers>, 2026-08-13. The `split(",")[0]` is
    therefore defensive, not load-bearing.

    Two things that are true and worth knowing, neither of which is a change to make:

    - **A proxy that this project puts in FRONT of Vercel** could overwrite the header
      after Vercel set it. `x-vercel-forwarded-for` is the documented escape hatch for
      that case. There is no such proxy here, so this is a pointer, not a TODO.
    - **Locally** (`uvicorn` with nothing in front) the header is whatever the client
      sends, so the limiter is trivially bypassable in development. That is not a threat
      — it is just a reason never to read local behaviour as production behaviour.

    The value is never reflected in a response (CLAUDE.md forbids that outright) and
    never reaches a query as anything but HMAC input.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = request.client
    return client.host if client is not None else "unknown"


def bucket_key(rule: Rule, subject: str) -> str:
    """`"<rule>:<hmac(subject)>"`. A plain value, bound as a parameter — not SQL text.

    The subject is an IP for the IP-keyed rules and the **normalised** (stripped,
    lowercased) email for `LOGIN_ACCOUNT`. Normalising is the caller's job and it is not
    optional: `Kilian@x.com` and `kilian@x.com` would otherwise get separate budgets, and
    the effective limit multiplies by the number of case variants an attacker can type.
    """
    fingerprint = hmac.new(
        auth_secret().encode("utf-8"),
        subject.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{rule.name}:{fingerprint}"


def window_start_for(rule: Rule, now: datetime) -> datetime:
    """Floor `now` to the start of its fixed window.

    Fixed windows, not a sliding log: a sliding window needs a row per request, and this
    table must stay tiny. The known weakness is a burst straddling a boundary allowing up
    to 2x the limit briefly, which is an acceptable trade for one row per client per
    window.
    """
    seconds = int(rule.window.total_seconds())
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


def purge(session: Session, older_than: timedelta = RETENTION) -> int:
    """Delete finished windows. Returns the number of rows removed. Does not commit."""
    cutoff = datetime.now(UTC) - older_than
    # See the note in refresh.revoke_family: DML always produces a CursorResult, but
    # `Session.execute` is only typed as `Result`.
    result = cast(
        CursorResult[Any],
        session.execute(delete(RateLimit).where(RateLimit.window_start < cutoff)),
    )
    return result.rowcount


def enforce(session: Session, request: Request, rule: Rule) -> None:
    """Count this request against one IP-keyed rule. Convenience over `enforce_all`."""
    enforce_all(session, (rule, client_ip(request)))


def enforce_all(session: Session, *checks: tuple[Rule, str]) -> None:
    """Count this request against every `(rule, subject)` pair, in ONE statement.

    Raises a single generic 429 if **any** bucket is over its limit, with `Retry-After`
    taken from whichever tripped window ends **last** — so a client that waits it out is
    clear of all of them at once. The response says nothing about which bucket tripped or
    how many there are: on login one of them is keyed by the attempted email, and naming
    it would turn the 429 into an account-existence oracle.

    **This commits.** The counters have to survive whatever the request does next — if
    they were left to the endpoint's transaction, every rejected login would roll back its
    own increment and the limiter would never trip. Call it before any other work in the
    handler, so committing here cannot truncate a half-finished write.
    """
    if not checks:  # pragma: no cover - no caller does this; guards the empty VALUES
        return

    now = datetime.now(UTC)

    # Keyed by bucket. Deduplicated because Postgres refuses an ON CONFLICT DO UPDATE
    # that would touch the same row twice in one statement ("cannot affect row a second
    # time"); distinct rules already produce distinct buckets, so this only guards
    # against a caller passing the same pair twice.
    planned: dict[str, tuple[Rule, datetime]] = {
        bucket_key(rule, subject): (rule, window_start_for(rule, now)) for rule, subject in checks
    }

    insert_statement = pg_insert(RateLimit).values(
        [
            {"bucket": bucket, "window_start": window_start, "count": 1}
            for bucket, (_, window_start) in planned.items()
        ]
    )
    counted = insert_statement.on_conflict_do_update(
        index_elements=[RateLimit.bucket, RateLimit.window_start],
        # Renders `count = rate_limit.count + 1`, evaluated by Postgres inside the
        # statement — so two concurrent requests cannot both read the same old value.
        set_={"count": RateLimit.count + 1},
    ).returning(RateLimit.bucket, RateLimit.count)
    # RETURNING order is not guaranteed, which is why `bucket` comes back with the count:
    # each count has to be compared against its OWN rule's limit.
    results = session.execute(counted).all()

    exceeded_until: list[datetime] = []
    opened_a_window = False
    for bucket, count in results:
        rule, window_start = planned[bucket]
        if count == 1:
            opened_a_window = True
        if count > rule.limit:
            exceeded_until.append(window_start + rule.window)

    if opened_a_window:
        _maybe_purge(session)
    session.commit()

    if exceeded_until:
        retry_after = max(1, int((max(exceeded_until) - now).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def _maybe_purge(session: Session) -> None:
    global _last_purge_at
    now = time.monotonic()
    if now - _last_purge_at < _PURGE_INTERVAL_SECONDS:
        return
    _last_purge_at = now
    purge(session)
