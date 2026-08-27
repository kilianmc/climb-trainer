"""`GET /api/vocabulary` against real Postgres.

A **core user path**: it is the input to every picker onboarding renders, so an empty or
reordered list is a step nobody can complete, and neither failure shows up anywhere else.
Nothing in the local gate can cover it — five queries against seeded reference data — so these
**skip without `DATABASE_URL`** and CI runs them for real.

Deliberately NOT tested: the display text of individual rows. That is seed content, owned by
`tests/test_seed.py`; asserting "Hangboard" here would break on a copy edit and catch nothing.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.domain.grades import GRADE_SYSTEMS, Discipline
from server.domain.vocabulary import (
    CLIMBING_ASPECTS,
    EQUIPMENT,
    INJURY_AREAS,
    ActivityKind,
    AscentStyle,
    Phase,
    ProtocolKind,
    SessionStatus,
)
from server.models import Grade
from server.vocabulary.routes import _CACHE_CONTROL

_EMAIL = "vocabulary@example.com"
_PASSWORD = "a-long-enough-passphrase"


@pytest.fixture
def vocabulary(api_client: TestClient, invite_code: str) -> dict[str, Any]:
    registered = api_client.post(
        "/api/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD, "invite_code": invite_code},
    )
    assert registered.status_code == 201, registered.text
    response = api_client.get(
        "/api/vocabulary",
        headers={"Authorization": f"Bearer {registered.json()['access_token']}"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == _CACHE_CONTROL
    body: dict[str, Any] = response.json()
    return body


def test_it_is_authenticated_like_everything_else(api_client: TestClient) -> None:
    """Deny-by-default. Reference data is not a reason to open a route."""
    assert api_client.get("/api/vocabulary").status_code == 401


@pytest.mark.parametrize(
    ("field", "specs"),
    [
        pytest.param("climbing_aspects", CLIMBING_ASPECTS, id="climbing_aspects"),
        pytest.param("equipment", EQUIPMENT, id="equipment"),
        pytest.param("injury_areas", INJURY_AREAS, id="injury_areas"),
    ],
)
def test_a_lookup_table_arrives_whole_and_in_SEED_ORDER(
    field: str, specs: tuple[Any, ...], vocabulary: dict[str, Any]
) -> None:
    """The order IS the display order, and it is why `sort_order` is not in the payload.

    The endpoint sorts by `sort_order` and the client iterates the array as it arrives, so
    a lost `ORDER BY` reorders every picker in the app with nothing else failing. This is
    the assertion that was missing: it compares against the ORDER DECLARED IN
    `server/domain/vocabulary.py`, which is the source both the seed and the UI derive
    from — not against whatever the database happened to return.
    """
    rows = vocabulary[field]
    assert [row["key"] for row in rows] == [spec.key for spec in specs]
    # Ids are real and usable as request input; nothing here is a placeholder.
    assert all(isinstance(row["id"], int) and row["id"] > 0 for row in rows)


def test_the_grade_ladder_arrives_grouped_by_system_and_ascending(
    vocabulary: dict[str, Any], db_session: Session
) -> None:
    """Grades are ordered `(grade_system_id, ordinal)`, so a picker can render them as-is.

    Asserted against the database rather than against a hand-written list: the ladder's
    CONTENTS belong to `tests/test_grades.py`, and what matters here is that the endpoint
    returns all of it, in the order a `<select>` needs.
    """
    expected = db_session.execute(
        select(Grade.id).order_by(Grade.grade_system_id, Grade.ordinal)
    ).all()
    assert [row["id"] for row in vocabulary["grades"]] == [row.id for row in expected]

    systems = vocabulary["grade_systems"]
    # ⚠️ **This assertion was latently wrong until `0006` (issue #55).** The endpoint used to
    # order by the SERIAL `id`, so declaration order and insert order were the same thing only
    # on a fresh database — which CI always is. Add a system mid-tuple and this test kept
    # passing while dev and production rendered the new one last. It now goes through
    # `grade_system.sort_order`, like every sibling lookup table, so it is insulated the same
    # way `test_a_lookup_table_arrives_whole_and_in_SEED_ORDER` always was.
    assert [entry["key"] for entry in systems] == [spec.key.value for spec in GRADE_SYSTEMS]
    # The discipline is what makes the boulder/rope split selectable in the UI.
    assert {entry["discipline"] for entry in systems} == {member.value for member in Discipline}


def test_every_grade_points_at_a_system_in_the_same_payload(vocabulary: dict[str, Any]) -> None:
    """One request has to be enough: the client joins these two arrays by id itself.

    If a grade referenced a system the response omitted, the picker would render an empty
    scale — and no test of either array on its own would notice.
    """
    system_ids = {entry["id"] for entry in vocabulary["grade_systems"]}
    assert {grade["grade_system_id"] for grade in vocabulary["grades"]} <= system_ids
    assert vocabulary["grades"], "the ladder came back empty — is the seed running?"


def test_the_equipment_list_offers_an_outdoor_option_per_discipline(
    vocabulary: dict[str, Any],
) -> None:
    """The seeded half of the outdoor dead-end fix, asserted where the client sees it.

    `tests/test_equipment_vocabulary.py` guards the domain tuple DB-free; this proves the
    rows are actually seeded and actually reach the picker, which is the property an
    outdoor-only climber depends on. Both exist because the tuple and the table can drift:
    the seed upserts on `key` and never deletes, so a renamed key adds a row rather than
    replacing one.
    """
    keys = {row["key"] for row in vocabulary["equipment"]}
    assert {"outdoor_boulders", "outdoor_routes"} <= keys


def test_the_closed_vocabularies_are_the_python_enums(vocabulary: dict[str, Any]) -> None:
    """Values, not member names, and in declaration order.

    `tests/test_vocabulary_contract.py` checks these same lists against the generated
    TypeScript; this checks what the endpoint actually serialises, which is the third copy
    and the one a client really receives.
    """
    assert vocabulary["enums"] == {
        "disciplines": [member.value for member in Discipline],
        "activity_kinds": [member.value for member in ActivityKind],
        "ascent_styles": [member.value for member in AscentStyle],
        "protocol_kinds": [member.value for member in ProtocolKind],
        "phases": [member.value for member in Phase],
        "session_statuses": [member.value for member in SessionStatus],
    }


def test_it_is_the_same_for_every_user(
    api_client: TestClient, invite_code: str, vocabulary: dict[str, Any]
) -> None:
    """The premise the `Cache-Control` rests on, asserted rather than assumed.

    `private, max-age=3600` with no `Vary: Authorization` is only safe while this body
    carries nothing user-scoped — a browser cache keys on the URL, so two accounts sharing
    one browser share the entry. If a future field makes this fail, that header has to
    change in the same commit.
    """
    other = api_client.post(
        "/api/auth/register",
        json={
            "email": "someone-else@example.com",
            "password": _PASSWORD,
            "invite_code": invite_code,
        },
    )
    assert other.status_code == 201, other.text
    response = api_client.get(
        "/api/vocabulary",
        headers={"Authorization": f"Bearer {other.json()['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json() == vocabulary
