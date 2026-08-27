"""The `/api/library` CDN contract, with NO database — so it runs in the local gate.
One rule, and it is a **security** rule: `/api/library` is user-independent, permanently. It is
served from a shared CDN keyed on URL alone with **no `Vary: Authorization`**, so any per-user
field would be served out of one user's cache entry to another and **no test would catch it** — the
leak happens between two requests, inside an intermediary this repo does not run. Per-user state
about exercises (the "I don't have this gear" flag, personal bests, anything derived from a
`user_*` table) goes on a separate endpoint that is never CDN-cached. **Adding a user-scoped field
to this response is a security change, not a feature change**, and PR #11's equipment flag is
exactly the field that would spring it.
So the guard cannot be behavioural: it is a **pinned field list**, red on the diff that adds the
field. The names are written out as literals rather than derived from the model — a control
assembled from the constant it tests would cheerfully confirm a typo to itself.
"""

from server.auth.deps import PUBLIC_ROUTES
from server.library.routes import _CACHE_CONTROL, ExerciseLibraryResponse, ExerciseOut, router

# Every field the library response may carry. **All of them are properties of the
# EXERCISE**; not one is a property of the reader. Adding a name here is claiming that
# every user of the app may be served this value out of another user's cache entry.
_EXERCISE_FIELDS = frozenset(
    {
        "id",
        "key",
        "name",
        "climbing_aspect_id",
        "protocol_kind",
        "discipline",
        "instructions",
        "substitution_hint",
        "media_url",
        "progression_of_id",
        "regression_of_id",
        "equipment_ids",
        "contraindicated_injury_area_ids",
        "prescriptions",
    }
)


def test_the_response_carries_nothing_user_scoped() -> None:
    """The pinned field list. Read this file's docstring before changing it."""
    assert set(ExerciseOut.model_fields) == _EXERCISE_FIELDS, (
        "the /api/library response shape changed. If the new field is a property of the "
        "USER rather than of the exercise, it must not be here at all — this response is "
        "served from a shared CDN with no Vary: Authorization, so one user's value would "
        "be handed to the next. Put it on a separate, uncached endpoint."
    )
    assert set(ExerciseLibraryResponse.model_fields) == {"exercises"}


def test_retired_at_is_not_in_the_payload() -> None:
    """Named explicitly, because it is a column on the row the endpoint reads.

    `Exercise.retired_at` is a seed-time curation record, not display data: the client has
    no use for it and a served exercise always has it NULL by construction. Spelling the
    exclusion out means the next person to widen `ExerciseOut` from the model has to delete
    a test with a reason in it.
    """
    assert "retired_at" not in ExerciseOut.model_fields


def test_the_cache_control_header_is_the_immutable_per_deploy_one() -> None:
    """A year, shared, immutable — and `?v=<buildId>` is what makes that safe.

    Pinned as an exact string because each half is load-bearing: `public` puts it in the
    CDN (that is the point — Neon Free gives ~400 awake hours and every origin read costs a
    five-minute window), `s-maxage` is the shared-cache lifetime, and `immutable` stops
    revalidation. Weakening any of it silently moves library reads back onto the database.
    """
    assert _CACHE_CONTROL == "public, s-maxage=31536000, immutable"


def test_the_route_is_not_public() -> None:
    """Auth gates who can cause a cache MISS, and a miss is a Neon wake.

    Not a privacy argument — the body is identical for everyone. It is a compute argument,
    and it is the same one that made `POST /api/auth/demo` issue zero SQL: an
    unauthenticated cacheable endpoint lets a bot keep the database awake on every cache
    eviction. `PUBLIC_ROUTES` is the only way to open a route, in a diff, on purpose.
    """
    assert router.prefix == "/api/library"
    assert not any(path.startswith("/api/library") for _, path in PUBLIC_ROUTES)
