"""The `/api/plans/preview` cache and demo contract, with NO database — so it runs locally.

The `/api/library` bullet in CLAUDE.md's testing policy, applied to its sibling. That
endpoint needs a pinned guard because a shared-cache leak is invisible to behaviour; this
one needs the mirror-image guard, because the thing that would go wrong is the response
becoming *cacheable*. `/api/library` is `public, immutable` on a shared CDN precisely
because its body is identical for everyone. This body is built from one climber's grades,
availability, declared weakness and **open injuries**, so a shared or persisted cache entry
is a cross-account leak — and, exactly as with the library, no behavioural test in this
repo can see it happen, because it happens in an intermediary this repo does not run.

So three literals are pinned here, all DB-free:

1. this endpoint's header, which must forbid both the CDN and the disk;
2. **the library's header, unchanged.** The two rules differ on purpose and the realistic
   failure is somebody "harmonising" them while adding this one;
3. the `DEMO_WRITE_EXEMPT_ROUTES` entry that lets the demo mount call it — present, and
   absent from `PUBLIC_ROUTES`, which are two different claims.

Nothing here needs Postgres, so it fails in the local gate rather than only in CI.
"""

from server.auth.deps import DEMO_WRITE_EXEMPT_ROUTES, PUBLIC_ROUTES
from server.library.routes import _CACHE_CONTROL as _LIBRARY_CACHE_CONTROL
from server.plans.routes import _CACHE_CONTROL, router

_PREVIEW = ("POST", "/api/plans/preview")


def test_the_preview_is_never_cached_anywhere() -> None:
    """`private, no-store`, and both halves are load-bearing.

    `private` keeps it out of the shared CDN, which is the cross-account leak.
    `no-store` keeps it off the browser's disk too — the same argument that keeps
    `runtimeCaching` off `/api` in the service worker: authenticated JSON in Cache Storage
    is not scoped to a session and survives logout, and nothing in the app clears it.
    """
    assert _CACHE_CONTROL == "private, no-store"


def test_the_library_cache_rule_is_untouched() -> None:
    """The sibling's header, pinned here as well as in `test_library_contract.py`.

    Not redundant: the two rules are opposites and this file is where the *pair* is
    asserted. A change that made the preview `public` by copying the library's constant, or
    made the library `private` by copying this one, is one edit either way.

    (There is deliberately no `_CACHE_CONTROL != _LIBRARY_CACHE_CONTROL` here: both are
    `Final` literals, so mypy decides that comparison statically and rejects it as
    non-overlapping. The two literal assertions say the same thing and are checkable.)
    """
    assert _LIBRARY_CACHE_CONTROL == "public, s-maxage=31536000, immutable"


def test_the_demo_mount_may_call_it() -> None:
    """The one route besides `POST /api/auth/demo` a demo token may POST to.

    Justified at the constant in `server/auth/deps.py`: it writes nothing, enforced by the
    domain's purity rule, by the handler issuing only `SELECT`s, and by
    `SET LOCAL transaction_read_only` on the demo path. Without the entry the demo mount
    403s on the one screen the portfolio exists to show.
    """
    assert _PREVIEW in DEMO_WRITE_EXEMPT_ROUTES


def test_the_exemption_did_not_also_make_it_public() -> None:
    """Two different claims, and conflating them is how an endpoint opens by accident.

    "A demo token may write here" is not "no token is needed here". A public preview would
    let an unauthenticated caller run a Postgres read at will, which is the Neon wake that
    `POST /api/auth/demo` was rewritten to zero-SQL to remove.
    """
    assert router.prefix == "/api/plans"
    assert not any(path.startswith("/api/plans") for _, path in PUBLIC_ROUTES)
