"""Fixed-window rate limiting, counted in Postgres.

## Why the database

There is no Redis and there are no background workers here. A serverless function is
frozen between invocations and may be a different instance every time, so an in-process
counter is both per-instance and reset by every cold start — which is to say, not a rate
limit. The `rate_limit` table is the only shared, durable place available.

## One statement, no race — and one statement for ALL of a route's buckets

`INSERT ... ON CONFLICT (bucket, window_start) DO UPDATE SET count = rate_limit.count + 1
RETURNING bucket, count` — a single atomic round trip. A read-then-write would let two
concurrent requests both see `count = limit - 1` and both proceed, which is exactly the
window a credential-stuffing script would find. Built with SQLAlchemy constructs and
bound parameters; no SQL is assembled from strings anywhere in this module.

`enforce_all()` puts **several buckets in that same statement** as multiple VALUES rows.
That is the point of its existence: a route can be limited along two independent
dimensions for the cost of one round trip and one commit, so adding a control costs no
extra latency and no extra Neon wake-up. `RETURNING bucket` is what lets each returned
count be matched back to its own rule — row order is not guaranteed.

## The bucket key never contains an IP or an email

The key is `"<rule>:<hmac-sha256(AUTH_SECRET, subject)>"`, where the subject is a client
IP for the IP-keyed rules and the **normalised email** for the account-keyed one. We do
not need to know anyone's address — the only question ever asked is "is this bucket
hot?" — so storing either in the clear would be collecting personal data for no purpose.
Keyed HMAC rather than a bare hash, because the IPv4 space is small enough to enumerate
offline in seconds and so is a list of likely email addresses.

## Two dimensions on login: source AND target

The per-IP bucket stops one machine. It does nothing against an attacker spread across
many addresses, because each address starts with a fresh budget. `LOGIN_ACCOUNT` keys on
**the email being attempted**, so the limit binds to the *target* of the attack and
rotating IPs does not help.

**The trade-off, stated plainly because it must not be quietly omitted:** a determined
attacker can hold a real user's login at 429 by deliberately burning that user's bucket.
That is accepted. The alternative is unlimited distributed guessing, which is worse; the
window **self-heals within the hour** with no admin action; and this is a **rate limit,
never an account lockout** — nothing here writes state that disables an account, which is
exactly why OWASP moved off lockout policies in the first place.

**30 per hour** is the chosen number: high enough that a real person mistyping their
password over and over, on several devices, never reaches it, and low enough that
distributed guessing against one account is pointless.

A 429 from either bucket is identical, and **the email counter increments for every
address attempted, existing or not** — so the response can never be used to learn
whether an account exists.

## This is an ABUSE control. It is NOT a compute-budget control.

Stated plainly because the original plan claimed otherwise, and the code shows why the
claim was wrong: `enforce()` performs the upsert **and commits** before it looks at the
limit. A request that receives a 429 has therefore already written to Postgres, and
Neon's five-minute autosuspend timer restarts on that write exactly as it would on a
successful call. A script hammering `/api/auth/demo` keeps the database awake at the
same rate whether it is being rejected or not.

Do not "fix" that by checking before counting. Reading the counter and then incrementing
it reintroduces the read-then-write race described above, which is a worse bug, and
rejected attempts genuinely have to be counted or the limit is trivially evaded.

What this module *does* buy: it stops credential stuffing against `login` and bulk
address probing against `register`. That is worth having, and it is all it is for.

**Real protection for unauthenticated endpoints sits at the edge**, where a request never
reaches the function or the database at all — a **Vercel WAF rule on `/api/auth/*`**.
That is the control the compute budget actually depends on, it lives outside this
repository, and CLAUDE.md carries the warning about deleting it. This table is not a
substitute for it.

The endpoint that made this most obvious — `POST /api/auth/demo` — was the one rule
removed outright rather than left in place looking protective. See the comment where the
rules are defined.

## Which routes

`login` and `register` are the obvious credential-attack surfaces, and `login` carries
the second, account-keyed bucket described above. `refresh` is bounded because a valid
rotation is a write. **`demo` is not here at all** — see the comment where the rules are
defined for why the rule was deleted rather than kept.

`LOGIN_ACCOUNT` is applied to **login only**, deliberately:

- Not `register` — an address can be registered exactly once, so an account-keyed limit
  there constrains nothing an attacker would want to repeat.
- Not `refresh` or `demo` — neither request carries an email, so there is no target to
  key on.

## Purging

`purge()` deletes windows that are long over. It is called **opportunistically** from
`enforce_all()` — throttled to roughly once an hour per warm instance, and only when a
brand new window is opened — because there is no cron and there must not be one: a
scheduled job that pings Neon is precisely the ~730 CU-hr/month mistake CLAUDE.md
forbids. Slightly late cleanup of a tiny table is a much better trade than a timer.
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
