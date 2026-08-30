"""`GET /api/sessions/completion` — the DERIVED percentage, against real Postgres.

Partial completion is a query, never a column, so the cases that matter are the ones a column
would get wrong: 2 of 3 parts under `status = 'completed'`, a set with **null `actual_*`
values** (a real completion, from "I did this myself"), a session with no blocks at all, and
the date boundary that makes an unfinished past session `skipped`.

`tests/test_sessions_log.py` owns the write path; the only rows written through the ORM here
are the two states the passage of time would otherwise have to produce. Skips with no
`DATABASE_URL` (`conftest.py`)."""

import itertools
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from server.auth.tokens import issue_access_token
from server.domain.grades import Discipline, GradeSystemKey
from server.domain.planner.selection import BLOCKS_PER_SESSION
from server.domain.vocabulary import ActivityKind, SessionStatus
from server.models import ClimbingAspect, Grade, GradeSystem, PlannedSession
from server.seed import DEMO_USER_ID
from server.sessions.routes import _CACHE_CONTROL, _COMPLETION_SPAN_DAYS

_EMAIL = "completion@example.com"
_OTHER_EMAIL = "completion-other@example.com"
_PASSWORD = "a-long-enough-passphrase"
_TODAY = datetime.now(UTC).date()

# Monday, Wednesday, Saturday — the mask `tests/test_sessions_log.py` uses, for the same reason:
# three sessions a week is the shortest plan that still has parts to leave undone.
_MON_WED_SAT = 0b0100101
_ONE_RUNG_TARGET = "6c+"

# One source address per registration: `ratelimit.REGISTER` is 3/hour/IP. TEST-NET-3, and a
# different range from every other file so two suites cannot share a bucket.
_source_ips = itertools.count(210)


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _EMAIL)


def _register(client: TestClient, invite: str, email: str) -> dict[str, str]:
    """A registered account's bearer header, from its OWN source IP."""
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PASSWORD, "invite_code": invite},
        headers={"x-forwarded-for": f"203.0.113.{next(_source_ips)}"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _french_grade_id(session: Session, label: str) -> int:
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


def _plan(client: TestClient, headers: dict[str, str], session: Session) -> dict[str, Any]:
    """A persisted plan through the REAL endpoints — profile, then `POST /api/plans`."""
    profile = client.patch(
        "/api/profile",
        json={
            "current_grade_id": _french_grade_id(session, "6c"),
            "target_grade_id": _french_grade_id(session, _ONE_RUNG_TARGET),
            "sessions_per_week": 3,
            "available_weekdays": _MON_WED_SAT,
            "strength_aspect_id": _aspect_id(session, "endurance"),
            "weakness_aspect_id": _aspect_id(session, "finger_strength"),
        },
        headers=headers,
    )
    assert profile.status_code == 200, profile.text
    persisted = client.post("/api/plans", json={}, headers=headers)
    assert persisted.status_code == 201, persisted.text
    body: dict[str, Any] = persisted.json()
    return body


def _sessions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Every planned session of the tree, in schedule order."""
    return [
        planned
        for meso in plan["mesocycles"]
        for micro in meso["microcycles"]
        for planned in micro["sessions"]
    ]


def _three_block_sessions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Every session with three distinct-exercise blocks — one per part to leave undone."""
    return [
        planned
        for planned in _sessions(plan)
        if len(planned["blocks"]) == BLOCKS_PER_SESSION
        and len({block["exercise_id"] for block in planned["blocks"]}) == BLOCKS_PER_SESSION
    ]


def _three_block_session(plan: dict[str, Any]) -> dict[str, Any]:
    """The first of them, for the tests that need only one."""
    found = _three_block_sessions(plan)
    if not found:
        raise AssertionError(f"no session with {BLOCKS_PER_SESSION} distinct-exercise blocks")
    return found[0]


def _block_ids(planned: dict[str, Any]) -> set[int]:
    """The tree's OWN block ids, which is the key the plan screen joins completion on."""
    return {block["id"] for block in planned["blocks"]}


def _log(
    client: TestClient,
    headers: dict[str, str],
    planned: dict[str, Any],
    blocks: list[dict[str, Any]],
    **overrides: Any,
) -> Any:
    """Finish `planned`, logging the first prescribed set of each block in `blocks`."""
    payload: dict[str, Any] = {
        "occurred_on": _TODAY.isoformat(),
        "duration_minutes": 45,
        "discipline": Discipline.BOULDER.value,
        "planned_session_id": planned["id"],
        "finished": True,
        "sets": [
            {
                "client_uuid": str(uuid.uuid4()),
                "exercise_id": block["exercise_id"],
                "prescribed_set_id": block["sets"][0]["id"],
                "set_index": index,
            }
            | overrides
            for index, block in enumerate(blocks, start=1)
        ],
    }
    return client.put(f"/api/sessions/{uuid.uuid4()}", json=payload, headers=headers)


def _read(client: TestClient, headers: dict[str, str], start: Any, end: Any) -> Any:
    return client.get(
        "/api/sessions/completion",
        params={"from": str(start), "to": str(end)},
        headers=headers,
    )


def _window(plan: dict[str, Any]) -> tuple[str, str]:
    """Wide enough for the whole plan AND for a session backdated by a month."""
    days = [planned["scheduled_on"] for planned in _sessions(plan)]
    return str(_TODAY - timedelta(days=30)), max(days)


def _row(body: dict[str, Any], planned_session_id: int) -> dict[str, Any]:
    for row in body["sessions"]:
        if row["planned_session_id"] == planned_session_id:
            found: dict[str, Any] = row
            return found
    raise AssertionError(f"session {planned_session_id} is missing from the response")


@contextmanager
def _statements(session: Session) -> Iterator[list[str]]:
    """Every statement the connection executes, minus the harness's savepoint bookkeeping."""
    captured: list[str] = []
    skip = {"SAVEPOINT", "RELEASE", "ROLLBACK", "COMMIT", "BEGIN"}

    def _record(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        head = statement.strip().split(None, 1)[0].upper() if statement.strip() else ""
        if head not in skip:
            captured.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", _record)
    try:
        yield captured
    finally:
        event.remove(bind, "before_cursor_execute", _record)


# --- The figure itself: 2 of 3 parts, under a status that says "completed" --------


def test_TWO_OF_THREE_PARTS_reads_67_PERCENT_while_STATUS_READS_COMPLETED(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The whole point of deriving it: `completed` is "pressed Finish", not "did it all"."""
    plan = _plan(api_client, auth, db_session)
    planned = _three_block_session(plan)
    assert _log(api_client, auth, planned, planned["blocks"][:2]).status_code == 200

    start, end = _window(plan)
    response = _read(api_client, auth, start, end)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == _CACHE_CONTROL
    row = _row(response.json(), planned["id"])
    assert (row["blocks_done"], row["block_count"], row["percent"]) == (2, BLOCKS_PER_SESSION, 67)
    assert (row["status"], row["state"]) == (SessionStatus.COMPLETED.value, "completed")


def test_WHICH_BLOCKS_GOT_DONE_comes_back_not_only_HOW_MANY(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """ "33% done" cannot say WHICH third, and the card marks every block row done or missed."""
    plan = _plan(api_client, auth, db_session)
    partial, whole = _three_block_sessions(plan)[:2]
    assert _log(api_client, auth, partial, partial["blocks"][:2]).status_code == 200
    assert _log(api_client, auth, whole, whole["blocks"]).status_code == 200
    logged = {partial["id"], whole["id"]}
    untouched = next(one for one in _sessions(plan) if one["id"] not in logged)

    start, end = _window(plan)
    body = _read(api_client, auth, start, end).json()

    # ⚠️ Compared against the TREE's ids, not against ids the response also supplied: the join
    # key is the whole point, and a response agreeing with itself would prove nothing.
    assert set(_row(body, partial["id"])["done_block_ids"]) == _block_ids(partial) - {
        partial["blocks"][2]["id"]
    }
    assert set(_row(body, whole["id"])["done_block_ids"]) == _block_ids(whole)
    assert _row(body, untouched["id"])["done_block_ids"] == []
    for row in body["sessions"]:
        assert row["blocks_done"] == len(row["done_block_ids"]), row


def test_a_logged_set_with_NULL_ACTUAL_VALUES_IS_A_REAL_COMPLETION(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """PR #15a's "I did this myself" mints exactly those; filtering them breaks the count."""
    plan = _plan(api_client, auth, db_session)
    planned = _three_block_session(plan)
    blocks = planned["blocks"]
    # One block measured, one claimed with nothing measured at all. Both are completions.
    assert _log(api_client, auth, planned, blocks[:1], actual_reps=6).status_code == 200
    assert _log(api_client, auth, planned, blocks[1:2]).status_code == 200

    start, end = _window(plan)
    row = _row(_read(api_client, auth, start, end).json(), planned["id"])

    assert (row["blocks_done"], row["percent"]) == (2, 67)
    # And the claimed block is NAMED, so the card marks that row done rather than missed.
    assert set(row["done_block_ids"]) == {blocks[0]["id"], blocks[1]["id"]}


# --- `skipped` is INFERRED, and the boundary is the day itself -------------------


def test_a_PAST_session_reads_SKIPPED_while_TODAYS_STILL_READS_PENDING(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """No endpoint writes `skipped`; the day passing is what makes it one, and today has not."""
    plan = _plan(api_client, auth, db_session)
    first, second, third = _sessions(plan)[:3]
    for planned, day in (
        (first, _TODAY - timedelta(days=1)),
        (second, _TODAY),
        (third, _TODAY + timedelta(days=1)),
    ):
        db_session.execute(
            update(PlannedSession)
            .where(PlannedSession.id == planned["id"])
            .values(scheduled_on=day)
        )
    db_session.flush()

    start, end = _window(plan)
    body = _read(api_client, auth, start, end).json()

    assert body["as_of"] == _TODAY.isoformat()
    states = [_row(body, planned["id"])["state"] for planned in (first, second, third)]
    assert states == ["skipped", "pending", "pending"]


def test_a_COMPLETED_session_in_the_PAST_is_NEVER_SKIPPED(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The status outranks the date: a finished session does not become skipped by ageing."""
    plan = _plan(api_client, auth, db_session)
    planned = _three_block_session(plan)
    assert _log(api_client, auth, planned, planned["blocks"][:1]).status_code == 200
    db_session.execute(
        update(PlannedSession)
        .where(PlannedSession.id == planned["id"])
        .values(scheduled_on=_TODAY - timedelta(days=2))
    )
    db_session.flush()

    start, end = _window(plan)
    row = _row(_read(api_client, auth, start, end).json(), planned["id"])

    assert (row["state"], row["percent"]) == ("completed", 33)


# --- The shapes a percentage cannot describe, and the scoping -------------------


def test_a_session_with_NO_BLOCKS_HAS_NO_PERCENTAGE(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """0% would read as a failure nobody had. `null` says there was nothing to do."""
    plan = _plan(api_client, auth, db_session)
    sibling = _sessions(plan)[0]
    microcycle_id = db_session.scalar(
        select(PlannedSession.microcycle_id).where(PlannedSession.id == sibling["id"])
    )
    assert microcycle_id is not None
    # Weekday 6 is free: the plan above is scheduled Monday, Wednesday and Saturday.
    empty = PlannedSession(
        microcycle_id=microcycle_id,
        weekday=6,
        scheduled_on=sibling["scheduled_on"],
        activity_kind=ActivityKind.CLIMBING,
        status=SessionStatus.PLANNED,
        title="A session with nothing in it",
        estimated_minutes=None,
    )
    db_session.add(empty)
    db_session.flush()

    start, end = _window(plan)
    row = _row(_read(api_client, auth, start, end).json(), empty.id)

    assert (row["block_count"], row["blocks_done"], row["percent"]) == (0, 0, None)
    # The outer join yields ONE row here whose `block_id` is null — never `[null]` on the wire.
    assert row["done_block_ids"] == []


def test_ANOTHER_CLIMBERS_SESSIONS_ARE_ABSENT(
    api_client: TestClient, auth: dict[str, str], invite_code: str, db_session: Session
) -> None:
    """IDOR is the real extraction risk: the window is a date range, the scope is the token."""
    plan = _plan(api_client, auth, db_session)
    mine = {planned["id"] for planned in _sessions(plan)}
    start, end = _window(plan)
    assert {
        row["planned_session_id"] for row in _read(api_client, auth, start, end).json()["sessions"]
    } == mine

    other = _register(api_client, invite_code, _OTHER_EMAIL)
    body = _read(api_client, other, start, end).json()

    assert body["sessions"] == []


def test_a_DEMO_TOKEN_MAY_READ_THIS(api_client: TestClient) -> None:
    """A GET, so the demo mount can colour its plan: read-only is not read-none."""
    demo = {"Authorization": f"Bearer {issue_access_token(DEMO_USER_ID, 'demo').token}"}
    response = _read(api_client, demo, _TODAY, _TODAY + timedelta(days=7))

    assert response.status_code == 200, response.text


# --- Compute: one statement, and a window nobody can widen ----------------------


def test_the_READ_IS_ONE_STATEMENT_whatever_the_SESSION_COUNT(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """No per-session query, so a 32-week plan costs the same one Neon read as a 8-week one."""
    plan = _plan(api_client, auth, db_session)
    planned = _three_block_session(plan)
    assert _log(api_client, auth, planned, planned["blocks"][:2]).status_code == 200
    start, end = _window(plan)

    with _statements(db_session) as captured:
        response = _read(api_client, auth, start, end)
    assert response.status_code == 200, response.text

    assert len(_sessions(plan)) > BLOCKS_PER_SESSION
    assert len(captured) == 1, captured
    # Non-vacuous: the per-BLOCK detail came out of that ONE statement, not a second read.
    done = _row(response.json(), planned["id"])["done_block_ids"]
    assert set(done) == {block["id"] for block in planned["blocks"][:2]}


@pytest.mark.parametrize(
    "start,end",
    [
        (_TODAY, _TODAY - timedelta(days=1)),
        (_TODAY, _TODAY + timedelta(days=_COMPLETION_SPAN_DAYS + 1)),
    ],
    ids=["backwards", "too-wide"],
)
def test_the_WINDOW_IS_BOUNDED(
    api_client: TestClient, auth: dict[str, str], start: Any, end: Any
) -> None:
    """ "Return everything" is the resource-exhaustion risk, and a wider read is a longer wake."""
    assert _read(api_client, auth, start, end).status_code == 422
