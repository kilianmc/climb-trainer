"""`GET /api/library` against real Postgres.

Under CLAUDE.md's testing policy this is a **core user path**: it is the whole input to the
exercise browser and, once PR #11 lands, the content behind every prescribed block. Skips
without `DATABASE_URL` (conftest); CI runs it for real against the seeded library.

What is deliberately NOT tested: names, instructions or any individual prescription. That
is content — `tests/test_exercise_library.py` owns its rules and a copy edit must not turn
this file red. What is tested is the **contract**: the shape, the auth treatment, the
caching header, the aspect ordering the UI groups on, the retirement filter, and the one
product property that must survive the round trip (the zero-equipment floor).

The field list and the cache-control string are pinned in `tests/test_library_contract.py`
instead — no database, so the CDN rule is guarded in the local gate too.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.domain.exercises import EXERCISES
from server.library.routes import _CACHE_CONTROL
from server.models import ClimbingAspect, Equipment, Exercise

_EMAIL = "exercises@example.com"
_PASSWORD = "a-long-enough-passphrase"
# Stands in for `web/src/buildId.ts`'s value. Any string the client could send; the point
# of the parameter is that the server never looks at it.
_BUILD_ID = "0123456789ab"


@pytest.fixture
def library(api_client: TestClient, invite_code: str) -> list[dict[str, Any]]:
    registered = api_client.post(
        "/api/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD, "invite_code": invite_code},
    )
    assert registered.status_code == 201, registered.text
    # `?v=` exactly as the client sends it. The response must not depend on it — see
    # `test_the_cache_buster_does_not_change_the_body` below.
    response = api_client.get(
        f"/api/library?v={_BUILD_ID}",
        headers={"Authorization": f"Bearer {registered.json()['access_token']}"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == _CACHE_CONTROL
    exercises: list[dict[str, Any]] = response.json()["exercises"]
    return exercises


def test_it_is_authenticated_like_everything_else(api_client: TestClient) -> None:
    """Deny-by-default — and now load-bearing for the COMPUTE budget, not just for privacy.

    The response is `public, s-maxage=31536000, immutable`, so auth is what gates who can
    cause a **cache MISS**, and a cache miss is an origin read and therefore a five-minute
    Neon wake. Opening this route would hand a bot a way to keep the database awake.
    Unauthenticated with and without the cache-buster: `?v=` must not look like a key.
    """
    assert api_client.get("/api/library").status_code == 401
    assert api_client.get("/api/library?v=anything").status_code == 401


def test_the_whole_library_arrives_in_one_response(library: list[dict[str, Any]]) -> None:
    """One endpoint, no list/detail split — so every exercise carries its detail fields."""
    by_key = {exercise["key"]: exercise for exercise in library}
    assert {spec.key for spec in EXERCISES} <= by_key.keys()
    for spec in EXERCISES:
        row = by_key[spec.key]
        assert row["protocol_kind"] == spec.protocol_kind.value
        assert row["discipline"] == (spec.discipline.value if spec.discipline else None)
        assert row["substitution_hint"] == spec.substitution_hint
        assert len(row["equipment_ids"]) == len(spec.equipment_keys)
        assert len(row["contraindicated_injury_area_ids"]) == len(spec.contraindication_keys)
        assert [prescription["phase"] for prescription in row["prescriptions"]] != []


def test_equipment_ids_resolve_to_the_authored_requirements(
    library: list[dict[str, Any]], db_session: Session
) -> None:
    """The ids are the join dimension, so they have to point at the right rows.

    Display text is NOT in this payload by design — the client joins these ids against
    `GET /api/vocabulary`, which it already holds. That only works if the ids are right,
    and an off-by-one join in the router would otherwise be invisible.
    """
    rows = db_session.execute(select(Equipment.id, Equipment.key)).all()
    key_by_id = {row_id: key for row_id, key in rows}
    by_key = {exercise["key"]: exercise for exercise in library}
    for spec in EXERCISES:
        resolved = {key_by_id[row_id] for row_id in by_key[spec.key]["equipment_ids"]}
        assert resolved == set(spec.equipment_keys), spec.key


def test_the_array_is_grouped_by_aspect_in_SORT_ORDER(
    library: list[dict[str, Any]], db_session: Session
) -> None:
    """Grouping arrives as ORDER, so the order is the contract.

    ⚠️ `climbing_aspect.sort_order`, never the serial id: a serial follows INSERT order, so
    ordering by it is declaration order only on a fresh database — the exact trap
    `GET /api/vocabulary` paid for in revision `0006`. A UI walking this once to build its
    sections would silently render the aspects in a different order in production than in
    CI.
    """
    order = {
        aspect_id: position
        for position, aspect_id in enumerate(
            db_session.scalars(select(ClimbingAspect.id).order_by(ClimbingAspect.sort_order)).all()
        )
    }
    positions = [order[exercise["climbing_aspect_id"]] for exercise in library]
    assert positions == sorted(positions), "the payload is not grouped by aspect sort_order"


def test_every_aspect_still_offers_something_with_no_equipment(
    library: list[dict[str, Any]], db_session: Session
) -> None:
    """The zero-equipment floor, end to end through the API.

    The pure test guards the content and the seed test guards the rows; this guards the
    last hop, because an empty `equipment_ids` is what the *client* filters on when it
    decides whether a user can do an exercise.
    """
    gearless = {
        exercise["climbing_aspect_id"] for exercise in library if not exercise["equipment_ids"]
    }
    every_aspect = set(db_session.scalars(select(ClimbingAspect.id)).all())
    assert every_aspect - gearless == set(), (
        "an aspect reached the API with no zero-equipment exercise — a climber with no gear "
        "would get an empty slot in their plan."
    )


def test_the_cache_buster_does_not_change_the_body(
    api_client: TestClient, invite_code: str
) -> None:
    """`?v=` is a cache key and nothing else.

    The CDN keys on the whole URL, so if the body varied with `v` the cache would hold one
    body per build id that ever reached it — and, worse, a handler that read `v` would be
    one refactor away from reading something user-scoped from the query string.
    """
    registered = api_client.post(
        "/api/auth/register",
        json={
            "email": "cachebuster@example.com",
            "password": _PASSWORD,
            "invite_code": invite_code,
        },
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    first = api_client.get("/api/library?v=aaaaaaaaaaaa", headers=headers)
    second = api_client.get("/api/library", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.headers["cache-control"] == second.headers["cache-control"] == _CACHE_CONTROL


def test_a_retired_exercise_is_not_served(
    api_client: TestClient, db_session: Session, invite_code: str
) -> None:
    """Retirement means gone from the library, not merely marked.

    `retired_at` is only ever set because a plan or a logged set points at the row and
    Postgres refused the delete (`server/contentseed.py`) — the row survives so old history
    resolves, and it must not come back through this endpoint or PR #11's generator would
    prescribe an exercise Kilian removed. `retired_at` must also stay OUT of the payload:
    it is a shared-CDN response and every field on it is a field every user gets.
    """
    registered = api_client.post(
        "/api/auth/register",
        json={"email": "retired@example.com", "password": _PASSWORD, "invite_code": invite_code},
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    victim = EXERCISES[0].key
    assert victim in {
        row["key"] for row in api_client.get("/api/library", headers=headers).json()["exercises"]
    }

    db_session.execute(
        update(Exercise).where(Exercise.key == victim).values(retired_at=datetime.now(UTC))
    )
    db_session.flush()

    served = api_client.get("/api/library", headers=headers).json()["exercises"]
    assert victim not in {row["key"] for row in served}
    assert all("retired_at" not in row for row in served)
