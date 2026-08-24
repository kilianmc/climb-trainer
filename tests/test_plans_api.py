"""`POST /api/plans/preview` against real Postgres — the endpoint, not the algorithm.

The generator itself is covered DB-free by the six `test_planner_*.py` files. What only a
database can test is the half this endpoint exists for, and it earns three of CLAUDE.md's
"write tests for" bullets:

- **core user paths.** Opening `/plan` with a finished profile is the product promise, and
  the profile-to-`PlannerInput` mapping is the whole of it: four nullable columns, two grade
  ids resolved to ordinals, two aspect ids resolved to keys, and the open injuries. Every one
  of those is SQL, so a unit test of the handler would exercise none of it.
- **the demo path.** The demo mount is why the endpoint is a non-writing POST at all, and
  the `DEMO_WRITE_EXEMPT_ROUTES` entry is a hole in "demo mode is read-only" that has to be
  demonstrated to be the hole it claims to be.
- **anything that can lose user data — inverted.** The last test counts `plan`, `mesocycle`
  and `planned_session` rows after a successful preview and asserts all three are still
  zero. That is the behavioural proof that "writes nothing" is true, rather than three
  arguments that it ought to be.

Deliberately NOT here: any assertion about which exercise landed in which block, or how a
phase is structured. That is the domain's, it is tested there, and restating it would break
this file on every content edit.

**Skips without `DATABASE_URL`** (`conftest.py`); CI runs it for real.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.auth.tokens import issue_access_token
from server.domain.grades import GradeSystemKey
from server.domain.planner import REFUSAL_MESSAGES, RefusalReason
from server.domain.planner.periodisation import week_count_for
from server.models import (
    ClimbingAspect,
    Grade,
    GradeSystem,
    Mesocycle,
    Plan,
    PlannedSession,
)
from server.seed import DEMO_USER_ID

_EMAIL = "planner@example.com"
_PASSWORD = "a-long-enough-passphrase"

# Monday, Wednesday, Saturday — bits 0, 2 and 5. Three days for three sessions, so the
# weekday chooser has exactly one answer.
_MON_WED_SAT = 0b0100101

# The demo profile's own numbers, from `server/seed.py`. Two rungs of French sport gap.
_DEMO_WEEK_COUNT = 16


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    """A registered account's bearer header. Registration mints one, so this is one call."""
    response = api_client.post(
        "/api/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD, "invite_code": invite_code},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def demo_auth() -> dict[str, str]:
    """A demo-scope bearer for the seeded demo account.

    Minted here rather than through `POST /api/auth/demo` so the test is about the preview
    and not about the mint, and because the secret fixture has not run at collection time.
    """
    return {"Authorization": f"Bearer {issue_access_token(DEMO_USER_ID, 'demo').token}"}


def _french_grade_id(session: Session, label: str) -> int:
    """A French rung by its label. Exact match — `7A` is Font and `7a` is French."""
    grade_id = session.scalar(
        select(Grade.id)
        .join(GradeSystem, Grade.grade_system_id == GradeSystem.id)
        .where(GradeSystem.key == GradeSystemKey.FRENCH.value, Grade.label == label)
    )
    assert grade_id is not None, f"no seeded French {label}"
    return grade_id


def _aspect_id(session: Session, key: str) -> int:
    aspect_id = session.scalar(select(ClimbingAspect.id).where(ClimbingAspect.key == key))
    assert aspect_id is not None, f"no seeded {key} aspect"
    return aspect_id


def _complete_profile(
    client: TestClient, auth: dict[str, str], session: Session, **overrides: object
) -> None:
    """Every answer the generator reads, so a test can remove exactly one of them."""
    body: dict[str, object] = {
        "current_grade_id": _french_grade_id(session, "6c"),
        "target_grade_id": _french_grade_id(session, "7a+"),
        "sessions_per_week": 3,
        "available_weekdays": _MON_WED_SAT,
        "strength_aspect_id": _aspect_id(session, "endurance"),
        "weakness_aspect_id": _aspect_id(session, "finger_strength"),
    }
    body.update(overrides)
    # The target grade has to land before the current one is judged against it, and PATCH
    # takes them together, so one call is also the shortest path.
    response = client.patch("/api/profile", json=body, headers=auth)
    assert response.status_code == 200, response.text


def _preview(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post("/api/plans/preview", json={}, headers=headers)


def test_a_complete_profile_gets_a_plan_whose_length_follows_the_GRADE_GAP(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The product promise: grades in, a dated phase-structured plan out.

    `week_count` is asserted against `week_count_for(grade_gap)` rather than a literal, so
    this test proves the endpoint *plumbs the gap through* — the gap table itself is pinned
    literally in `tests/test_planner_periodisation.py`, and asserting it twice would make a
    deliberate change to it fail in two places with one of them lying about the cause.
    """
    _complete_profile(api_client, auth, db_session)

    response = _preview(api_client, auth)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grade_gap"] > 0
    assert body["week_count"] == week_count_for(body["grade_gap"])
    assert body["generator_version"] == body["generator_input"]["generator_version"]
    # The dates are the half no unit test of the domain can prove reached the wire.
    assert body["start_date"] == body["mesocycles"][0]["microcycles"][0]["start_date"]
    weeks = [
        microcycle["week_no"]
        for mesocycle in body["mesocycles"]
        for microcycle in mesocycle["microcycles"]
    ]
    assert weeks == list(range(1, body["week_count"] + 1))
    # Both ids are the ROUTE's to fill: the domain holds ordinals and never sees a grade id.
    assert body["target_grade_id"] is not None
    assert body["current_grade_id"] is not None


def test_an_unanswered_training_frequency_refuses_with_its_own_frozen_sentence(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """NULL `sessions_per_week` is a refusal, never a default.

    CLAUDE.md is explicit that nothing may substitute a fallback here — `3` is a perfectly
    plausible reply, which is what makes an invented one dangerous. The sentence is quoted
    from `REFUSAL_MESSAGES` rather than repeated, because it is signed off and frozen and a
    copy in a test is a copy that can drift.
    """
    _complete_profile(api_client, auth, db_session, sessions_per_week=None)

    response = _preview(api_client, auth)

    assert response.status_code == 422, response.text
    assert (
        response.json()["detail"] == (REFUSAL_MESSAGES[RefusalReason.SESSIONS_PER_WEEK_UNANSWERED])
    )


def test_no_target_grade_refuses_rather_than_inventing_a_goal(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """A brand-new account has no `user_profile` row at all, and that is the same answer.

    "Never asked" and "asked and unanswered" are the same fact for a plan built around a
    target grade, and the endpoint must not create the row on the way past — the touch-on-read
    write is the accident that defeats every other compute rule in CLAUDE.md.
    """
    response = _preview(api_client, auth)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == REFUSAL_MESSAGES[RefusalReason.NO_TARGET_GRADE]


def test_a_demo_token_is_not_forbidden(api_client: TestClient, demo_auth: dict[str, str]) -> None:
    """The `DEMO_WRITE_EXEMPT_ROUTES` entry, proved rather than asserted.

    A 403 here is the failure the entry exists to prevent, and it is the failure that would
    make the portfolio's whole point — an interactive demo mount — a dead screen.
    """
    response = _preview(api_client, demo_auth)

    assert response.status_code != 403, response.text


def test_the_demo_profile_is_plannable(api_client: TestClient, demo_auth: dict[str, str]) -> None:
    """`server/seed.py`'s demo profile yields a real 16-week plan.

    The 16 is pinned as a literal on purpose, unlike the test above: it is Kilian's decision
    (French 6a to 6b, two rungs, four blocks) and the length of the one plan a portfolio
    visitor ever sees. A content or gap-table change that reshaped it should have to delete
    this number deliberately.
    """
    response = _preview(api_client, demo_auth)

    assert response.status_code == 200, response.text
    assert response.json()["week_count"] == _DEMO_WEEK_COUNT


def test_the_response_is_never_cached(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The header, asserted on a real response and not only as a constant.

    `tests/test_plans_contract.py` pins the string; this proves it is actually sent. Both
    are needed — a constant nothing writes to the response is a comment.
    """
    _complete_profile(api_client, auth, db_session)

    response = _preview(api_client, auth)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"


def test_a_successful_preview_writes_NO_PLAN_ROWS(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The most valuable assertion in this file: "writes nothing", measured.

    Three mechanisms are supposed to guarantee it — the generator's purity lint, a handler
    that issues only `SELECT`s, and `SET LOCAL transaction_read_only` on the demo path — and
    every one of them is an argument. This is the only test that would notice the day
    somebody adds the persist path here instead of in #11b.

    All three tables are counted, because a partial insert is the realistic version of the
    mistake: a `Plan` row with no children is exactly what a half-written write path leaves.
    """
    _complete_profile(api_client, auth, db_session)

    response = _preview(api_client, auth)
    assert response.status_code == 200, response.text

    for model in (Plan, Mesocycle, PlannedSession):
        count = db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, (
            f"{model.__tablename__} holds {count} row(s) after a PREVIEW. The preview must "
            f"not write: persisting a plan is PR #11b, and the demo path would be refused "
            f"by Postgres itself."
        )
