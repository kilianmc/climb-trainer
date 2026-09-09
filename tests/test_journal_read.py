"""`GET /api/journal` — reading the diary back, against real Postgres.

The cases that matter are the ones a plausible implementation gets wrong: another climber's
entries, two plans whose weeks overlap, an entry belonging to no plan, the weight series when
`show_body_metrics` is off, too few readings for a mean to mean anything, and the row cap.
`tests/test_journal_log.py` owns the write path.
⚠️ **Cross-user isolation and the weight-series gate were SABOTAGED and watched go red**
(CLAUDE.md); the edits and their failures are in the PR. **Skips without
`CT_TEST_DATABASE_URL`** (`conftest.py`).
"""

import itertools
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from server.auth.tokens import decode_access_token, issue_access_token
from server.domain.grades import Discipline
from server.domain.vocabulary import Phase
from server.journal import routes as journal_routes
from server.journal.routes import (
    _CACHE_CONTROL,
    _STEADY_BAND_KG,
    _TREND_WINDOW,
    WeightDirection,
)
from server.models import Mesocycle, Microcycle, Plan, PlannedSession
from server.seed import DEMO_USER_ID

_EMAIL = "journal-read@example.com"
_OTHER_EMAIL = "journal-read-other@example.com"
_PASSWORD = "a-long-enough-passphrase"
_TODAY = datetime.now(UTC).date()

# One source address per registration: `ratelimit.REGISTER` is 3/hour/IP. TEST-NET-1, a range
# no other suite uses, so two files cannot share a bucket.
_source_ips = itertools.count(10)

# A string no other field could produce, so "did `body` come back?" has no false positive.
_BODY_MARKER = "SECRET-BETA-CRIMP-MARKER"

# Six weeks back, so a four-week plan's weeks are all in the past and every entry below stays
# inside `bounded_day`'s year of backdating.
_PLAN_START = _TODAY - timedelta(days=42)


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _EMAIL)


@pytest.fixture
def other_auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _OTHER_EMAIL)


@pytest.fixture
def demo_auth() -> dict[str, str]:
    """A demo-scope bearer for the seeded demo account."""
    return {"Authorization": f"Bearer {issue_access_token(DEMO_USER_ID, 'demo').token}"}


def _register(client: TestClient, invite: str, email: str) -> dict[str, str]:
    """A registered account's bearer header, from its OWN source IP."""
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PASSWORD, "invite_code": invite},
        headers={"x-forwarded-for": f"192.0.2.{next(_source_ips)}"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _user_id(headers: dict[str, str]) -> int:
    """The id inside the bearer, never one the test invented."""
    return decode_access_token(headers["Authorization"].removeprefix("Bearer ")).user_id


def _put(client: TestClient, headers: dict[str, str], **overrides: Any) -> Any:
    """One entry through the REAL write path. `feel` unless a case says otherwise."""
    payload: dict[str, Any] = {"entry_date": _TODAY.isoformat(), "feel": 3} | overrides
    response = client.put(f"/api/journal/{uuid.uuid4()}", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _get(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = client.get("/api/journal", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _plan_tree(
    session: Session,
    user_id: int,
    *,
    name: str,
    phase: Phase,
    start: date = _PLAN_START,
    weeks: int = 4,
    active: bool = False,
    created_at: datetime | None = None,
) -> Plan:
    """A minimal plan: one mesocycle, one microcycle per week, no sessions unless asked for."""
    activated = datetime.now(UTC) - timedelta(days=42)
    plan = Plan(
        user_id=user_id,
        name=name,
        discipline=Discipline.BOULDER,
        start_date=start,
        week_count=weeks,
        generator_version="test",
        generator_input={},
        activated_at=activated,
        abandoned_at=None if active else activated + timedelta(days=1),
    )
    if created_at is not None:
        plan.created_at = created_at
    session.add(plan)
    session.flush()
    mesocycle = Mesocycle(plan_id=plan.id, phase=phase, start_week=1, end_week=weeks)
    session.add(mesocycle)
    session.flush()
    session.add_all(
        Microcycle(
            mesocycle_id=mesocycle.id,
            plan_id=plan.id,
            week_no=week,
            start_date=start + timedelta(days=7 * (week - 1)),
        )
        for week in range(1, weeks + 1)
    )
    session.flush()
    return plan


def _week_start(plan: Plan, week_no: int) -> date:
    return plan.start_date + timedelta(days=7 * (week_no - 1))


def _shift_week(session: Session, plan: Plan, week_no: int, *, days: int) -> date:
    """Move one STORED week start off the 7-day stride, so a re-derived axis cannot match."""
    microcycle = session.scalars(
        select(Microcycle).where(Microcycle.plan_id == plan.id, Microcycle.week_no == week_no)
    ).one()
    microcycle.start_date = microcycle.start_date + timedelta(days=days)
    session.flush()
    return microcycle.start_date


def _planned_session(session: Session, plan: Plan, week_no: int) -> int:
    """One planned session in a week of `plan`, so a logged session can point at it."""
    microcycle_id = session.scalar(
        select(Microcycle.id).where(Microcycle.plan_id == plan.id, Microcycle.week_no == week_no)
    )
    assert microcycle_id is not None, f"no week {week_no} in plan {plan.id}"
    planned = PlannedSession(
        microcycle_id=microcycle_id,
        weekday=0,
        scheduled_on=_week_start(plan, week_no),
        title="A test session",
    )
    session.add(planned)
    session.flush()
    return planned.id


def _logged_session_id(
    client: TestClient, headers: dict[str, str], planned_session_id: int, on: date
) -> int:
    """A real logged session against a planned one, through the REAL endpoint."""
    response = client.put(
        f"/api/sessions/{uuid.uuid4()}",
        json={
            "occurred_on": on.isoformat(),
            "duration_minutes": 5,
            "discipline": Discipline.BOULDER.value,
            "planned_session_id": planned_session_id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def test_an_entry_comes_back_whole_including_its_body(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """The positive control. Unlike the PUT's ack, this endpoint MUST echo the free text."""
    written = _put(
        api_client,
        auth,
        body=_BODY_MARKER,
        feel=4,
        sleep_quality=5,
        skin=2,
        body_weight_kg="71.40",
    )

    body = _get(api_client, auth)

    assert [entry["id"] for entry in body["entries"]] == [written["id"]]
    entry = body["entries"][0]
    assert entry["body"] == _BODY_MARKER
    assert entry["client_uuid"] == written["client_uuid"]
    assert entry["entry_date"] == _TODAY.isoformat()
    assert (entry["feel"], entry["sleep_quality"], entry["skin"]) == (4, 5, 2)
    assert Decimal(str(entry["body_weight_kg"])) == Decimal("71.40")
    assert entry["logged_session_id"] is None
    assert entry["plan"] is None
    assert body["truncated"] is False
    assert body["has_entries_outside_plan"] is False


def test_another_climbers_entries_are_invisible(
    api_client: TestClient, auth: dict[str, str], other_auth: dict[str, str]
) -> None:
    """⚠️ The security guard. Every row is scoped by the token's own `user_id`."""
    mine = _put(api_client, auth, body="mine")
    _put(api_client, other_auth, body=_BODY_MARKER, feel=1)

    body = _get(api_client, auth)

    assert [entry["id"] for entry in body["entries"]] == [mine["id"]]
    assert _BODY_MARKER not in api_client.get("/api/journal", headers=auth).text


def test_the_read_is_private_and_uncacheable(api_client: TestClient, auth: dict[str, str]) -> None:
    """A shared cache entry would hand a stranger somebody's diary."""
    response = api_client.get("/api/journal", headers=auth)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == _CACHE_CONTROL


def test_a_demo_token_may_read_the_diary(api_client: TestClient, demo_auth: dict[str, str]) -> None:
    """Read-only, so `enforce_auth`'s mutating-method ban does not reach it."""
    body = _get(api_client, demo_auth)

    assert body["entries"] == []
    assert body["trends"] == {"body_weight_kg": None, "body_weight_direction": None}


def test_the_active_plan_wins_when_two_plans_weeks_overlap(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ Abandoned plans routinely cover the same dates as the live one. The active one wins."""
    user_id = _user_id(auth)
    _plan_tree(db_session, user_id, name="Stood down", phase=Phase.BASE)
    live = _plan_tree(db_session, user_id, name="Live", phase=Phase.STRENGTH, active=True)

    _put(api_client, auth, entry_date=_week_start(live, 2).isoformat())

    entry = _get(api_client, auth)["entries"][0]
    assert entry["plan"] == {
        "plan_id": live.id,
        "phase": Phase.STRENGTH.value,
        "week_no": 2,
    }


def test_the_newest_plan_wins_when_none_is_active(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Both stood down and both covering the date: `created_at` decides, newest first."""
    user_id = _user_id(auth)
    older = datetime.now(UTC) - timedelta(days=60)
    _plan_tree(db_session, user_id, name="Older", phase=Phase.BASE, created_at=older)
    newer = _plan_tree(
        db_session,
        user_id,
        name="Newer",
        phase=Phase.TAPER,
        created_at=older + timedelta(days=10),
    )

    _put(api_client, auth, entry_date=_week_start(newer, 3).isoformat())

    body = _get(api_client, auth)
    plan = body["entries"][0]["plan"]
    assert (plan["plan_id"], plan["week_no"]) == (newer.id, 3)
    # The NAME moved to the lookup, which holds exactly one copy of it.
    assert [(row["plan_id"], row["name"]) for row in body["plans"]] == [(newer.id, "Newer")]


def test_an_entry_takes_its_own_sessions_plan_over_the_active_one(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ The top tier: the entry hangs off a session, and that session names its plan."""
    user_id = _user_id(auth)
    stood_down = _plan_tree(db_session, user_id, name="Stood down", phase=Phase.BASE)
    live = _plan_tree(db_session, user_id, name="Live", phase=Phase.STRENGTH, active=True)
    planned_session_id = _planned_session(db_session, stood_down, 2)
    logged_session_id = _logged_session_id(
        api_client, auth, planned_session_id, _week_start(stood_down, 2)
    )

    # Dated inside the LIVE plan's week 3, so the date path alone would answer `live`.
    _put(
        api_client,
        auth,
        entry_date=_week_start(live, 3).isoformat(),
        logged_session_id=logged_session_id,
    )

    entry = _get(api_client, auth)["entries"][0]
    assert entry["logged_session_id"] == logged_session_id
    assert entry["plan"] == {
        "plan_id": stood_down.id,
        "phase": Phase.BASE.value,
        "week_no": 2,
    }


def test_an_entry_outside_every_plan_is_attributed_to_nothing(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Dated before any plan existed, or in a gap between two. Normal, not an error."""
    plan = _plan_tree(db_session, _user_id(auth), name="Later", phase=Phase.BASE, active=True)

    _put(api_client, auth, entry_date=(plan.start_date - timedelta(days=1)).isoformat())

    assert _get(api_client, auth)["entries"][0]["plan"] is None


def test_a_plan_scoped_read_returns_only_that_plans_entries(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """And says that there IS history outside it, without sending any of it."""
    user_id = _user_id(auth)
    plan = _plan_tree(db_session, user_id, name="Live", phase=Phase.BASE, active=True)
    inside = _put(api_client, auth, entry_date=_week_start(plan, 1).isoformat())
    _put(
        api_client,
        auth,
        entry_date=(plan.start_date - timedelta(days=1)).isoformat(),
        body=_BODY_MARKER,
    )

    body = _get(api_client, auth, plan_id=plan.id)

    assert [entry["id"] for entry in body["entries"]] == [inside["id"]]
    assert body["has_entries_outside_plan"] is True
    assert (
        _BODY_MARKER
        not in api_client.get("/api/journal", params={"plan_id": plan.id}, headers=auth).text
    )


def test_a_plan_scoped_read_admits_when_there_is_nothing_else(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The "show old plans" control exists only when there is something to open."""
    plan = _plan_tree(db_session, _user_id(auth), name="Live", phase=Phase.BASE, active=True)
    _put(api_client, auth, entry_date=_week_start(plan, 1).isoformat())

    assert _get(api_client, auth, plan_id=plan.id)["has_entries_outside_plan"] is False


def test_a_foreign_or_unknown_plan_id_yields_no_entries(
    api_client: TestClient, auth: dict[str, str], other_auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ No 404: a caller must not learn that a stranger's plan exists."""
    theirs = _plan_tree(
        db_session, _user_id(other_auth), name="Theirs", phase=Phase.BASE, active=True
    )
    _put(api_client, auth, entry_date=_week_start(theirs, 1).isoformat(), body=_BODY_MARKER)

    for plan_id in (theirs.id, 10**9):
        body = _get(api_client, auth, plan_id=plan_id)
        assert body["entries"] == [], plan_id
        assert body["has_entries_outside_plan"] is True, plan_id


def test_a_misspelled_query_parameter_is_a_422(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """`extra="forbid"`, so `planId` is not silently read as "every plan"."""
    response = api_client.get("/api/journal", params={"planId": 1}, headers=auth)

    assert response.status_code == 422, response.text


# --- the per-plan week lookup: one chart per plan needs one ruler per plan --------------


def test_an_entry_carries_its_plans_id_and_the_name_lives_in_the_lookup(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ ONE copy of a renameable string: the entry holds the id, `plans` holds the name."""
    plan = _plan_tree(
        db_session, _user_id(auth), name="Spring block", phase=Phase.BASE, active=True
    )

    _put(api_client, auth, entry_date=_week_start(plan, 2).isoformat())

    body = _get(api_client, auth)
    attribution = body["entries"][0]["plan"]

    assert "plan_name" not in attribution
    assert attribution["plan_id"] == plan.id
    assert [(row["plan_id"], row["name"]) for row in body["plans"]] == [(plan.id, "Spring block")]


def test_every_referenced_plan_brings_its_own_weeks_in_week_order(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The older plan's chart is ruled in ITS weeks, which `/api/plans/active` never reaches."""
    user_id = _user_id(auth)
    older = _plan_tree(db_session, user_id, name="Older", phase=Phase.BASE, weeks=3)
    live = _plan_tree(
        db_session,
        user_id,
        name="Live",
        phase=Phase.STRENGTH,
        start=_PLAN_START + timedelta(days=21),
        weeks=3,
        active=True,
    )

    _put(api_client, auth, entry_date=_week_start(older, 1).isoformat())
    _put(api_client, auth, entry_date=_week_start(live, 2).isoformat())

    plans = {row["plan_id"]: row for row in _get(api_client, auth)["plans"]}

    assert set(plans) == {older.id, live.id}
    for plan in (older, live):
        assert [(week["week_no"], week["start_date"]) for week in plans[plan.id]["weeks"]] == [
            (week_no, _week_start(plan, week_no).isoformat()) for week_no in (1, 2, 3)
        ]


def test_the_week_starts_are_the_stored_dates_and_never_a_seven_day_stride(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """⚠️ The ruler is `microcycle.start_date`. A client re-deriving `start + 7 * (n - 1)` would
    put week 3 three days early the moment one real plan's week moved."""
    plan = _plan_tree(db_session, _user_id(auth), name="Shifted", phase=Phase.BASE, active=True)
    moved = _shift_week(db_session, plan, 3, days=3)

    _put(api_client, auth, entry_date=_week_start(plan, 1).isoformat())

    weeks = _get(api_client, auth)["plans"][0]["weeks"]

    assert moved != _week_start(plan, 3), "this case is vacuous unless the two disagree"
    assert [week["start_date"] for week in weeks] == [
        _week_start(plan, 1).isoformat(),
        _week_start(plan, 2).isoformat(),
        moved.isoformat(),
        _week_start(plan, 4).isoformat(),
    ]


def test_a_plan_no_entry_references_is_not_in_the_lookup(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The lookup answers "what do these entries reference?", never "what plans exist?"."""
    _plan_tree(db_session, _user_id(auth), name="Empty", phase=Phase.BASE, active=True)

    _put(api_client, auth, entry_date=(_PLAN_START - timedelta(days=1)).isoformat())

    body = _get(api_client, auth)

    assert body["entries"][0]["plan"] is None
    assert body["plans"] == []


# Seven readings, so exactly one full window, and no reading equals its own mean: 496 / 7 is
# 70.857…, which rounds to 70.86 and is not in the list.
_WEIGH_INS = ("70.00", "71.00", "72.00", "70.00", "71.00", "72.00", "70.00")
_WINDOW_MEAN = 70.86
# An eighth reading, so there are two windows and the cut-tail case has one to keep.
_EIGHTH = "76.00"
_SECOND_WINDOW_MEAN = 71.71


def _weigh_in_days(count: int) -> list[date]:
    """One reading a day, oldest first, ending today."""
    return [_TODAY - timedelta(days=count - 1 - offset) for offset in range(count)]


def _write_weigh_ins(client: TestClient, headers: dict[str, str], weights: tuple[str, ...]) -> None:
    for day, weight in zip(_weigh_in_days(len(weights)), weights, strict=True):
        _put(client, headers, entry_date=day.isoformat(), body_weight_kg=weight, feel=3)


def _show_body_metrics(client: TestClient, headers: dict[str, str], *, on: bool) -> None:
    response = client.patch("/api/profile", json={"show_body_metrics": on}, headers=headers)
    assert response.status_code == 200, response.text


def test_the_weight_series_is_a_trailing_mean_and_never_the_raw_dailies(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """⚠️ Raw daily weight is noise presented as signal. Every point is a mean of seven."""
    _write_weigh_ins(api_client, auth, (*_WEIGH_INS, _EIGHTH))

    body = _get(api_client, auth)
    series = body["trends"]["body_weight_kg"]

    assert [point["value"] for point in series] == [
        pytest.approx(_WINDOW_MEAN),
        pytest.approx(_SECOND_WINDOW_MEAN),
    ]
    assert [point["entry_date"] for point in series] == [
        (_TODAY - timedelta(days=1)).isoformat(),
        _TODAY.isoformat(),
    ]
    raw = {float(weight) for weight in (*_WEIGH_INS, _EIGHTH)}
    assert raw.isdisjoint(point["value"] for point in series)
    assert len(body["entries"]) == len(_WEIGH_INS) + 1


def test_a_series_is_absent_until_a_full_window_exists(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """One fewer weigh-in than the window is a sentence in the UI, never a pseudo-trend."""
    _write_weigh_ins(api_client, auth, _WEIGH_INS[:-1])

    trends = _get(api_client, auth)["trends"]

    assert len(_WEIGH_INS[:-1]) == _TREND_WINDOW - 1
    assert trends == {"body_weight_kg": None, "body_weight_direction": None}


def test_the_weight_series_is_absent_when_body_metrics_are_off(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """⚠️ The gate. Nothing is computed for the weight, and the entries themselves still come."""
    _show_body_metrics(api_client, auth, on=False)
    _write_weigh_ins(api_client, auth, _WEIGH_INS)

    body = _get(api_client, auth)

    assert body["trends"] == {"body_weight_kg": None, "body_weight_direction": None}
    assert [entry["feel"] for entry in body["entries"]] == [3] * len(_WEIGH_INS)
    # ⚠️ The weigh-in itself is still sent: the PUT replaces an entry WHOLE, so a client
    # editing one without it in hand would silently erase the stored weight.
    assert [Decimal(str(entry["body_weight_kg"])) for entry in body["entries"]] == [
        Decimal(weight) for weight in reversed(_WEIGH_INS)
    ]


def test_the_weight_series_is_present_when_body_metrics_are_on(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """The other position of the same setting, explicitly rather than by default."""
    _show_body_metrics(api_client, auth, on=True)
    _write_weigh_ins(api_client, auth, _WEIGH_INS)

    series = _get(api_client, auth)["trends"]["body_weight_kg"]

    assert [point["value"] for point in series] == [pytest.approx(_WINDOW_MEAN)]


# --- the weight's DIRECTION: a fact about the smoothed series, and nothing more ---------

# Seven flat readings, then one that moves the SECOND window by exactly `_STEADY_BAND_KG`:
# (70.00 * 6 + 73.50) / 7 = 70.50, half a kilo above the first window's 70.00.
_FLAT = ("70.00",) * _TREND_WINDOW
_AT_THE_BAND_UP = "73.50"
# (70.00 * 6 + 73.40) / 7 = 70.49, one hundredth inside the band.
_JUST_INSIDE_THE_BAND = "73.40"
_AT_THE_BAND_DOWN = "66.50"

# Words that would turn a direction into an outcome. Not exhaustive and not meant to be: it is
# the shape of the mistake — a value named for approval, a target, or a body outcome.
_EVALUATIVE = ("good", "bad", "gain", "loss", "lose", "improv", "target", "goal", "ideal")


def test_no_direction_value_reads_as_a_judgement() -> None:
    """⚠️ CLAUDE.md: the app never recommends losing weight. So a direction names a direction —
    no outcome, no target, no approval — and the sentence for it is the client's, not ours."""
    assert {member.value for member in WeightDirection} == {"up", "down", "steady"}
    for member in WeightDirection:
        assert not any(word in member.value for word in _EVALUATIVE), member
    # Not vacuous: the same sweep fires on exactly the kind of name it exists to refuse.
    assert any(word in "gaining" for word in _EVALUATIVE)


def test_a_change_of_exactly_the_band_is_a_direction_and_not_steady(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """The boundary, upper side: the band is REACHED, so the series has a direction."""
    _write_weigh_ins(api_client, auth, (*_FLAT, _AT_THE_BAND_UP))

    trends = _get(api_client, auth)["trends"]
    series = trends["body_weight_kg"]

    assert series[-1]["value"] - series[0]["value"] == _STEADY_BAND_KG
    assert trends["body_weight_direction"] == WeightDirection.UP.value


def test_a_change_just_inside_the_band_is_steady(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """The boundary, lower side: 0.49 kg across the whole smoothed series is `steady`."""
    _write_weigh_ins(api_client, auth, (*_FLAT, _JUST_INSIDE_THE_BAND))

    trends = _get(api_client, auth)["trends"]
    series = trends["body_weight_kg"]

    assert series[-1]["value"] - series[0]["value"] == pytest.approx(0.49)
    assert trends["body_weight_direction"] == WeightDirection.STEADY.value


def test_a_fall_of_the_band_is_down_and_the_response_carries_no_words_for_it(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """⚠️ `down` is a direction, not an achievement, and the server ships no sentence at all."""
    _write_weigh_ins(api_client, auth, (*_FLAT, _AT_THE_BAND_DOWN))

    trends = _get(api_client, auth)["trends"]

    assert trends["body_weight_direction"] == WeightDirection.DOWN.value
    assert set(trends) == {"body_weight_kg", "body_weight_direction"}


def test_the_direction_is_absent_when_body_metrics_are_off(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """⚠️ The gate covers the direction too. A direction with no series behind it is an
    unsourced claim about a climber's body — the one thing this flag exists to switch off."""
    _show_body_metrics(api_client, auth, on=False)
    _write_weigh_ins(api_client, auth, (*_FLAT, _AT_THE_BAND_UP))

    body = _get(api_client, auth)

    assert body["trends"] == {"body_weight_kg": None, "body_weight_direction": None}
    # The weigh-ins themselves are still there, so a direction WOULD have been derivable.
    assert len(body["entries"]) == _TREND_WINDOW + 1


def test_the_direction_is_absent_until_a_full_window_exists(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """The series' own floor, and the direction shares it: six weigh-ins is not a window."""
    _write_weigh_ins(api_client, auth, _FLAT[:-1])

    trends = _get(api_client, auth)["trends"]

    assert trends == {"body_weight_kg": None, "body_weight_direction": None}


def test_a_one_point_series_still_carries_a_direction(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """⚠️ Present exactly when the series is. One full window is flat by construction, so it
    reads `steady` — the client never meets a series with no direction beside it."""
    _write_weigh_ins(api_client, auth, _FLAT)

    trends = _get(api_client, auth)["trends"]

    assert len(trends["body_weight_kg"]) == 1
    assert trends["body_weight_direction"] == WeightDirection.STEADY.value


def test_the_wellbeing_scores_are_never_smoothed_into_a_series(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """⚠️ A 1-5 score is NOT noise — the reading is the datum, so the client plots the entries
    and nothing here averages them. Smoothing is what shortened the line (Kilian, 2026-09-08)."""
    for day in _weigh_in_days(_TREND_WINDOW + 1):
        _put(api_client, auth, entry_date=day.isoformat(), feel=3, sleep_quality=4, skin=5)

    body = _get(api_client, auth)

    # The whole payload, so a re-added series is a failure rather than an unread extra key.
    assert set(body["trends"]) == {"body_weight_kg", "body_weight_direction"}
    assert [(row["feel"], row["sleep_quality"], row["skin"]) for row in body["entries"]] == [
        (3, 4, 5)
    ] * (_TREND_WINDOW + 1)


def test_the_row_cap_truncates_the_oldest_and_says_so(
    api_client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound every list endpoint owes, and the flag the UI admits it with."""
    monkeypatch.setattr(journal_routes, "_JOURNAL_ROWS_MAX", 3)
    days = _weigh_in_days(4)
    for day in days:
        _put(api_client, auth, entry_date=day.isoformat())

    body = _get(api_client, auth)

    assert [entry["entry_date"] for entry in body["entries"]] == [
        day.isoformat() for day in reversed(days[1:])
    ]
    assert body["truncated"] is True


def test_exactly_the_cap_is_not_truncated(
    api_client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boundary. `truncated` claims older entries exist, so it must not cry wolf at the cap."""
    monkeypatch.setattr(journal_routes, "_JOURNAL_ROWS_MAX", 3)
    for day in _weigh_in_days(3):
        _put(api_client, auth, entry_date=day.isoformat())

    body = _get(api_client, auth)

    assert len(body["entries"]) == 3
    assert body["truncated"] is False


def test_a_cut_tail_cannot_half_fill_a_trend_point(
    api_client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ The completion fold's trap: a cut that makes a DERIVED figure wrong. It cannot here —
    every point needs a full window, so the cut drops points rather than shortening one."""
    monkeypatch.setattr(journal_routes, "_JOURNAL_ROWS_MAX", _TREND_WINDOW)
    _write_weigh_ins(api_client, auth, (*_WEIGH_INS, _EIGHTH))

    body = _get(api_client, auth)

    assert body["truncated"] is True
    assert [point["value"] for point in body["trends"]["body_weight_kg"]] == [
        pytest.approx(_SECOND_WINDOW_MEAN)
    ]


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


def test_the_read_issues_one_statement_per_concern(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Neon bills awake time: the profile flag, the entries with every attribution, one bounded
    lookup for the plans they reference, and — plan-scoped only — the EXISTS. No N+1."""
    plan = _plan_tree(db_session, _user_id(auth), name="Live", phase=Phase.BASE, active=True)
    _put(api_client, auth, entry_date=_week_start(plan, 1).isoformat())
    _put(api_client, auth, entry_date=(plan.start_date - timedelta(days=1)).isoformat())

    # Read out before measuring: the writes above COMMITTED, so touching `plan` inside the
    # block would reload the expired ORM row and be counted as the endpoint's statement.
    plan_id = plan.id

    with _statements(db_session) as unscoped:
        assert len(_get(api_client, auth)["entries"]) == 2
    with _statements(db_session) as scoped:
        assert len(_get(api_client, auth, plan_id=plan_id)["entries"]) == 1

    assert len(unscoped) == 3, unscoped
    assert len(scoped) == 4, scoped
