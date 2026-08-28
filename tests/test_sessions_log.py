"""`PUT /api/sessions/{client_uuid}` — the WRITE path, against real Postgres.

The half of PR #15b that can lose a climber's run: it is the only way a session becomes a row,
it is replayed by an at-least-once outbox, and `sets` merges rather than replaces. Every
assertion here is about what survives a replay, an out-of-order flush, or a lie in the payload.

`tests/test_sessions_validation.py` owns the DB-free edge bounds and runs in the local gate.
Nothing here restates them; nothing there touches a row.

⚠️ **Every guard here was SABOTAGED and watched go red** (CLAUDE.md, "⚠️ A guard test must be
SHOWN to fail before it is trusted"). The edit, then the failure it produced:

- **`sets` made authoritative-replace** — the batch upsert also deletes rows the payload does
  not name. `test_a_PUT_that_OMITS_a_STORED_SET_DOES_NOT_DELETE_IT` red with `assert 1 == 2`,
  `test_TWO_FLUSHES_ACCUMULATE_rather_than_replace` with `assert 2 == 3`. ⚠️ **The replay test
  stayed GREEN**: an identical replay names every set, so it is not the arm that catches replace
  semantics — the omission and accumulation arms are, and neither is redundant.
- **`func.greatest(...)` -> `excluded.duration_minutes`** —
  `test_a_STALE_REPLAY_CANNOT_SHORTEN_THE_SESSION` red with `assert 5 == 90` on the returned
  duration; the `srpe_load` assertion behind it never got to run.
- **the `WHEN status = 'completed'` arm of the `CASE` deleted** —
  `test_a_LATER_UNFINISHED_put_DOES_NOT_UN_FINISH_a_completed_session` red with
  `assert 'in_progress' == 'completed'`, while the forward-transition test stayed green: an
  unconditional target still advances, it only regresses.
- **the prescription-versus-exercise comparison deleted** — the mismatch test red with
  `assert 200 == 422`, the 200 acknowledging two `logged_set` rows one of which names an
  exercise its prescription did not. That is issue #62's failure, exactly.
- **`Plan.user_id` dropped from BOTH branches of `_owned`** —
  `test_ANOTHER_USERS_plan_ids_are_a_404_IDENTICAL_TO_THE_MISSING_CASE` red with
  `assert 200 == 404` on the **prescribed-set** arm only. ⚠️ **The planned-session arm stayed
  green**, because `_advance_planned_session`'s `EXISTS` re-scopes ownership independently.
  Dropping that `EXISTS` as well turned the same test red at the planned-session assertion,
  `assert 200 == 404` with `planned_session_status: "in_progress"` on a stranger's session. Two
  layers, and the test can only see the first one break through the prescribed-set arm.
- **the batch upsert converted to a per-set loop** —
  `test_the_STATEMENT_COUNT_is_INDEPENDENT_OF_THE_SET_COUNT` red with `a 2-set flush cost 6
  statements and a 30-set flush 34`. The measured real figures: **5 for any flush** of 1..120
  sets, and 3 for an off-plan one.
- **the duplicate-`client_uuid` validator removed** — red with psycopg's
  `CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time`, i.e. a
  500 carrying the whole flush into the log.
- **the `where=` on the activity `DO UPDATE` dropped** — the cardio test red on `the conflict
  must be seen before any subtype row is attempted`. ⚠️ The **status is 409 either way** (the
  composite FK catches the reclassification), so the assertion that actually carries this guard
  is the ABSENCE of an attempted `INSERT INTO logged_session`: a failed statement aborts the
  transaction, an empty `RETURNING` does not.
- **the 500 branch logging `error` rather than the constraint name** — red with
  `assert 'SECRET-BETA-CRIMP' not in ...`, the set note reaching the function log inside the
  driver's bound parameters.
- **`SessionLogResponse` given a `notes` field** — red with
  `'NOTES-MARKER' is contained here: ,"notes":"NOTES-MARKER"`.

**Skips without `DATABASE_URL`** (`conftest.py`); CI runs it for real.
"""

import itertools
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from server.auth.deps import DEMO_WRITE_EXEMPT_ROUTES
from server.auth.tokens import issue_access_token
from server.domain.grades import Discipline, GradeSystemKey
from server.domain.planner.selection import BLOCKS_PER_SESSION
from server.domain.vocabulary import ActivityKind, SessionStatus
from server.models import (
    Activity,
    AppUser,
    ClimbingAspect,
    Exercise,
    Grade,
    GradeSystem,
    LoggedSession,
    LoggedSet,
    PlannedSession,
    PrescribedSet,
    SessionBlock,
)
from server.seed import DEMO_USER_ID
from server.sessions import routes
from server.sessions.routes import (
    _CACHE_CONTROL,
    _EXERCISE_MISMATCH,
    _NO_EXERCISE,
    _NO_PLANNED_SESSION,
    _NO_PRESCRIBED_SET,
    _NOT_SAVED,
    _WRONG_KIND,
)

_EMAIL = "log@example.com"
_OTHER_EMAIL = "log-other@example.com"
_PASSWORD = "a-long-enough-passphrase"
_TODAY = datetime.now(UTC).date()

# Monday, Wednesday, Saturday — bits 0, 2 and 5. Same mask as `tests/test_plans_persist.py`.
_MON_WED_SAT = 0b0100101

# A ONE-rung gap on purpose: it is the shortest real plan, and this file persists several.
_ONE_RUNG_TARGET = "6c+"

# One source address per registration: `ratelimit.REGISTER` is 3/hour/IP, so a shared address
# would let the limiter decide the outcome of whichever test registers fourth. TEST-NET-3.
_source_ips = itertools.count(180)

# The three tables one flush can touch. Idempotency is a claim about all of them at once.
_LOG_TABLES = (Activity, LoggedSession, LoggedSet)

_ROUTE = ("PUT", "/api/sessions/{client_uuid}")


class _Prescription(NamedTuple):
    """One prescribed set of the plan tree, with the exercise its block names."""

    prescribed_set_id: int
    exercise_id: int
    block_id: int


class _Tree(NamedTuple):
    """A real plan tree's ids, read off `POST /api/plans`' own response."""

    planned_session_id: int
    prescriptions: list[_Prescription]


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _EMAIL)


@pytest.fixture
def demo_auth() -> dict[str, str]:
    """A demo-scope bearer for the seeded demo account."""
    return {"Authorization": f"Bearer {issue_access_token(DEMO_USER_ID, 'demo').token}"}


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


def _plan_tree(client: TestClient, headers: dict[str, str], session: Session) -> _Tree:
    """A plan through the REAL endpoints — profile then `POST /api/plans`, never hand-built rows."""
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

    for meso in persisted.json()["mesocycles"]:
        for micro in meso["microcycles"]:
            for planned in micro["sessions"]:
                blocks = planned["blocks"]
                if len(blocks) != BLOCKS_PER_SESSION:
                    continue
                if len({block["exercise_id"] for block in blocks}) != BLOCKS_PER_SESSION:
                    continue
                return _Tree(
                    planned_session_id=planned["id"],
                    prescriptions=[
                        _Prescription(
                            prescribed_set_id=block["sets"][0]["id"],
                            exercise_id=block["exercise_id"],
                            block_id=block["id"],
                        )
                        for block in blocks
                    ],
                )
    raise AssertionError(f"no planned session with {BLOCKS_PER_SESSION} distinct-exercise blocks")


def _envelope(**overrides: Any) -> dict[str, Any]:
    """The three required fields, so every case below differs in exactly what it names."""
    payload: dict[str, Any] = {
        "occurred_on": _TODAY.isoformat(),
        "duration_minutes": 5,
        "discipline": Discipline.BOULDER.value,
    }
    return payload | overrides


def _set(exercise_id: int, index: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "client_uuid": str(uuid.uuid4()),
        "exercise_id": exercise_id,
        "set_index": index,
    }
    return payload | overrides


def _put(client: TestClient, headers: dict[str, str], client_uuid: str, **overrides: Any) -> Any:
    return client.put(f"/api/sessions/{client_uuid}", json=_envelope(**overrides), headers=headers)


def _counts(session: Session) -> dict[str, int]:
    """One row count per table a flush can write, keyed by table name."""
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in _LOG_TABLES
    }


def _an_exercise_id(session: Session) -> int:
    exercise_id = session.scalar(select(func.min(Exercise.id)))
    assert exercise_id is not None, "the exercise library is not seeded"
    return exercise_id


def _user_id(session: Session, email: str) -> int:
    user_id = session.scalar(select(AppUser.id).where(AppUser.email == email))
    assert user_id is not None, f"no account for {email}"
    return user_id


@contextmanager
def _statements(session: Session) -> Iterator[list[str]]:
    """Every statement the connection executes, minus the harness's own savepoint bookkeeping."""
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


# --- The start PUT, and what the response is allowed to say ----------------------


def test_a_START_put_creates_the_activity_and_its_SUBTYPE(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """200 with no sets, both rows written, and the header the body's sensitivity demands."""
    client_uuid = str(uuid.uuid4())

    response = _put(api_client, auth, client_uuid, notes="felt strong", location="Cafe Kraft")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == _CACHE_CONTROL
    body = response.json()
    assert body["client_uuid"] == client_uuid
    assert body["sets"] == []
    assert body["planned_session_status"] is None
    assert _counts(db_session) == {"activity": 1, "logged_session": 1, "logged_set": 0}
    stored = db_session.scalar(select(LoggedSession).where(LoggedSession.activity_id == body["id"]))
    assert stored is not None
    assert (stored.notes, stored.location) == ("felt strong", "Cafe Kraft")
    assert stored.activity_kind is ActivityKind.CLIMBING


def test_the_RESPONSE_ECHOES_NO_USER_FREE_TEXT(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Nothing in this body needs escaping downstream, so nothing user-typed may be in it."""
    exercise_id = _an_exercise_id(db_session)

    response = _put(
        api_client,
        auth,
        str(uuid.uuid4()),
        notes="NOTES-MARKER",
        location="LOCATION-MARKER",
        sets=[_set(exercise_id, 1, note="SET-NOTE-MARKER")],
    )

    assert response.status_code == 200, response.text
    for marker in ("NOTES-MARKER", "LOCATION-MARKER", "SET-NOTE-MARKER"):
        assert marker not in response.text
    assert db_session.scalar(select(LoggedSet.note)) == "SET-NOTE-MARKER"


# --- C — idempotency: a replay is not a second run, and an omission is not a delete


def test_an_IDENTICAL_REPLAY_CHANGES_NOTHING(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Same body twice: same row counts, and a BYTE-IDENTICAL response the outbox can compare."""
    exercise_id = _an_exercise_id(db_session)
    client_uuid = str(uuid.uuid4())
    sets = [_set(exercise_id, 1), _set(exercise_id, 2)]

    first = _put(api_client, auth, client_uuid, duration_minutes=30, sets=sets)
    after_first = _counts(db_session)
    second = _put(api_client, auth, client_uuid, duration_minutes=30, sets=sets)

    assert first.status_code == second.status_code == 200, second.text
    assert second.text == first.text
    assert after_first == {"activity": 1, "logged_session": 1, "logged_set": 2}
    assert _counts(db_session) == after_first


def test_a_PUT_that_OMITS_a_STORED_SET_DOES_NOT_DELETE_IT(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`sets` is a DELTA: a piggyback carries the unsent tail, never the whole run."""
    exercise_id = _an_exercise_id(db_session)
    client_uuid = str(uuid.uuid4())
    kept, resent = _set(exercise_id, 1), _set(exercise_id, 2)

    assert _put(api_client, auth, client_uuid, sets=[kept, resent]).status_code == 200
    again = _put(api_client, auth, client_uuid, sets=[resent | {"actual_reps": 9}])

    assert again.status_code == 200, again.text
    assert _counts(db_session)["logged_set"] == 2
    stored: dict[uuid.UUID, int | None] = {
        row.client_uuid: row.actual_reps
        for row in db_session.execute(select(LoggedSet.client_uuid, LoggedSet.actual_reps))
    }
    assert stored[uuid.UUID(kept["client_uuid"])] is None
    assert stored[uuid.UUID(resent["client_uuid"])] == 9


def test_TWO_FLUSHES_ACCUMULATE_rather_than_replace(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Disjoint flushes are order-insensitive, so both must be present afterwards."""
    exercise_id = _an_exercise_id(db_session)
    client_uuid = str(uuid.uuid4())

    assert _put(api_client, auth, client_uuid, sets=[_set(exercise_id, 1)]).status_code == 200
    second = _put(api_client, auth, client_uuid, sets=[_set(exercise_id, 2), _set(exercise_id, 3)])

    assert second.status_code == 200, second.text
    assert _counts(db_session)["logged_set"] == 3
    assert [ack["set_index"] for ack in second.json()["sets"]] == [2, 3]


# --- D — monotonicity: neither the duration nor the planned status may regress ---


def test_a_STALE_REPLAY_CANNOT_SHORTEN_THE_SESSION(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`GREATEST`, because `srpe_load` is GENERATED from this column and would regress with it."""
    client_uuid = str(uuid.uuid4())

    assert _put(api_client, auth, client_uuid, duration_minutes=90, rpe=8).status_code == 200
    late = _put(api_client, auth, client_uuid, duration_minutes=5, rpe=8)

    assert late.status_code == 200, late.text
    assert late.json()["duration_minutes"] == 90
    activity = db_session.scalar(select(Activity).where(Activity.id == late.json()["id"]))
    assert activity is not None
    assert (activity.duration_minutes, activity.srpe_load) == (90, 720)


def test_a_plan_linked_run_advances_PLANNED_to_IN_PROGRESS_to_COMPLETED(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The transition is the only server behaviour that depends on `finished`."""
    tree = _plan_tree(api_client, auth, db_session)
    client_uuid = str(uuid.uuid4())
    linked = {"planned_session_id": tree.planned_session_id}
    assert (
        db_session.scalar(
            select(PlannedSession.status).where(PlannedSession.id == tree.planned_session_id)
        )
        is SessionStatus.PLANNED
    )

    start = _put(api_client, auth, client_uuid, **linked)
    finish = _put(api_client, auth, client_uuid, finished=True, duration_minutes=75, **linked)

    assert start.json()["planned_session_status"] == SessionStatus.IN_PROGRESS.value, start.text
    assert finish.json()["planned_session_status"] == SessionStatus.COMPLETED.value, finish.text
    assert (
        db_session.scalar(
            select(PlannedSession.status).where(PlannedSession.id == tree.planned_session_id)
        )
        is SessionStatus.COMPLETED
    )


def test_a_LATER_UNFINISHED_put_DOES_NOT_UN_FINISH_a_completed_session(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """A retry of the flush before Finish must not walk the status back to `in_progress`."""
    tree = _plan_tree(api_client, auth, db_session)
    client_uuid = str(uuid.uuid4())
    linked = {"planned_session_id": tree.planned_session_id}

    finish = _put(api_client, auth, client_uuid, finished=True, duration_minutes=75, **linked)
    stale = _put(api_client, auth, client_uuid, duration_minutes=40, **linked)

    assert finish.json()["planned_session_status"] == SessionStatus.COMPLETED.value
    assert stale.status_code == 200, stale.text
    assert stale.json()["planned_session_status"] == SessionStatus.COMPLETED.value
    assert (
        db_session.scalar(
            select(PlannedSession.status).where(PlannedSession.id == tree.planned_session_id)
        )
        is SessionStatus.COMPLETED
    )


# --- A — issue #62: a logged set may not name an exercise its prescription did not


def test_a_set_whose_EXERCISE_DISAGREES_with_its_PRESCRIPTION_is_refused(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """422, and ZERO rows: a broken prescription mapping makes the rest of the flush suspect."""
    tree = _plan_tree(api_client, auth, db_session)
    honest, other = tree.prescriptions[0], tree.prescriptions[1]

    response = _put(
        api_client,
        auth,
        str(uuid.uuid4()),
        planned_session_id=tree.planned_session_id,
        sets=[
            _set(honest.exercise_id, 1, prescribed_set_id=honest.prescribed_set_id),
            _set(other.exercise_id, 2, prescribed_set_id=honest.prescribed_set_id),
        ],
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _EXERCISE_MISMATCH
    assert _counts(db_session) == {"activity": 0, "logged_session": 0, "logged_set": 0}


def test_a_set_that_MATCHES_its_prescription_is_stored(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The positive control: invariant A must not be a blanket refusal of plan-linked sets."""
    tree = _plan_tree(api_client, auth, db_session)
    prescription = tree.prescriptions[0]

    response = _put(
        api_client,
        auth,
        str(uuid.uuid4()),
        planned_session_id=tree.planned_session_id,
        sets=[_set(prescription.exercise_id, 1, prescribed_set_id=prescription.prescribed_set_id)],
    )

    assert response.status_code == 200, response.text
    assert db_session.scalar(select(LoggedSet.prescribed_set_id)) == prescription.prescribed_set_id


# --- B — ownership: not-yours and not-there are the same answer, in one statement


def test_ANOTHER_USERS_plan_ids_are_a_404_IDENTICAL_TO_THE_MISSING_CASE(
    api_client: TestClient, auth: dict[str, str], db_session: Session, invite_code: str
) -> None:
    """404 before 422, byte-identical either way: the message must not confirm a row exists."""
    other_auth = _register(api_client, invite_code, _OTHER_EMAIL)
    theirs = _plan_tree(api_client, other_auth, db_session)
    exercise_id = _an_exercise_id(db_session)
    absent = (db_session.scalar(select(func.max(PrescribedSet.id))) or 0) + 10_000
    absent_session = (db_session.scalar(select(func.max(PlannedSession.id))) or 0) + 10_000

    not_yours_session = _put(
        api_client, auth, str(uuid.uuid4()), planned_session_id=theirs.planned_session_id
    )
    not_there_session = _put(api_client, auth, str(uuid.uuid4()), planned_session_id=absent_session)
    not_yours_set = _put(
        api_client,
        auth,
        str(uuid.uuid4()),
        sets=[
            _set(
                theirs.prescriptions[0].exercise_id,
                1,
                prescribed_set_id=theirs.prescriptions[0].prescribed_set_id,
            )
        ],
    )
    not_there_set = _put(
        api_client, auth, str(uuid.uuid4()), sets=[_set(exercise_id, 1, prescribed_set_id=absent)]
    )

    for response in (not_yours_session, not_there_session):
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == _NO_PLANNED_SESSION
    for response in (not_yours_set, not_there_set):
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == _NO_PRESCRIBED_SET
    assert not_yours_session.text == not_there_session.text
    assert not_yours_set.text == not_there_set.text
    assert _counts(db_session) == {"activity": 0, "logged_session": 0, "logged_set": 0}


def test_the_STATEMENT_COUNT_is_INDEPENDENT_OF_THE_SET_COUNT(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """One ownership statement and one batch upsert for the whole flush, whatever N is."""
    tree = _plan_tree(api_client, auth, db_session)
    prescription = tree.prescriptions[0]
    linked = {"planned_session_id": tree.planned_session_id}

    def _flush(count: int) -> int:
        sets = [
            _set(prescription.exercise_id, index, prescribed_set_id=prescription.prescribed_set_id)
            for index in range(1, count + 1)
        ]
        with _statements(db_session) as captured:
            response = _put(api_client, auth, str(uuid.uuid4()), sets=sets, **linked)
        assert response.status_code == 200, response.text
        return len(captured)

    small, large = _flush(2), _flush(30)

    assert small == large, f"a 2-set flush cost {small} statements and a 30-set flush {large}"
    assert large <= 6, f"a maximal flush must stay bounded, saw {large}"


def test_an_OFF_PLAN_flush_costs_NO_OWNERSHIP_STATEMENT(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """No `planned_session_id` and no prescription means the ownership branch is skipped whole."""
    exercise_id = _an_exercise_id(db_session)

    with _statements(db_session) as captured:
        response = _put(api_client, auth, str(uuid.uuid4()), sets=[_set(exercise_id, 1)])

    assert response.status_code == 200, response.text
    assert len(captured) == 3, [statement.split(None, 3)[:3] for statement in captured]


# --- E — a duplicate conflict key never reaches Postgres -------------------------


def test_TWO_SETS_WITH_ONE_CLIENT_UUID_never_reach_postgres(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """A 422 at the edge, not `ON CONFLICT DO UPDATE cannot affect row a second time` as a 500."""
    exercise_id = _an_exercise_id(db_session)
    shared = str(uuid.uuid4())

    response = _put(
        api_client,
        auth,
        str(uuid.uuid4()),
        sets=[
            _set(exercise_id, 1, client_uuid=shared),
            _set(exercise_id, 2, client_uuid=shared),
        ],
    )

    assert response.status_code == 422, response.text
    assert _counts(db_session) == {"activity": 0, "logged_session": 0, "logged_set": 0}


# --- Decision 4 — the demo principal stays unable to log, with zero per-route code


def test_a_DEMO_TOKEN_CANNOT_LOG(
    api_client: TestClient, demo_auth: dict[str, str], db_session: Session
) -> None:
    """403 from the app-level guard, and this route is deliberately not exempted from it."""
    assert _ROUTE not in DEMO_WRITE_EXEMPT_ROUTES

    response = _put(api_client, demo_auth, str(uuid.uuid4()))

    assert response.status_code == 403, response.text
    assert _counts(db_session) == {"activity": 0, "logged_session": 0, "logged_set": 0}


# --- Decision 8 — partial completion is a derived query, not a column ------------


def test_TWO_OF_THREE_PARTS_is_ANSWERABLE_BY_QUERY_while_status_reads_COMPLETED(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`completed` means "pressed Finish"; how much got done is a join, which is why no column."""
    tree = _plan_tree(api_client, auth, db_session)
    done = tree.prescriptions[:2]

    response = _put(
        api_client,
        auth,
        str(uuid.uuid4()),
        planned_session_id=tree.planned_session_id,
        finished=True,
        duration_minutes=75,
        sets=[
            _set(item.exercise_id, index, prescribed_set_id=item.prescribed_set_id)
            for index, item in enumerate(done, start=1)
        ],
    )

    assert response.status_code == 200, response.text
    assert response.json()["planned_session_status"] == SessionStatus.COMPLETED.value
    blocks_trained = db_session.scalar(
        select(func.count(func.distinct(SessionBlock.id)))
        .select_from(LoggedSet)
        .join(PrescribedSet, PrescribedSet.id == LoggedSet.prescribed_set_id)
        .join(SessionBlock, SessionBlock.id == PrescribedSet.session_block_id)
        .where(SessionBlock.planned_session_id == tree.planned_session_id)
    )
    blocks_planned = db_session.scalar(
        select(func.count())
        .select_from(SessionBlock)
        .where(SessionBlock.planned_session_id == tree.planned_session_id)
    )
    assert (blocks_trained, blocks_planned) == (2, BLOCKS_PER_SESSION)


# --- The supertype guard, and the rest of the error table ------------------------


def test_a_uuid_that_already_names_a_CARDIO_activity_is_a_409(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Refused by an EMPTY `RETURNING`, so no failed statement ever aborts the transaction."""
    client_uuid = uuid.uuid4()
    db_session.add(
        Activity(
            user_id=_user_id(db_session, _EMAIL),
            activity_kind=ActivityKind.CARDIO,
            occurred_on=_TODAY,
            duration_minutes=45,
            client_uuid=client_uuid,
        )
    )
    db_session.flush()

    with _statements(db_session) as captured:
        response = _put(api_client, auth, str(client_uuid))

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _WRONG_KIND
    attempted = [statement for statement in captured if "INSERT INTO logged_session" in statement]
    assert not attempted, "the conflict must be seen before any subtype row is attempted"
    assert _counts(db_session)["logged_session"] == 0


def test_a_NONEXISTENT_EXERCISE_ID_is_a_404_not_a_500(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The one `IntegrityError` this route can explain, matched on the constraint NAME."""
    absent = (db_session.scalar(select(func.max(Exercise.id))) or 0) + 10_000

    response = _put(api_client, auth, str(uuid.uuid4()), sets=[_set(absent, 1)])

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == _NO_EXERCISE
    assert _counts(db_session) == {"activity": 0, "logged_session": 0, "logged_set": 0}


def test_the_SAME_CLIENT_UUID_FROM_TWO_USERS_is_TWO_SESSIONS(
    api_client: TestClient, auth: dict[str, str], db_session: Session, invite_code: str
) -> None:
    """The conflict target binds `user_id` from the token: the idempotency key IS the scope."""
    other_auth = _register(api_client, invite_code, _OTHER_EMAIL)
    client_uuid = str(uuid.uuid4())

    mine = _put(api_client, auth, client_uuid, duration_minutes=90)
    theirs = _put(api_client, other_auth, client_uuid, duration_minutes=30)

    assert mine.status_code == theirs.status_code == 200, theirs.text
    assert mine.json()["id"] != theirs.json()["id"]
    assert theirs.json()["duration_minutes"] == 30
    assert _counts(db_session) == {"activity": 2, "logged_session": 2, "logged_set": 0}


def test_a_DATA_ERROR_is_a_500_that_LOGS_NEITHER_THE_NOTE_NOR_THE_STATEMENT(
    api_client: TestClient,
    auth: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Input minimisation applies to the LOG: `str(DataError)` carries the bound parameters."""
    marker = "SECRET-BETA-CRIMP"
    exercise_id = _an_exercise_id(db_session)
    real = routes._upsert_sets
    captured: list[BaseException] = []

    def _overflowing(session: Session, activity_id: int, sets: list[Any]) -> Any:
        widened = [entry.model_copy(update={"actual_reps": 99_999}) for entry in sets]
        try:
            return real(session, activity_id, widened)
        except DataError as error:
            captured.append(error)
            raise

    monkeypatch.setattr(routes, "_upsert_sets", _overflowing)

    response = _put(api_client, auth, str(uuid.uuid4()), sets=[_set(exercise_id, 1, note=marker)])

    assert response.status_code == 500, response.text
    assert response.json()["detail"] == _NOT_SAVED
    assert captured, "no DataError was raised, so this test proves nothing"
    assert marker in str(captured[0]), "the driver text does not carry the note — vacuous test"
    assert marker not in caplog.text
    assert "99999" not in caplog.text
    assert "session log failed" in caplog.text
    assert _counts(db_session) == {"activity": 0, "logged_session": 0, "logged_set": 0}
