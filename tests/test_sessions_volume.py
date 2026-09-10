"""`GET /api/sessions/volume` — per-aspect training volume, and what the row cap does to it.

The cap cases are PURE and need no database: `_aspect_volume` takes the rows, so "exactly on
the cap" and "the cut fell inside a day" are exact rather than staged through 2000 fixtures.
The DB-backed half proves the join reaches an aspect at all, and that it reaches nobody else's.
⚠️ **Cross-user isolation, the exactly-on-the-cap flag and the split-day drop were SABOTAGED
and watched go red** (CLAUDE.md); the edits and their failures are in the PR.
**Skips without `CT_TEST_DATABASE_URL`** (`conftest.py`).
"""

import itertools
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.auth.tokens import decode_access_token
from server.domain.grades import Discipline
from server.domain.vocabulary import CLIMBING_ASPECTS, ActivityKind
from server.models import Activity, ClimbingAspect, Exercise, LoggedSession, LoggedSet
from server.sessions import routes as session_routes
from server.sessions.routes import _CACHE_CONTROL, _VOLUME_ROWS_MAX, _aspect_volume, _volume_query

_EMAIL = "volume@example.com"
_OTHER_EMAIL = "volume-other@example.com"
_PASSWORD = "a-long-enough-passphrase"
_TODAY = datetime.now(UTC).date()

# One source address per registration: `ratelimit.REGISTER` is 3/hour/IP. TEST-NET-2, a range
# no other suite uses, so two files cannot share a bucket.
_source_ips = itertools.count(10)

_FINGERS = "finger_strength"
_POWER = "power"


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _EMAIL)


@pytest.fixture
def other_auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    return _register(api_client, invite_code, _OTHER_EMAIL)


def _register(client: TestClient, invite: str, email: str) -> dict[str, str]:
    """A registered account's bearer header, from its OWN source IP."""
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PASSWORD, "invite_code": invite},
        headers={"x-forwarded-for": f"198.51.100.{next(_source_ips)}"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _user_id(headers: dict[str, str]) -> int:
    """The id inside the bearer, never one the test invented."""
    return decode_access_token(headers["Authorization"].removeprefix("Bearer ")).user_id


def _exercise_per_aspect(session: Session) -> dict[str, int]:
    """One real seeded exercise id per aspect key, so the join has something to land on."""
    rows = session.execute(
        select(ClimbingAspect.key, func.min(Exercise.id))
        .join(Exercise, Exercise.climbing_aspect_id == ClimbingAspect.id)
        .group_by(ClimbingAspect.key)
    ).all()
    return {key: exercise_id for key, exercise_id in rows}


def _log_day(
    session: Session,
    user_id: int,
    *,
    on: date,
    sets: dict[str, int],
    exercises: dict[str, int],
) -> None:
    """One logged session with no plan behind it — every set here is OFF-PLAN by construction."""
    activity = Activity(
        user_id=user_id,
        activity_kind=ActivityKind("climbing"),
        occurred_on=on,
        duration_minutes=60,
        client_uuid=uuid.uuid4(),
    )
    session.add(activity)
    session.flush()
    session.add(
        LoggedSession(
            activity_id=activity.id,
            activity_kind=ActivityKind("climbing"),
            discipline=Discipline.BOULDER,
        )
    )
    session.flush()
    index = itertools.count(1)
    for aspect_key, count in sets.items():
        for _ in range(count):
            session.add(
                LoggedSet(
                    logged_session_id=activity.id,
                    client_uuid=uuid.uuid4(),
                    exercise_id=exercises[aspect_key],
                    set_index=next(index),
                )
            )
    session.flush()


def _get(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/api/sessions/volume", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _sets(body: dict[str, Any]) -> dict[str, int]:
    return {row["aspect_key"]: row["sets"] for row in body["aspects"]}


class _Row(NamedTuple):
    """What `_volume_query` yields, without a database to yield it."""

    occurred_on: date
    aspect_key: str
    sets: int


def _rows(*days: tuple[int, list[str]]) -> list[_Row]:
    """`(day offset, aspect keys)` pairs, newest day first, one set per row — query order."""
    return [_Row(_TODAY - timedelta(days=offset), key, 1) for offset, keys in days for key in keys]


def test_totals_are_counted_per_aspect_across_days_and_off_plan(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The whole point of the view, over sets that belong to no plan at all."""
    exercises = _exercise_per_aspect(db_session)
    user_id = _user_id(auth)
    _log_day(db_session, user_id, on=_TODAY, sets={_FINGERS: 3, _POWER: 1}, exercises=exercises)
    _log_day(
        db_session, user_id, on=_TODAY - timedelta(days=2), sets={_FINGERS: 2}, exercises=exercises
    )

    body = _get(api_client, auth)

    assert _sets(body)[_FINGERS] == 5
    assert _sets(body)[_POWER] == 1
    assert body["training_days"] == 2
    assert body["from_date"] == (_TODAY - timedelta(days=2)).isoformat()
    assert body["to_date"] == _TODAY.isoformat()
    assert body["truncated"] is False


def test_another_climbers_sets_are_never_counted(
    api_client: TestClient, auth: dict[str, str], other_auth: dict[str, str], db_session: Session
) -> None:
    """Every query scoped by the token's `user_id` — the one that must never regress."""
    exercises = _exercise_per_aspect(db_session)
    _log_day(
        db_session,
        _user_id(other_auth),
        on=_TODAY,
        sets={_FINGERS: 7},
        exercises=exercises,
    )

    body = _get(api_client, auth)

    assert _sets(body)[_FINGERS] == 0
    assert body["training_days"] == 0


def test_nothing_logged_is_every_aspect_at_zero_and_no_window(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """A climber with no history gets zeros and NULLs, never an empty list to guess from."""
    body = _get(api_client, auth)

    assert set(_sets(body).values()) == {0}
    assert body["from_date"] is None
    assert body["to_date"] is None
    assert body["training_days"] == 0
    assert body["truncated"] is False


def test_the_response_is_private_and_never_stored(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """One climber's training, so a shared-cache entry would hand it to a stranger."""
    response = api_client.get("/api/sessions/volume", headers=auth)

    assert response.headers["cache-control"] == _CACHE_CONTROL


def test_every_seeded_aspect_is_padded_in_sort_order() -> None:
    """An untrained aspect is the answer this view exists to give, so it cannot be absent."""
    body = _aspect_volume([])

    assert [row.aspect_key for row in body.aspects] == [spec.key for spec in CLIMBING_ASPECTS]
    assert {row.sets for row in body.aspects} == {0}


def test_the_read_asks_for_one_row_past_the_cap() -> None:
    """Without the extra row `truncated` cannot tell a full window from a cut one."""
    sql = str(_volume_query(1).compile(compile_kwargs={"literal_binds": True}))
    limit = re.search(r"LIMIT\s+(\d+)", sql)

    assert limit is not None, sql
    assert int(limit.group(1)) == _VOLUME_ROWS_MAX + 1


def test_exactly_the_cap_is_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The boundary. `truncated` claims older training is missing, so it must not cry wolf."""
    monkeypatch.setattr(session_routes, "_VOLUME_ROWS_MAX", 4)

    body = _aspect_volume(_rows((0, [_FINGERS, _POWER]), (1, [_FINGERS, _POWER])))

    assert body.truncated is False
    assert body.training_days == 2
    assert {row.aspect_key: row.sets for row in body.aspects}[_FINGERS] == 2


def test_past_the_cap_truncates_and_keeps_a_boundary_day_the_cut_missed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cut landing BETWEEN two days took nothing out of the younger one, so it stands."""
    monkeypatch.setattr(session_routes, "_VOLUME_ROWS_MAX", 4)

    body = _aspect_volume(_rows((0, [_FINGERS, _POWER]), (1, [_FINGERS, _POWER]), (2, [_FINGERS])))

    assert body.truncated is True
    assert body.training_days == 2
    assert {row.aspect_key: row.sets for row in body.aspects}[_FINGERS] == 2
    assert body.from_date == _TODAY - timedelta(days=1)


def test_a_day_the_cap_split_is_dropped_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ `_fold_sessions`' trap one shape along: a surviving half-day understates an aspect
    and `truncated` does not cover it, so the split day goes whole."""
    monkeypatch.setattr(session_routes, "_VOLUME_ROWS_MAX", 4)

    body = _aspect_volume(_rows((0, [_FINGERS, _POWER]), (1, [_FINGERS, _POWER, _FINGERS])))

    assert body.truncated is True
    assert body.training_days == 1
    assert {row.aspect_key: row.sets for row in body.aspects}[_FINGERS] == 1
    assert body.from_date == _TODAY
    assert body.to_date == _TODAY
