"""`POST /api/plans`, `GET /api/plans/active`, `POST /api/plans/{id}/abandon` — the WRITE path.

The half of PR #11b that can lose data: it inserts a ~2,400-row tree in one transaction and is
the only way a plan comes into existence.

`tests/test_plans_api.py` covers `/preview` and owns the mirror-image assertion — that a preview
writes NOTHING. Nothing here asserts which exercise landed in which block: that is the domain's,
tested DB-free in the six `test_planner_*.py` files, and restating it would break this file on
every content edit.

⚠️ **The one-active-plan index needs BOTH of its tests, and both were shown to fail** against the
local database, each for a different sabotage:

- `DROP INDEX uq_plan_one_active_per_user` turns `test_the_database_REFUSES_a_second_ACTIVE_plan`
  red with `Failed: DID NOT RAISE IntegrityError` — two active plans for one user, accepted.
- Recreating it WITHOUT the `postgresql_where` predicate (a plain
  `CREATE UNIQUE INDEX ... ON plan (user_id)`, the one-line edit that loses it) leaves that test
  passing and turns `test_an_ABANDONED_plan_does_not_block_a_new_active_one` red with
  `UniqueViolation: ... "uq_plan_one_active_per_user"`.

Neither alone distinguishes the right index from a plausible wrong one.

**Skips without `DATABASE_URL`** (`conftest.py`); CI runs it for real.
"""

import itertools
import logging
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.app import app
from server.auth import invites, ratelimit
from server.auth.deps import DEMO_WRITE_EXEMPT_ROUTES
from server.auth.tokens import issue_access_token
from server.db import session_scope
from server.domain.grades import Discipline, GradeSystemKey
from server.domain.planner.schedule import week_start_on_or_after
from server.models import (
    AppUser,
    ClimbingAspect,
    Exercise,
    Grade,
    GradeSystem,
    InjuryArea,
    Mesocycle,
    Microcycle,
    Plan,
    PlannedSession,
    PrescribedSet,
    RateLimit,
    SessionBlock,
)
from server.plans.routes import _ACTIVE_STATE, _CACHE_CONTROL, _ONE_ACTIVE_INDEX
from server.security_headers import _FALLBACK_CACHE_CONTROL
from server.seed import DEMO_USER_ID

_EMAIL = "persist@example.com"
_OTHER_EMAIL = "persist-other@example.com"
_PASSWORD = "a-long-enough-passphrase"

# Monday, Wednesday, Saturday — bits 0, 2 and 5.
_MON_WED_SAT = 0b0100101

# ⚠️ **A ONE-rung gap on purpose: runtime, not coverage.** The gap drives `week_count`, which
# drives how many rows each persist inserts, and this file persists a plan a dozen times over.
# One rung is the shortest real plan, and the tree's *shape* is what these tests assert.
# `test_plans_api.py` keeps the long-gap case.
_ONE_RUNG_TARGET = "6c+"

# Committed by the concurrency test, which cannot use the savepoint fixture.
_RACE_EMAIL = "persist-race@example.com"

# ⚠️ **A FIXED address for the concurrency test, outside `_source_ips`' range: it is what makes
# that test locally repeatable.** Its registration COMMITS a `rate_limit` row and `REGISTER` is
# 3/hour, so with a counter-allocated address the row could not be cleaned up (the bucket is an
# HMAC of an address nobody recorded) and the fourth run inside an hour failed on `_register`'s
# 201, naming REGISTRATION rather than the limiter. A constant is a bucket `_purge_race_rows` can
# compute.
_RACE_SOURCE_IP = "203.0.113.119"

# One source address per registration; see `_register`. Starts above `_RACE_SOURCE_IP`, and
# 120-255 is far more addresses than this file registers accounts.
_source_ips = itertools.count(120)

# Every table in the plan tree, root first. The all-or-nothing and completeness assertions
# both walk this, so a seventh level added later is one line here rather than six edits.
_PLAN_TABLES = (Plan, Mesocycle, Microcycle, PlannedSession, SessionBlock, PrescribedSet)


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _EMAIL)


@pytest.fixture
def demo_auth() -> dict[str, str]:
    """A demo-scope bearer for the seeded demo account."""
    return {"Authorization": f"Bearer {issue_access_token(DEMO_USER_ID, 'demo').token}"}


def _register(
    client: TestClient, invite: str, email: str, source_ip: str | None = None
) -> dict[str, str]:
    """A registered account's bearer header, from its OWN source IP.

    ⚠️ The `x-forwarded-for` is not decoration: `ratelimit.REGISTER` is 3/hour/IP and this file
    registers a dozen accounts, so a shared address would make the limiter decide the outcome of
    whichever test runs fourth. Same device and TEST-NET-3 block as `tests/test_auth_invites.py`.
    `source_ip` is passed only by the committing test, which needs a *knowable* bucket.
    """
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PASSWORD, "invite_code": invite},
        headers={"x-forwarded-for": source_ip or f"203.0.113.{next(_source_ips)}"},
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


def _injury_area_id(session: Session, key: str) -> int:
    area_id = session.scalar(select(InjuryArea.id).where(InjuryArea.key == key))
    assert area_id is not None, f"no injury area {key}"
    return area_id


def _complete_profile(
    client: TestClient, auth: dict[str, str], session: Session, **overrides: object
) -> None:
    """Every answer the generator reads. Written through the API, like a real onboarding."""
    body: dict[str, object] = {
        "current_grade_id": _french_grade_id(session, "6c"),
        "target_grade_id": _french_grade_id(session, _ONE_RUNG_TARGET),
        "sessions_per_week": 3,
        "available_weekdays": _MON_WED_SAT,
        "strength_aspect_id": _aspect_id(session, "endurance"),
        "weakness_aspect_id": _aspect_id(session, "finger_strength"),
    }
    body.update(overrides)
    response = client.patch("/api/profile", json=body, headers=auth)
    assert response.status_code == 200, response.text


def _user_id(session: Session, email: str) -> int:
    user_id = session.scalar(select(AppUser.id).where(AppUser.email == email))
    assert user_id is not None, f"no account for {email}"
    return user_id


def _counts(session: Session) -> dict[str, int]:
    """One row count per plan-tree table, keyed by table name."""
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in _PLAN_TABLES
    }


def _body_counts(body: dict[str, Any]) -> dict[str, int]:
    """The same six counts, read off the RESPONSE, so the two can be compared."""
    mesocycles = body["mesocycles"]
    microcycles = [micro for meso in mesocycles for micro in meso["microcycles"]]
    sessions = [planned for micro in microcycles for planned in micro["sessions"]]
    blocks = [block for planned in sessions for block in planned["blocks"]]
    return {
        "plan": 1,
        "mesocycle": len(mesocycles),
        "microcycle": len(microcycles),
        "planned_session": len(sessions),
        "session_block": len(blocks),
        "prescribed_set": sum(len(block["sets"]) for block in blocks),
    }


def _reachable_counts(session: Session, plan_id: int) -> dict[str, int]:
    """The same six counts, but only rows REACHABLE FROM THE PLAN by its foreign keys.

    A row that exists but hangs off the wrong parent is counted by `_counts` and missed here —
    the other possible form of the dropped-subtree bug. Every join below is the real foreign key,
    including `microcycle`'s composite `(mesocycle_id, plan_id)`.
    """
    meso = select(Mesocycle.id).where(Mesocycle.plan_id == plan_id).subquery()
    micro = (
        select(Microcycle.id)
        .join(meso, meso.c.id == Microcycle.mesocycle_id)
        .where(Microcycle.plan_id == plan_id)
        .subquery()
    )
    planned = (
        select(PlannedSession.id).join(micro, micro.c.id == PlannedSession.microcycle_id).subquery()
    )
    block = (
        select(SessionBlock.id)
        .join(planned, planned.c.id == SessionBlock.planned_session_id)
        .subquery()
    )
    prescribed = (
        select(PrescribedSet.id)
        .join(block, block.c.id == PrescribedSet.session_block_id)
        .subquery()
    )
    return {
        "plan": session.scalar(select(func.count()).select_from(Plan).where(Plan.id == plan_id))
        or 0,
        "mesocycle": session.scalar(select(func.count()).select_from(meso)) or 0,
        "microcycle": session.scalar(select(func.count()).select_from(micro)) or 0,
        "planned_session": session.scalar(select(func.count()).select_from(planned)) or 0,
        "session_block": session.scalar(select(func.count()).select_from(block)) or 0,
        "prescribed_set": session.scalar(select(func.count()).select_from(prescribed)) or 0,
    }


def _persist(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post("/api/plans", json={}, headers=headers)


def _bare_plan(user_id: int, *, activated: bool, abandoned: bool = False) -> Plan:
    """A minimal `plan` row, for the tests that are about the INDEX and not the endpoint."""
    now = datetime.now(UTC)
    return Plan(
        user_id=user_id,
        name="index fixture",
        discipline=Discipline.SPORT,
        start_date=date(2026, 8, 31),
        week_count=8,
        generator_version="test",
        generator_input={},
        activated_at=now if activated else None,
        abandoned_at=now if abandoned else None,
    )


# ---------------------------------------------------------------------------------
# The tree gets written, whole and correctly parented
# ---------------------------------------------------------------------------------


def test_persisting_writes_the_COMPLETE_TREE_across_ALL_SIX_TABLES(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """201, and every node of the returned tree is a row hanging off the right parent.

    ⚠️ **The backref-cascade trap is what this exists for.** Attaching children with
    `Mesocycle(plan=plan, ...)` — the child-side form — fails SQLAlchemy's `track_cascade_events`
    initiator-key gate and persists the plan row with **none** of its ~2,400 descendants, with a
    201 and a commit. **Nothing in the schema requires a plan to have a mesocycle**, so no
    constraint objects.

    Three counts have to agree, each catching a different failure: the RESPONSE's tree (what the
    client was promised), the TABLE totals (what exists), and the rows REACHABLE FROM THE PLAN
    (what is correctly parented).
    """
    _complete_profile(api_client, auth, db_session)

    response = _persist(api_client, auth)

    assert response.status_code == 201, response.text
    body = response.json()
    promised = _body_counts(body)
    # Not a smoke check: a plan with one empty mesocycle satisfies every other assertion here,
    # and is exactly what the dropped-subtree bug produced one level down.
    assert promised["prescribed_set"] > 0, f"the plan the endpoint returned is empty: {promised}"
    assert _counts(db_session) == promised
    assert _reachable_counts(db_session, body["id"]) == promised


def test_a_failure_PART_WAY_THROUGH_the_insert_leaves_ZERO_ROWS_IN_ALL_SIX_TABLES(
    api_client: TestClient,
    auth: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All-or-nothing.

    The failure is injected where a real one would land: `_exercise_ids` resolves every key to an
    `exercise.id` that does not exist, so the insert dies on `session_block`'s foreign key — the
    FOURTH level, after four levels have flushed. Anything less than a full rollback leaves a plan
    whose weeks exist and whose sessions have no exercises, which the `/plan` screen renders as
    real.

    ⚠️ **This does NOT prove the handler's own `session.rollback()` is necessary** (an earlier
    version of this docstring claimed it did). In production it is redundant: `get_session` closes
    the session, and `Session.close()` rolls back. The test is still non-vacuous, because
    `conftest.py::api_client` hands the handler a savepoint-joined session that is never closed —
    but that is a property of the harness. Do not delete the `rollback()` on the strength of this
    test passing, and do not keep it on the strength of a reason that is wrong.

    **The 500 must not carry the DB detail, and neither must the LOG.** `str(IntegrityError)`
    includes the statement and its bound parameters, which on the `plan` INSERT means
    `generator_input` — the climber's open-injury keys. So the profile below declares an injury and
    this asserts that key reaches neither the response nor the log, while the constraint name does.
    """
    _complete_profile(
        api_client,
        auth,
        db_session,
        injuries=[{"injury_area_id": _injury_area_id(db_session, "ankle")}],
    )
    unknown_id = (db_session.scalar(select(func.max(Exercise.id))) or 0) + 10_000
    monkeypatch.setattr(
        "server.plans.routes._exercise_ids",
        lambda session, blueprint: dict.fromkeys(
            {
                block.exercise_key
                for meso in blueprint.mesocycles
                for micro in meso.microcycles
                for planned in micro.sessions
                for block in planned.blocks
            },
            unknown_id,
        ),
    )

    with caplog.at_level(logging.ERROR, logger="server.plans.routes"):
        response = _persist(api_client, auth)

    assert response.status_code == 500, response.text
    assert _counts(db_session) == dict.fromkeys((model.__tablename__ for model in _PLAN_TABLES), 0)

    # Worth debugging with: the constraint that refused, and plan-level metadata.
    assert "session_block" in caplog.text and "exercise_id" in caplog.text
    assert f"user_id={_user_id(db_session, _EMAIL)}" in caplog.text
    # …and NOT the user's input, in either place.
    for leaked in ("ankle", "generator_input", "generator_caveats", "INSERT INTO"):
        assert leaked not in caplog.text, f"{leaked!r} reached the function log"
        assert leaked not in response.text, f"{leaked!r} reached the client"


def test_a_MISSING_EXERCISE_KEY_raises_rather_than_inserting_NULL_or_skipping_the_block(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The library and `server/domain/exercises.py` disagreeing is a 500, and writes nothing.

    Not mocked: an exercise row the generator is about to prescribe is genuinely deleted first,
    which is the real shape of the failure — a content edit shipped without re-seeding.
    `_exercise_ids` raises before any insert; both alternatives are worse (a NULL `exercise_id` is
    refused by the column, and skipping the block ships a session missing an exercise).
    """
    _complete_profile(api_client, auth, db_session)
    preview = api_client.post("/api/plans/preview", json={}, headers=auth)
    assert preview.status_code == 200, preview.text
    prescribed_key = preview.json()["mesocycles"][0]["microcycles"][0]["sessions"][0]["blocks"][0][
        "exercise_key"
    ]
    db_session.execute(delete(Exercise).where(Exercise.key == prescribed_key))
    db_session.flush()

    with pytest.raises(RuntimeError, match="prescribed exercise keys with no row"):
        _persist(api_client, auth)

    assert _counts(db_session) == dict.fromkeys((model.__tablename__ for model in _PLAN_TABLES), 0)


# ---------------------------------------------------------------------------------
# One active plan, and the switch
# ---------------------------------------------------------------------------------


def test_the_database_REFUSES_a_second_ACTIVE_plan(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`uq_plan_one_active_per_user`, at the level that still holds if a handler forgets it.

    ⚠️ **Shown to fail** — see the module docstring for both sabotages.

    Deliberately NOT through the endpoint: `create_plan` stands the old plan down first, so it can
    never produce two active rows on one connection. This inserts them directly, which is what a
    future write path that forgot the stand-down would do.
    """
    user_id = _user_id(db_session, _EMAIL)
    db_session.add(_bare_plan(user_id, activated=True))
    db_session.flush()

    db_session.add(_bare_plan(user_id, activated=True))
    try:
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        # A failed flush poisons the SAVEPOINT; unwind it so teardown stays clean.
        db_session.rollback()


def test_an_ABANDONED_plan_does_not_block_a_new_active_one(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The index is the PARTIAL one, and this is the half that proves the predicate.

    A total unique index on `user_id` would pass the test above and fail this one — the realistic
    way the predicate gets lost, since dropping a `postgresql_where` is a one-line edit that
    leaves a plausible-looking index behind. A climber who abandons a plan and generates another
    must not be refused. ⚠️ **Shown to fail**; see the module docstring.
    """
    user_id = _user_id(db_session, _EMAIL)
    db_session.add(_bare_plan(user_id, activated=True, abandoned=True))
    db_session.add(_bare_plan(user_id, activated=True))

    db_session.flush()

    assert (
        db_session.scalar(select(func.count()).select_from(Plan).where(Plan.user_id == user_id))
        == 2
    )


def test_a_LOST_RACE_is_a_409_and_not_a_500(
    api_client: TestClient,
    auth: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 409 branch: the index refused the insert, and that is a legitimate answer.

    ⚠️ **The stand-down is suppressed rather than raced, deliberately.** Two real connections
    cannot produce a 409 *deterministically* — if the requests do not overlap, the second stands
    the first down and both correctly return 201 — so the branch and the concurrency invariant are
    two tests. Neutering `_stand_down_active_plan` is exactly the state a request is in when it
    loses the race; `test_TWO_REAL_CONNECTIONS...` below covers genuine concurrency.

    A 500 here would be the real failure: the user does have an active plan, so the client needs
    "you already have one, refetch".
    """
    _complete_profile(api_client, auth, db_session)
    db_session.add(_bare_plan(_user_id(db_session, _EMAIL), activated=True))
    db_session.flush()
    monkeypatch.setattr(
        "server.plans.routes._stand_down_active_plan",
        lambda session, user_id, at: None,
    )

    response = _persist(api_client, auth)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "You already have an active plan."


def test_activating_B_stands_A_down_IN_ONE_TRANSACTION(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The switch, which is why there is no separate "switch" endpoint.

    Afterwards exactly one plan is active, the other carries `abandoned_at`, and the two timestamps
    are the SAME instant — the observable consequence of one transaction with one `_now_utc()`. A
    gap would mean a window with no active plan; an overlap would mean two.
    """
    _complete_profile(api_client, auth, db_session)
    first = _persist(api_client, auth)
    assert first.status_code == 201, first.text

    second = _persist(api_client, auth)

    assert second.status_code == 201, second.text
    plan_a, plan_b = first.json()["id"], second.json()["id"]
    assert plan_a != plan_b
    rows = {
        row.id: row
        for row in db_session.execute(
            select(Plan.id, Plan.activated_at, Plan.abandoned_at).where(
                Plan.id.in_((plan_a, plan_b))
            )
        ).all()
    }
    assert rows[plan_a].abandoned_at is not None, "A was not stood down"
    assert rows[plan_b].abandoned_at is None
    assert rows[plan_a].abandoned_at == rows[plan_b].activated_at, (
        "A's stand-down and B's activation are not the same instant, so they were not one "
        "transaction with one clock reading."
    )
    active = api_client.get("/api/plans/active", headers=auth)
    assert active.status_code == 200, active.text
    assert active.json()["plan"]["id"] == plan_b


def _purge_race_rows() -> None:
    """Committed rows need explicit cleanup — the concurrency test cannot use a savepoint.

    ⚠️ **Two tables.** Deleting the account cascades the plans, but `rate_limit` hangs off nothing,
    so its row survived and the fourth run of this file inside an hour 429d the *registration*. The
    bucket is computable only because `_RACE_SOURCE_IP` is a constant and
    `conftest.py::_auth_secret` fixes the HMAC key for the session.
    """
    with session_scope() as cleanup:
        cleanup.execute(delete(AppUser).where(AppUser.email == _RACE_EMAIL))
        cleanup.execute(
            delete(RateLimit).where(
                RateLimit.bucket == ratelimit.bucket_key(ratelimit.REGISTER, _RACE_SOURCE_IP)
            )
        )


def test_TWO_REAL_CONNECTIONS_cannot_both_end_up_active(seeded: Engine) -> None:
    """Two genuine simultaneous creates, and the invariant that has to survive them.

    The assertion is the OUTCOME, not the status codes: overlapping transactions give the loser a
    409, and serialised ones legitimately give both 201. Both are correct; **two active plans, or a
    500, are not.**

    Does NOT use `db_session` or `api_client` — a savepoint on one connection cannot race itself.
    Rows are committed and cleaned up by hand, like
    `tests/test_auth_invites.py::test_two_simultaneous_registrations_cannot_both_spend_the_last_use`.
    """
    assert not app.dependency_overrides, "this test needs the app's REAL session dependency"
    _purge_race_rows()
    try:
        with session_scope() as setup:
            code = invites.create(setup, label="persist race", max_uses=2).code
        with TestClient(app, base_url="https://climb.kilianmc.com") as client:
            headers = _register(client, code, _RACE_EMAIL, _RACE_SOURCE_IP)
            with session_scope() as reference:
                _complete_profile(client, headers, reference)

            outcomes: list[int] = []
            lock = threading.Lock()
            barrier = threading.Barrier(2)

            def _tap() -> None:
                barrier.wait(timeout=10)
                status_code = _persist(client, headers).status_code
                with lock:
                    outcomes.append(status_code)

            threads = [threading.Thread(target=_tap, daemon=True) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=120)
                assert not thread.is_alive(), "a create never finished"

        assert set(outcomes) <= {201, 409}, (
            f"a simultaneous create answered with {outcomes}. Anything outside "
            f"{{201, 409}} means the index conflict escaped as a 500."
        )
        with session_scope() as check:
            user_id = _user_id(check, _RACE_EMAIL)
            active = check.scalar(
                select(func.count())
                .select_from(Plan)
                .where(Plan.user_id == user_id, *_ACTIVE_STATE)
            )
        assert active == 1, f"{active} active plans after two simultaneous creates"
    finally:
        _purge_race_rows()


# ---------------------------------------------------------------------------------
# Reading it back, and standing it down
# ---------------------------------------------------------------------------------


def test_no_plan_yet_is_a_200_with_a_NULL_plan(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """Every new account's state, and it is an ordinary render rather than an error.

    A 404 would make the normal case a failure at three layers that all treat 4xx as one — see
    `ActivePlanResponse`.
    """
    response = api_client.get("/api/plans/active", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json() == {"plan": None}


def test_abandon_sets_the_timestamp_and_is_IDEMPOTENT(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Marks, never deletes — and a second press keeps the ORIGINAL timestamp.

    *When* a plan was stood down is the fact the diary wants. Afterwards `GET /active` has nothing
    to return and every row is still there: `activity.planned_session_id` is the only link from a
    logged activity to the plan it satisfied, so a delete would destroy the adherence record.
    """
    _complete_profile(api_client, auth, db_session)
    created = _persist(api_client, auth)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    before = _counts(db_session)

    first = api_client.post(f"/api/plans/{plan_id}/abandon", headers=auth)
    second = api_client.post(f"/api/plans/{plan_id}/abandon", headers=auth)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert datetime.fromisoformat(first.json()["abandoned_at"]) == datetime.fromisoformat(
        second.json()["abandoned_at"]
    ), "a second abandon overwrote the timestamp"
    assert api_client.get("/api/plans/active", headers=auth).json() == {"plan": None}
    assert _counts(db_session) == before, "abandoning deleted rows; it must only mark"


def test_abandon_404s_on_ANOTHER_USERS_plan_and_does_not_leak_that_it_exists(
    api_client: TestClient, auth: dict[str, str], db_session: Session, invite_code: str
) -> None:
    """The scoping IS the security property, so the two answers must be identical.

    A 403 on someone else's plan against a 404 on one that never existed would let a caller
    enumerate plan ids — the IDOR read this project treats as its real extraction risk. Status
    *and* message are compared.
    """
    _complete_profile(api_client, auth, db_session)
    created = _persist(api_client, auth)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    stranger = _register(api_client, invite_code, _OTHER_EMAIL)

    theirs = api_client.post(f"/api/plans/{plan_id}/abandon", headers=stranger)
    nonexistent = api_client.post("/api/plans/99999999/abandon", headers=stranger)

    assert theirs.status_code == 404, theirs.text
    assert theirs.json() == nonexistent.json()
    assert db_session.scalar(select(Plan.abandoned_at).where(Plan.id == plan_id)) is None


# ---------------------------------------------------------------------------------
# The demo mount
# ---------------------------------------------------------------------------------


def test_a_DEMO_TOKEN_cannot_reach_either_of_the_two_WRITE_routes(
    api_client: TestClient, demo_auth: dict[str, str]
) -> None:
    """403 on both POSTs, with no new code — and the reason there are two, not three.

    ⚠️ `GET /api/plans/active` is deliberately NOT refused: `enforce_auth` gates on
    `MUTATING_METHODS`, and refusing a read that writes nothing would break the demo mount's
    `/plan` screen for no gain. Both refusals come from `enforce_auth` before any handler runs,
    with `SET LOCAL transaction_read_only` as the second layer.
    """
    assert api_client.post("/api/plans", json={}, headers=demo_auth).status_code == 403
    assert api_client.post("/api/plans/1/abandon", headers=demo_auth).status_code == 403

    readback = api_client.get("/api/plans/active", headers=demo_auth)
    assert readback.status_code == 200, readback.text
    assert readback.json() == {"plan": None}


def test_the_WRITE_routes_are_ABSENT_from_DEMO_WRITE_EXEMPT_ROUTES() -> None:
    """The exemption list is the hole in "demo mode is read-only"; these must not join it.

    `/preview` is in it because it writes nothing. These write ~2,400 rows to a shared demo
    account, and one entry would remove BOTH layers of the refusal, because the same list gates
    the 403 and the read-only transaction.
    """
    assert ("POST", "/api/plans") not in DEMO_WRITE_EXEMPT_ROUTES
    assert not any(
        path.startswith("/api/plans/") and path != "/api/plans/preview"
        for _, path in DEMO_WRITE_EXEMPT_ROUTES
    )


# ---------------------------------------------------------------------------------
# One wire shape, and everything that has to round-trip
# ---------------------------------------------------------------------------------


def test_the_GENERATION_RECORD_and_the_new_columns_all_ROUND_TRIP(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`generator_version`, `generator_input`, `current_grade_id`, the block rest, the caveats.

    `generator_version` + `generator_input` are the reproducibility promise
    `server/models.py::Plan` makes, with `library_digest` inside the input because the library is
    a third input. `current_grade_id` is stored rather than derived because the profile's current
    grade drifts as the climber improves. `rest_between_sets_seconds` is one of THREE distinct
    rests in this tree, none of which may absorb another.
    """
    _complete_profile(api_client, auth, db_session)
    created = _persist(api_client, auth)
    assert created.status_code == 201, created.text
    body = created.json()

    stored = db_session.execute(
        select(
            Plan.generator_version,
            Plan.generator_input,
            Plan.current_grade_id,
            Plan.target_grade_id,
            Plan.generator_caveats,
        ).where(Plan.id == body["id"])
    ).one()
    assert stored.generator_version == body["generator_version"]
    assert stored.generator_input == body["generator_input"]
    assert stored.generator_input["generator_version"] == body["generator_version"]
    assert stored.generator_input["library_digest"]
    assert stored.current_grade_id == body["current_grade_id"] == _french_grade_id(db_session, "6c")
    assert (
        stored.target_grade_id
        == body["target_grade_id"]
        == _french_grade_id(db_session, _ONE_RUNG_TARGET)
    )
    assert stored.generator_caveats is not None, "generator_caveats was never written"
    assert stored.generator_caveats["shape_version"] == 1

    # The block rest, on the wire and in the column, for a block the generator gave one to.
    rests = db_session.scalars(
        select(SessionBlock.rest_between_sets_seconds).join(
            PlannedSession, PlannedSession.id == SessionBlock.planned_session_id
        )
    ).all()
    assert any(rest is not None for rest in rests), (
        "no block stored a rest_between_sets_seconds, so this test would pass with the "
        "column write removed"
    )
    wire = [
        block["rest_between_sets_seconds"]
        for meso in body["mesocycles"]
        for micro in meso["microcycles"]
        for planned in micro["sessions"]
        for block in planned["blocks"]
    ]
    assert sorted(rests, key=lambda value: (value is None, value)) == sorted(
        wire, key=lambda value: (value is None, value)
    )


def test_the_PERSISTED_response_is_the_PREVIEW_shape_plus_ids(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """ONE wire shape, so `plan.lazy.tsx` needs ONE renderer.

    A parallel persisted shape drops `shortfalls`, `notes`, `grade_gap` and a block's
    `aspect_key`, which forces a second renderer for the same tree. Keys are compared structurally
    at all five levels rather than field by field, so a field added to one path and not the other
    fails here rather than in the browser.

    Also asserted: `POST` and `GET /active` return the SAME body, and every `id` is filled on the
    persisted path.
    """
    _complete_profile(api_client, auth, db_session)
    preview = api_client.post("/api/plans/preview", json={}, headers=auth)
    assert preview.status_code == 200, preview.text
    created = _persist(api_client, auth)
    assert created.status_code == 201, created.text
    previewed, persisted = preview.json(), created.json()

    # Level by level, both trees at once.
    def _levels(plan: dict[str, Any]) -> list[set[str]]:
        meso = plan["mesocycles"][0]
        micro = meso["microcycles"][0]
        planned = micro["sessions"][0]
        block = planned["blocks"][0]
        return [
            set(plan),
            set(meso),
            set(micro),
            set(planned),
            set(block),
            set(block["sets"][0]),
        ]

    assert _levels(previewed) == _levels(persisted)

    # The four fields round 1 dropped, present and populated on the persisted path.
    assert persisted["grade_gap"] == previewed["grade_gap"] > 0
    assert "shortfalls" in persisted and "notes" in persisted
    block = persisted["mesocycles"][0]["microcycles"][0]["sessions"][0]["blocks"][0]
    assert block["aspect_key"], "a persisted block lost its aspect_key"
    assert block["exercise_key"] and block["exercise_id"], (
        "a persisted block must carry BOTH the key and the id, so one client-side library "
        "lookup serves the preview and the persisted plan"
    )

    # Every id filled on the persisted path, and none on the preview's.
    assert persisted["id"] and persisted["activated_at"]
    assert previewed["id"] is None and previewed["activated_at"] is None
    for meso in persisted["mesocycles"]:
        assert meso["id"]
        for micro in meso["microcycles"]:
            assert micro["id"]
            for planned in micro["sessions"]:
                assert planned["id"] and planned["status"] == "planned"
                for persisted_block in planned["blocks"]:
                    assert persisted_block["id"]
                    assert all(prescribed["id"] for prescribed in persisted_block["sets"])

    readback = api_client.get("/api/plans/active", headers=auth)
    assert readback.status_code == 200, readback.text
    reloaded = readback.json()["plan"]
    # ⚠️ `activated_at` is the ONE field the two bodies render differently, and it is a rendering
    # difference rather than a data one: the POST serialises the in-memory `datetime.now(UTC)` as
    # `...Z`, while the re-read comes back from psycopg in the server's timezone. Same instant, so
    # it is compared as an instant and everything else byte for byte.
    assert datetime.fromisoformat(reloaded.pop("activated_at")) == datetime.fromisoformat(
        persisted["activated_at"]
    )
    assert reloaded == {key: value for key, value in persisted.items() if key != "activated_at"}, (
        "POST and GET /active disagree, so a client would need to know which it is holding"
    )


def test_the_generators_CAVEATS_survive_a_reload(
    api_client: TestClient,
    auth: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `/plan` screen's equipment-gap banners, after a reload. `0008`'s new column.

    A real shortfall needs missing gear, and `_ASSUMED_EQUIPMENT_KEYS` is the full vocabulary for
    every user, so the constant is emptied here. The domain is already tested against `()` in
    `tests/test_planner_gearless.py`; what is under test is that the caveats reach a column and
    come back.

    ⚠️ Both levels are asserted. A block's `shortfall` names the aspect the generator **wanted and
    could not fill**, which is NOT the block's own `aspect_key` — exactly why it cannot be derived
    from the persisted row.
    """
    monkeypatch.setattr("server.plans.routes._ASSUMED_EQUIPMENT_KEYS", ())
    _complete_profile(api_client, auth, db_session)
    created = _persist(api_client, auth)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["shortfalls"], "a gearless plan with no shortfalls means the fixture is wrong"

    readback = api_client.get("/api/plans/active", headers=auth)

    assert readback.status_code == 200, readback.text
    reloaded = readback.json()["plan"]
    assert reloaded["shortfalls"] == body["shortfalls"]
    assert reloaded["notes"] == body["notes"]
    blocks = [
        block
        for meso in reloaded["mesocycles"]
        for micro in meso["microcycles"]
        for planned in micro["sessions"]
        for block in planned["blocks"]
    ]
    displaced = [block for block in blocks if block["shortfall"] is not None]
    assert displaced, "no block kept its shortfall, so the per-block caveats were lost"
    assert any(block["shortfall"]["aspect_key"] != block["aspect_key"] for block in displaced), (
        "every surviving shortfall names the block's own aspect, which means the coordinate "
        "keys mis-attached: a shortfall names the aspect that could NOT be filled"
    )


def test_an_UNRECOGNISED_caveats_shape_DEGRADES_instead_of_500ing(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """A plan somebody is halfway through must stay OPENABLE, whatever is in the column.

    `plan.generator_caveats` is schemaless by design, so the read path has to survive a shape it
    does not recognise — a `Shortfall` that gained a required field, a retired `Phase`, a
    hand-edited row. The rule is "treat it as no caveats", never a 500: the tree is untouched and
    the banners are all that is lost.
    """
    _complete_profile(api_client, auth, db_session)
    created = _persist(api_client, auth)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    db_session.execute(
        update(Plan)
        .where(Plan.id == plan_id)
        .values(generator_caveats={"shortfalls": "not a list", "notes": [{"kind": "gone"}]})
    )
    db_session.flush()

    response = api_client.get("/api/plans/active", headers=auth)

    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert plan["id"] == plan_id
    assert plan["shortfalls"] == []
    assert plan["notes"] == []
    # The tree itself is unaffected — only the commentary degraded.
    assert plan["mesocycles"][0]["microcycles"][0]["sessions"][0]["blocks"]


# ---------------------------------------------------------------------------------
# The two definitions of "active", and the client's one input
# ---------------------------------------------------------------------------------


def _conditions(predicate: str) -> set[str]:
    """A parenthesised SQL conjunction as a set of normalised conditions."""
    flat = predicate.replace("(", " ").replace(")", " ")
    return {" ".join(part.split()).lower() for part in flat.split(" AND ")}


def test_the_ACTIVE_CRITERION_and_the_INDEX_PREDICATE_cannot_drift(db_session: Session) -> None:
    """`_ACTIVE_STATE` and `uq_plan_one_active_per_user`'s predicate, compared as SQL.

    The index can only refuse a SECOND active row, so if the app's criterion and the index's
    predicate diverged the index would keep passing while the app stopped agreeing with it. The
    visible symptom would be a plan that is active to Postgres and invisible to
    `GET /api/plans/active`.

    Read back out of `pg_indexes` — Postgres' own normalised rendering — rather than from the
    migration text, so an edited `0008` cannot fool it.
    """
    indexdef = db_session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
        {"name": _ONE_ACTIVE_INDEX},
    )
    assert indexdef is not None, f"{_ONE_ACTIVE_INDEX} does not exist"
    # `user_id` is the INDEXED column, not part of the predicate — which is why
    # `_ACTIVE_STATE` holds only the three state conditions and both callers add the scope.
    assert "btree (user_id)" in indexdef, indexdef
    assert " WHERE " in indexdef, f"the predicate is gone — a PLAIN unique index: {indexdef}"

    assert _conditions(indexdef.split(" WHERE ", 1)[1]) == {
        # `str()` on a SQLAlchemy expression is its compiled SQL; no dialect argument,
        # because `IS [NOT] NULL` renders identically everywhere and the point is the shape.
        " ".join(str(criterion).replace("plan.", "").split()).lower()
        for criterion in _ACTIVE_STATE
    }


def test_a_SUPPLIED_start_date_is_HONOURED_and_NORMALISED_to_a_MONDAY(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The one field the client owns, on the route that makes it durable.

    ⚠️ Every other test in this file posts `json={}`, so without this the persist route's date
    handling is untested on the server — and the web half sends `plan.start_date` precisely so a
    tab left open across midnight cannot save a plan a week off. `web/src/planPersist.test.tsx`
    holds the other side.

    Two cases, because "normalised" has to mean the same thing twice: a mid-week date moves FORWARD
    to the following Monday, and a Monday is returned unchanged. Asserted on the response, the
    `plan` row and the first microcycle — the last catches a normalisation applied to the response
    and not to the tree.
    """
    _complete_profile(api_client, auth, db_session)
    today = datetime.now(UTC).date()
    # The next Wednesday (or today, if today is one): inside the +365-day horizon, and never
    # a Monday, so the normalisation has something to do.
    wednesday = today + timedelta(days=(2 - today.weekday()) % 7)
    expected = week_start_on_or_after(wednesday)
    assert expected != wednesday and expected.weekday() == 0

    response = api_client.post(
        "/api/plans", json={"start_date": wednesday.isoformat()}, headers=auth
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["start_date"] == expected.isoformat()
    assert body["mesocycles"][0]["microcycles"][0]["start_date"] == expected.isoformat()
    assert db_session.scalar(select(Plan.start_date).where(Plan.id == body["id"])) == expected

    # A Monday is already normal, and the two paths must not disagree about that.
    monday = expected + timedelta(days=7)
    again = api_client.post("/api/plans", json={"start_date": monday.isoformat()}, headers=auth)
    assert again.status_code == 201, again.text
    assert again.json()["start_date"] == monday.isoformat()


def test_a_start_date_OUTSIDE_THE_BOUND_is_a_422_and_writes_nothing(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """A stale tab is the real caller here — see `_START_DATE_BACKDATE_DAYS`. The 422 is what the
    web half turns into "reload this page" rather than a generic failure.
    """
    _complete_profile(api_client, auth, db_session)
    stale = datetime.now(UTC).date() - timedelta(days=30)
    response = api_client.post("/api/plans", json={"start_date": stale.isoformat()}, headers=auth)
    assert response.status_code == 422, response.text
    assert _counts(db_session)["plan"] == 0


# ---------------------------------------------------------------------------------
# `cache-control` on all three routes, on BOTH the happy path and the error paths
# ---------------------------------------------------------------------------------
#
# The bodies name one climber's **open injuries**, so a shared-cache entry would hand a stranger
# a picture of somebody's injuries and no behavioural test would see it happen. The routes set the
# header on their injected `Response`, which FastAPI DISCARDS when an `HTTPException` propagates —
# so every 401/404/422 carried no directive at all until `SecurityHeadersMiddleware` grew a
# fallback. `tests/test_security_headers.py` covers the fallback and the complementary guard that
# `/api/library` keeps its `immutable` directive.


def test_the_routes_own_directive_and_the_middleware_fallback_AGREE() -> None:
    """Same string, deliberately, so a 422 and a 201 cannot be cached differently."""
    assert _CACHE_CONTROL == _FALLBACK_CACHE_CONTROL == "private, no-store"


def test_ALL_THREE_ROUTES_are_uncacheable_on_SUCCESS(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    _complete_profile(api_client, auth, db_session)
    created = _persist(api_client, auth)
    assert created.status_code == 201, created.text
    active = api_client.get("/api/plans/active", headers=auth)
    assert active.status_code == 200, active.text
    abandoned = api_client.post(f"/api/plans/{created.json()['id']}/abandon", headers=auth)
    assert abandoned.status_code == 200, abandoned.text
    for response in (created, active, abandoned):
        assert response.headers.get("cache-control") == _CACHE_CONTROL


def test_ALL_THREE_ROUTES_are_uncacheable_on_401_404_and_422(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The paths the routes' own header never reaches, one per route."""
    _complete_profile(api_client, auth, db_session)
    unauthenticated = api_client.get("/api/plans/active")
    assert unauthenticated.status_code == 401, unauthenticated.text
    unprocessable = api_client.post(
        "/api/plans",
        json={"start_date": (datetime.now(UTC).date() - timedelta(days=30)).isoformat()},
        headers=auth,
    )
    assert unprocessable.status_code == 422, unprocessable.text
    missing = api_client.post("/api/plans/999999999/abandon", headers=auth)
    assert missing.status_code == 404, missing.text
    for response in (unauthenticated, unprocessable, missing):
        assert response.headers.get("cache-control") == _FALLBACK_CACHE_CONTROL, (
            f"{response.status_code} carried {response.headers.get('cache-control')!r}"
        )
