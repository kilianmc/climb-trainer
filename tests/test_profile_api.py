"""`GET`/`PATCH /api/profile` against real Postgres.

Two of CLAUDE.md's "write tests for" bullets, and the first one is the reason this file
exists at all:

- **anything that saves or submits.** The partial upsert is the whole engineering
  consequence of the plan's Zeigarnik point: an abandoned onboarding must resume, so
  step 1 has to create the row and step 4 must not wipe what steps 1-3 wrote. A
  handler that dropped the earlier answers would pass every unit test of its own step.
- **core user paths** — onboarding is the first thing a new account does.

Integration tests on purpose. The risky parts are the `ON CONFLICT` clauses (including the
one that infers the partial unique index from `0005`), the delete-then-insert set
replacement, and the omitted-vs-null note rule — none of which a unit test of the handler
would exercise, because all three are SQL. **Skips without `DATABASE_URL`**
(`conftest.py`); CI runs them for real.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.domain.vocabulary import CLIMBING_ASPECTS
from server.models import (
    ClimbingAspect,
    Equipment,
    Grade,
    GradeSystem,
    InjuryArea,
    UserInjury,
    UserProfile,
)

_EMAIL = "onboarding@example.com"
_PASSWORD = "a-long-enough-passphrase"

# Monday, Wednesday, Friday — bits 0, 2 and 4.
_MON_WED_FRI = 0b0010101


@pytest.fixture
def auth(api_client: TestClient, invite_code: str) -> dict[str, str]:
    """A registered account's bearer header. Registration mints one, so this is one call."""
    response = api_client.post(
        "/api/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD, "invite_code": invite_code},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _patch(client: TestClient, auth: dict[str, str], body: dict[str, object]) -> dict[str, Any]:
    """One step's request. `Any` on the way out because every assertion indexes the body."""
    response = client.patch("/api/profile", json=body, headers=auth)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _first_grade_id(session: Session, discipline: str) -> int:
    """Any real grade of a discipline. The ladder's contents belong to `test_grades.py`."""
    grade_id = session.scalar(
        select(Grade.id)
        .join(GradeSystem, Grade.grade_system_id == GradeSystem.id)
        .where(GradeSystem.discipline == discipline)
        .order_by(Grade.ordinal)
        .limit(1)
    )
    assert grade_id is not None, f"no seeded {discipline} grade"
    return grade_id


def _lookup_ids(
    session: Session, table: type[Equipment] | type[InjuryArea], *keys: str
) -> list[int]:
    """Ids for seeded keys, **in the order the keys were asked for**.

    Not in id order: these are unpacked positionally below, and a caller silently getting
    them back sorted differently is a test that asserts the wrong pairing.
    """
    rows = session.execute(select(table.key, table.id).where(table.key.in_(keys))).all()
    by_key = {row.key: row.id for row in rows}
    missing = [key for key in keys if key not in by_key]
    assert not missing, f"seed is missing {missing}"
    return [by_key[key] for key in keys]


def test_a_new_account_has_an_empty_profile_and_no_row_is_created_by_reading_it(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """A GET must not write. "Create it on first read" is the touch-on-read accident."""
    response = api_client.get("/api/profile", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()

    # NULL everywhere: since 0005 "not answered" is a state the schema can express, and
    # `_read_profile` reports a missing row as exactly that rather than as placeholders.
    assert body["target_grade_id"] is None
    assert body["primary_discipline"] is None
    assert body["sessions_per_week"] is None
    assert body["available_weekdays"] is None
    assert body["equipment_reviewed_at"] is None
    assert body["injuries_reviewed_at"] is None
    assert body["equipment_ids"] == []
    assert body["aspect_ratings"] == []
    assert body["injuries"] == []
    # The one non-null field: a setting with a server default, not an answer.
    assert body["show_body_metrics"] is True

    assert db_session.scalars(select(UserProfile)).all() == []


def test_step_one_creates_the_row_and_derives_the_discipline_from_the_grade(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The row exists after the FIRST step, which is what makes resuming possible.

    `primary_discipline` is derived, never sent: a rope target grade means a rope goal,
    and the client cannot make the two disagree.
    """
    grade_id = _first_grade_id(db_session, "sport")
    body = _patch(api_client, auth, {"target_grade_id": grade_id})

    assert body["target_grade_id"] == grade_id
    assert body["primary_discipline"] == "sport"
    # ⚠️ The columns this step did not touch are still NULL. Before 0005 they carried
    # placeholders — `sessions_per_week = 3` — which read as an answer to anything that
    # asked "is it set?", including the completion bar and the plan generator.
    assert body["sessions_per_week"] is None
    assert body["available_weekdays"] is None


def test_an_abandoned_onboarding_resumes_rather_than_restarting(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The load-bearing test of this PR.

    Four steps, four requests, each carrying ONLY its own field — as onboarding sends
    them. Every earlier answer has to survive every later request; a handler that
    replaced the row instead of patching it would leave the last step's answer alone in
    a profile that reads as 20% complete.
    """
    grade_id = _first_grade_id(db_session, "boulder")
    equipment_ids = _lookup_ids(db_session, Equipment, "bouldering_wall", "hangboard")
    aspect_ids = list(
        db_session.scalars(select(ClimbingAspect.id).order_by(ClimbingAspect.sort_order))
    )
    injury_ids = _lookup_ids(db_session, InjuryArea, "elbow")

    _patch(api_client, auth, {"target_grade_id": grade_id})
    _patch(api_client, auth, {"sessions_per_week": 3, "available_weekdays": _MON_WED_FRI})
    _patch(api_client, auth, {"equipment_ids": equipment_ids})
    _patch(
        api_client,
        auth,
        {
            "aspect_ratings": [
                {"climbing_aspect_id": aspect_id, "score": 3} for aspect_id in aspect_ids
            ]
        },
    )
    final = _patch(
        api_client, auth, {"injuries": [{"injury_area_id": injury_ids[0], "note": "sore"}]}
    )

    assert final["target_grade_id"] == grade_id
    assert final["sessions_per_week"] == 3
    assert final["available_weekdays"] == _MON_WED_FRI
    assert final["equipment_ids"] == sorted(equipment_ids)
    assert [entry["score"] for entry in final["aspect_ratings"]] == [3] * len(CLIMBING_ASPECTS)
    assert final["injuries"] == [
        {
            "injury_area_id": injury_ids[0],
            "note": "sore",
            "started_on": final["injuries"][0]["started_on"],
        }
    ]

    # And the state is readable back on a fresh request, not just echoed by the writer.
    reread = api_client.get("/api/profile", headers=auth).json()
    assert reread == final


def test_a_list_field_REPLACES_the_set_and_an_empty_list_clears_it(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The collection semantics, which are the other half of "partial".

    A scalar left out is untouched; a list that IS sent is the whole answer. Both
    directions matter — an additive-only implementation makes a deselected checkbox
    impossible to express.
    """
    wall, hangboard, rings = _lookup_ids(
        db_session, Equipment, "bouldering_wall", "hangboard", "gymnastic_rings"
    )

    first = _patch(api_client, auth, {"equipment_ids": [wall, hangboard]})
    assert first["equipment_ids"] == sorted([wall, hangboard])
    # Deselect one, select another.
    second = _patch(api_client, auth, {"equipment_ids": [wall, rings]})
    assert second["equipment_ids"] == sorted([wall, rings])
    assert _patch(api_client, auth, {"equipment_ids": []})["equipment_ids"] == []


def test_dropping_an_injury_flag_RESOLVES_it_and_keeps_the_history(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """Unflagging is not deleting.

    "Resolved in March" is what lets the generator reintroduce the exercises it was
    withholding, so the row survives with `resolved_on` set — and stops being returned
    as an open injury. A delete would lose that, silently and permanently.
    """
    elbow, shoulder = _lookup_ids(db_session, InjuryArea, "elbow", "shoulder")

    _patch(api_client, auth, {"injuries": [{"injury_area_id": elbow}]})
    body = _patch(api_client, auth, {"injuries": [{"injury_area_id": shoulder}]})

    assert [entry["injury_area_id"] for entry in body["injuries"]] == [shoulder]

    rows = db_session.execute(
        select(UserInjury.injury_area_id, UserInjury.resolved_on).order_by(UserInjury.id)
    ).all()
    assert [(row.injury_area_id, row.resolved_on is None) for row in rows] == [
        (elbow, False),
        (shoulder, True),
    ]


def test_re_rating_an_aspect_updates_the_score_rather_than_duplicating_the_row(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`ON CONFLICT DO UPDATE` on the composite key, and `rated_at` moves with it."""
    aspect_id = db_session.scalar(select(ClimbingAspect.id).order_by(ClimbingAspect.sort_order))
    assert aspect_id is not None

    first = _patch(
        api_client, auth, {"aspect_ratings": [{"climbing_aspect_id": aspect_id, "score": 2}]}
    )
    second = _patch(
        api_client, auth, {"aspect_ratings": [{"climbing_aspect_id": aspect_id, "score": 5}]}
    )

    assert len(second["aspect_ratings"]) == 1
    assert second["aspect_ratings"][0]["score"] == 5
    assert second["aspect_ratings"][0]["rated_at"] >= first["aspect_ratings"][0]["rated_at"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"target_grade_id": 10_000_000}, id="grade"),
        pytest.param({"equipment_ids": [10_000_000]}, id="equipment"),
        pytest.param(
            {"aspect_ratings": [{"climbing_aspect_id": 10_000_000, "score": 3}]}, id="aspect"
        ),
        pytest.param({"injuries": [{"injury_area_id": 10_000_000}]}, id="injury_area"),
    ],
)
def test_an_id_that_does_not_exist_is_a_422_and_writes_nothing(
    api_client: TestClient, auth: dict[str, str], body: dict[str, object], db_session: Session
) -> None:
    """Resolved against the seeded table, not left to a foreign key.

    The FK would raise mid-handler — a 500 for a client mistake, with the transaction
    already aborted so nothing else in the request could report anything useful.

    ⚠️ **"Writes nothing" is asserted on the TABLE, and the first version of this test
    could not see it.** It only checked that `target_grade_id` came back null, which a
    freshly-created placeholder row satisfied — so it passed while three of its four
    parameters left a `user_profile` row behind. (Production was saved by
    `get_session`'s rollback on close; the test harness reuses the transaction and has no
    such teardown, which is exactly why the test could not detect it.) The fix is in the
    handler: every id is resolved BEFORE the first write. This assertion is what proves it.
    """
    response = api_client.patch("/api/profile", json=body, headers=auth)
    assert response.status_code == 422, response.text
    assert db_session.scalars(select(UserProfile)).all() == [], (
        "a rejected patch left a user_profile row behind — validate every lookup id "
        "before the first write"
    )


def test_one_users_profile_is_never_visible_to_another(
    api_client: TestClient, auth: dict[str, str], invite_code: str, db_session: Session
) -> None:
    """The scoping rule, exercised rather than asserted about.

    Every query is keyed on the token's `user_id` and the endpoint takes no id at all, so
    there is no parameter to substitute — this is the test that would fail if one were
    ever added.
    """
    grade_id = _first_grade_id(db_session, "boulder")
    _patch(api_client, auth, {"target_grade_id": grade_id})

    other = api_client.post(
        "/api/auth/register",
        json={
            "email": "someone-else@example.com",
            "password": _PASSWORD,
            "invite_code": invite_code,
        },
    )
    assert other.status_code == 201, other.text
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert api_client.get("/api/profile", headers=headers).json()["target_grade_id"] is None


def test_an_empty_patch_writes_nothing_at_all(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`PATCH {}` is a read in a write's clothing and must not materialise a row.

    It used to create one, with placeholder values, purely because the handler always ran
    its upsert. That row then reported `sessions_per_week = 3` to everything that asked.
    """
    response = api_client.patch("/api/profile", json={}, headers=auth)
    assert response.status_code == 200, response.text
    assert db_session.scalars(select(UserProfile)).all() == []


def test_submitting_the_injuries_step_with_NO_injuries_still_records_the_answer(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """The whole reason `injuries_reviewed_at` exists.

    "Nothing wrong" writes zero `user_injury` rows, so without this column the honest
    answer to the last onboarding step is indistinguishable from never having been asked —
    and the completion bar can never reach 100% for a healthy climber without lying.
    """
    body = _patch(api_client, auth, {"injuries": []})

    assert body["injuries"] == []
    assert body["injuries_reviewed_at"] is not None

    stamped = body["injuries_reviewed_at"]
    assert api_client.get("/api/profile", headers=auth).json()["injuries_reviewed_at"] == stamped


def test_submitting_the_equipment_step_with_NOTHING_selected_records_the_answer(
    api_client: TestClient, auth: dict[str, str]
) -> None:
    """The twin of the injuries test, and the reason the equipment step is not a dead end.

    "I own none of this" writes zero `user_equipment` rows, so without this column an empty
    selection is indistinguishable from never having been asked — which is what made the
    step unanswerable for an outdoor-only climber. A regression that never stamps the column
    (or stamps it on GET) would otherwise pass the entire suite: this file had no assertion
    on it at all.
    """
    body = _patch(api_client, auth, {"equipment_ids": []})

    assert body["equipment_ids"] == []
    assert body["equipment_reviewed_at"] is not None

    # And it is not touched by a read, nor by a patch that says nothing about equipment.
    stamped = body["equipment_reviewed_at"]
    assert api_client.get("/api/profile", headers=auth).json()["equipment_reviewed_at"] == stamped
    assert (
        _patch(api_client, auth, {"show_body_metrics": False})["equipment_reviewed_at"] == stamped
    )


def test_selecting_equipment_stamps_the_column_too(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The other half: rows AND the timestamp, so completion never has to count rows."""
    wall = _lookup_ids(db_session, Equipment, "bouldering_wall")[0]
    body = _patch(api_client, auth, {"equipment_ids": [wall]})

    assert body["equipment_ids"] == [wall]
    assert body["equipment_reviewed_at"] is not None


def test_re_submitting_a_flag_keeps_ONE_open_row_and_its_original_start_date(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """`ON CONFLICT` on the partial unique index added in `0005`.

    Two things at once. The index makes a second open row for the same area impossible —
    which is what makes two concurrent PATCHes safe, since the loser of the race updates
    instead of inserting a duplicate that would show up as a repeated checkbox and a
    doubled contraindication. And `started_on` is deliberately left out of the `DO UPDATE`
    set, so re-submitting a flag does not restart the clock on an injury someone has had
    for three weeks.
    """
    elbow = _lookup_ids(db_session, InjuryArea, "elbow")[0]

    first = _patch(api_client, auth, {"injuries": [{"injury_area_id": elbow}]})
    second = _patch(api_client, auth, {"injuries": [{"injury_area_id": elbow, "note": "worse"}]})

    assert len(second["injuries"]) == 1
    assert second["injuries"][0]["started_on"] == first["injuries"][0]["started_on"]
    assert (
        db_session.scalar(
            select(func.count()).select_from(UserInjury).where(UserInjury.resolved_on.is_(None))
        )
        == 1
    )


def test_an_omitted_note_PRESERVES_and_an_explicit_null_CLEARS(
    api_client: TestClient, auth: dict[str, str], db_session: Session
) -> None:
    """The one field where omitted and null differ, and it is the only free text here.

    `{"injuries": [{"injury_area_id": 3}]}` is the natural "keep this flagged" body — it is
    what the resume path and every hand-written client sends — so treating an omitted note
    as null would silently wipe what the user wrote. Pydantic's `model_fields_set` is the
    only thing that can tell the two apart: after validation the value is `None` either way.
    """
    elbow = _lookup_ids(db_session, InjuryArea, "elbow")[0]

    written = _patch(api_client, auth, {"injuries": [{"injury_area_id": elbow, "note": "sore"}]})
    assert written["injuries"][0]["note"] == "sore"

    kept = _patch(api_client, auth, {"injuries": [{"injury_area_id": elbow}]})
    assert kept["injuries"][0]["note"] == "sore", "an omitted note must not clear the stored one"

    cleared = _patch(api_client, auth, {"injuries": [{"injury_area_id": elbow, "note": None}]})
    assert cleared["injuries"][0]["note"] is None
