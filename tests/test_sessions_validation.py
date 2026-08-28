"""The bounds at the edge: what `PUT /api/sessions/{client_uuid}` refuses before any SQL runs.

**DB-free**, so it runs in the local gate — the models are validated directly rather than
through a request, because a `TestClient` would add an auth fixture and a session dependency
to a test about arithmetic. Mirrors `tests/test_profile_validation.py`.

Three of these have **no database half above zero**: the columns behind `actual_reps`,
`actual_work_seconds` and `actual_load_kg` `CHECK (>= 0)` and nothing more, so an over-large
value is a `DataError` with no constraint name to map — and a missing bound looks like one.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from server.app import _SAFE_VALIDATION_KEYS
from server.domain.grades import Discipline
from server.fields import DURATION_MINUTES_MAX, SETS_PER_REQUEST_MAX, DurationMinutes
from server.models import NOTES_MAX, SET_NOTE_MAX
from server.sessions.routes import LoggedSetIn, SessionLogRequest

_TODAY = datetime.now(UTC).date()
_NOW = datetime.now(UTC)


def _set(**overrides: Any) -> dict[str, Any]:
    """One valid set, so every negative case below differs from it in exactly one field."""
    payload: dict[str, Any] = {
        "client_uuid": str(uuid.uuid4()),
        "exercise_id": 1,
        "set_index": 1,
    }
    return payload | overrides


def _envelope(**overrides: Any) -> dict[str, Any]:
    """One valid envelope, for the same reason. Only the three required fields."""
    payload: dict[str, Any] = {
        "occurred_on": _TODAY.isoformat(),
        "duration_minutes": 75,
        "discipline": Discipline.BOULDER.value,
    }
    return payload | overrides


def test_a_full_payload_is_accepted() -> None:
    """The positive control. A model that rejects everything proves nothing at all."""
    request = SessionLogRequest.model_validate(
        _envelope(
            rpe=7,
            started_at=_NOW.isoformat(),
            notes="felt strong",
            location="Cafe Kraft",
            planned_session_id=3,
            finished=True,
            sets=[
                _set(
                    prescribed_set_id=9,
                    actual_reps=5,
                    actual_work_seconds=10,
                    actual_load_kg="-12.5",
                    rpe=8,
                    body_weight_kg="70.333",
                    body_weight_as_of=_TODAY.isoformat(),
                    note="add 2 kg",
                    completed_at=_NOW.isoformat(),
                )
            ],
        )
    )
    assert request.sets[0].actual_load_kg == Decimal("-12.5")
    assert request.sets[0].body_weight_kg == Decimal("70.333")


def test_the_defaults_make_a_start_put_the_minimum_payload() -> None:
    """Start sends three fields and nothing else; `finished` and `sets` must default."""
    request = SessionLogRequest.model_validate(_envelope())
    assert request.finished is False
    assert request.sets == []
    assert request.model_fields_set == {"occurred_on", "duration_minutes", "discipline"}


def test_duration_minutes_is_the_shared_bound_not_a_re_derived_one() -> None:
    """The endpoint imports `server.fields.DurationMinutes` rather than re-deriving 1440."""
    assert SessionLogRequest.__annotations__["duration_minutes"] is DurationMinutes
    assert (
        SessionLogRequest.model_validate(
            _envelope(duration_minutes=DURATION_MINUTES_MAX)
        ).duration_minutes
        == DURATION_MINUTES_MAX
    )
    with pytest.raises(ValidationError):
        SessionLogRequest.model_validate(_envelope(duration_minutes=3600))


def test_the_array_bound_is_the_resource_guard_it_exists_to_be() -> None:
    """`SETS_PER_REQUEST_MAX` sets are accepted; one more is `too_long`, not a 26 KiB write."""
    full = [_set(set_index=index) for index in range(1, SETS_PER_REQUEST_MAX + 1)]
    assert len(SessionLogRequest.model_validate(_envelope(sets=full)).sets) == SETS_PER_REQUEST_MAX
    with pytest.raises(ValidationError) as caught:
        SessionLogRequest.model_validate(_envelope(sets=[*full, _set(set_index=1)]))
    assert any(error["type"] == "too_long" for error in caught.value.errors())


def test_a_duplicate_client_uuid_never_reaches_postgres() -> None:
    """Two rows with one conflict key is `cardinality_violation` — a 500 with the payload logged."""
    shared = str(uuid.uuid4())
    with pytest.raises(ValidationError):
        SessionLogRequest.model_validate(
            _envelope(
                sets=[
                    _set(client_uuid=shared, set_index=1),
                    _set(client_uuid=shared, set_index=2),
                ]
            )
        )


def test_a_duplicate_set_index_is_refused() -> None:
    """`set_index` is the chronological 1..N ordinal of the whole session, so it is unique."""
    with pytest.raises(ValidationError):
        SessionLogRequest.model_validate(_envelope(sets=[_set(set_index=4), _set(set_index=4)]))


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"body_weight_kg": "70.0"}, id="a-weight-with-no-provenance"),
        pytest.param({"body_weight_as_of": _TODAY.isoformat()}, id="provenance-with-no-weight"),
    ],
)
def test_a_body_weight_and_its_as_of_date_travel_together(overrides: dict[str, Any]) -> None:
    """A snapshot with no provenance is exactly what the pair of columns exists to prevent."""
    with pytest.raises(ValidationError):
        LoggedSetIn.model_validate(_set(**overrides))


def test_neither_half_of_the_body_weight_pair_is_required() -> None:
    """Nothing prompts for a weigh-in with `show_body_metrics` off, so absence must be legal."""
    entry = LoggedSetIn.model_validate(_set())
    assert entry.body_weight_kg is None
    assert entry.body_weight_as_of is None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"sets": [], "sessionNotes": "x"}, id="a-camelCase-typo"),
        pytest.param({"srpe_load": 700}, id="a-generated-column"),
        pytest.param({"user_id": 2}, id="mass-assignment-of-the-owner"),
    ],
)
def test_the_envelope_forbids_unknown_fields(payload: dict[str, Any]) -> None:
    """`extra="forbid"`, so a probing or typo'd key is a 422 rather than a silent no-op."""
    with pytest.raises(ValidationError):
        SessionLogRequest.model_validate(_envelope(**payload))


def test_a_set_forbids_unknown_fields() -> None:
    """Same rule one level down — `logged_set_id` is the server's to mint, never the client's."""
    with pytest.raises(ValidationError):
        LoggedSetIn.model_validate(_set(id=17))


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"rpe": 0}, id="rpe-below-the-CHECK"),
        pytest.param({"rpe": 11}, id="rpe-above-the-CHECK"),
        pytest.param({"set_index": 0}, id="set-index-below-the-CHECK"),
        pytest.param({"set_index": SETS_PER_REQUEST_MAX + 1}, id="set-index-past-the-array"),
        pytest.param({"actual_reps": -1}, id="negative-reps"),
        pytest.param({"actual_reps": 501}, id="reps-that-would-overflow-SMALLINT-later"),
        pytest.param({"actual_work_seconds": -1}, id="negative-seconds"),
        pytest.param({"actual_work_seconds": 3601}, id="an-hour-and-one-second-in-one-set"),
        pytest.param({"actual_load_kg": "-501"}, id="assistance-past-the-column"),
        pytest.param({"actual_load_kg": "501"}, id="load-past-Numeric-5-2"),
        pytest.param(
            {"body_weight_kg": "19", "body_weight_as_of": _TODAY.isoformat()},
            id="weight-below-the-CHECK",
        ),
        pytest.param(
            {"body_weight_kg": "301", "body_weight_as_of": _TODAY.isoformat()},
            id="weight-above-the-CHECK",
        ),
        pytest.param({"note": "   "}, id="whitespace-is-not-a-note"),
        pytest.param({"note": "x" * (SET_NOTE_MAX + 1)}, id="a-note-past-its-column"),
        pytest.param({"exercise_id": 0}, id="an-id-that-cannot-exist"),
    ],
)
def test_a_set_outside_its_bounds_is_refused(overrides: dict[str, Any]) -> None:
    """Each of these mirrors a `CHECK`, a column length, or the only guard there is."""
    with pytest.raises(ValidationError):
        LoggedSetIn.model_validate(_set(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"actual_reps": 0}, id="a-failed-set-is-zero-reps-not-no-set"),
        pytest.param({"actual_work_seconds": 0}, id="zero-seconds"),
        pytest.param({"actual_load_kg": "-20.5"}, id="assisted-hangboarding-is-negative-load"),
        pytest.param({"actual_load_kg": "70.333"}, id="a-three-decimal-scale-reading"),
        pytest.param({"rpe": 1}, id="rpe-floor"),
        pytest.param({"rpe": 10}, id="rpe-ceiling"),
        pytest.param({"note": "  felt easy  "}, id="a-note-is-stripped-not-refused"),
    ],
)
def test_a_set_inside_its_bounds_is_accepted(overrides: dict[str, Any]) -> None:
    """The positive controls that keep the bounds above from being a blanket refusal."""
    assert LoggedSetIn.model_validate(_set(**overrides)) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"notes": "x" * (NOTES_MAX + 1)}, id="notes-past-their-column"),
        pytest.param({"location": "x" * 121}, id="a-location-past-its-column"),
        pytest.param({"location": " "}, id="whitespace-is-not-a-location"),
        pytest.param({"rpe": 11}, id="session-rpe-above-the-CHECK"),
        pytest.param({"duration_minutes": 0}, id="a-zero-minute-activity"),
        pytest.param({"planned_session_id": 0}, id="an-id-that-cannot-exist"),
        pytest.param({"discipline": "trad"}, id="a-value-outside-the-native-enum"),
    ],
)
def test_an_envelope_outside_its_bounds_is_refused(overrides: dict[str, Any]) -> None:
    """The free-text fields here are two of the eleven on CLAUDE.md's inventory."""
    with pytest.raises(ValidationError):
        SessionLogRequest.model_validate(_envelope(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"occurred_on": (_TODAY + timedelta(days=2)).isoformat()}, id="day-after-next"
        ),
        pytest.param({"occurred_on": (_TODAY - timedelta(days=400)).isoformat()}, id="last-year"),
        pytest.param({"started_at": (_NOW + timedelta(days=2)).isoformat()}, id="started-tomorrow"),
        pytest.param(
            {"started_at": (_NOW - timedelta(days=400)).isoformat()}, id="started-in-2025"
        ),
    ],
)
def test_a_date_or_instant_outside_the_window_is_refused(overrides: dict[str, Any]) -> None:
    """Bounds backdating and clock skew: an unbounded instant is an unbounded diary."""
    with pytest.raises(ValidationError):
        SessionLogRequest.model_validate(_envelope(**overrides))


def test_one_day_of_forward_slack_is_allowed_for_clock_skew() -> None:
    """A client in UTC+14 legitimately logs on what the server still calls yesterday."""
    request = SessionLogRequest.model_validate(
        _envelope(occurred_on=(_TODAY + timedelta(days=1)).isoformat())
    )
    assert request.occurred_on == _TODAY + timedelta(days=1)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"completed_at": (_NOW + timedelta(days=2)).isoformat()}, id="completed-tomorrow"
        ),
        pytest.param(
            {"completed_at": (_NOW - timedelta(days=400)).isoformat()}, id="completed-in-2025"
        ),
        pytest.param({"completed_at": "2026-08-28T10:00:00"}, id="naive-is-not-an-instant"),
        pytest.param(
            {
                "body_weight_kg": "70.0",
                "body_weight_as_of": (_TODAY + timedelta(days=2)).isoformat(),
            },
            id="a-weigh-in-that-has-not-happened",
        ),
    ],
)
def test_a_set_instant_outside_the_window_is_refused(overrides: dict[str, Any]) -> None:
    """`TIMESTAMPTZ` never naive, so a naive instant is a 422 rather than a guessed zone."""
    with pytest.raises(ValidationError):
        LoggedSetIn.model_validate(_set(**overrides))


def test_a_422_never_echoes_a_set_note_or_a_body_weight() -> None:
    """The allowlist in `server/app.py` is what saves us, so prove the raw error needs it."""
    marker = "SECRET-BETA-" + "x" * SET_NOTE_MAX
    with pytest.raises(ValidationError) as caught:
        SessionLogRequest.model_validate(
            _envelope(
                sets=[
                    _set(
                        note=marker,
                        body_weight_kg="987.65",
                        body_weight_as_of=_TODAY.isoformat(),
                    )
                ]
            )
        )
    raw = repr(caught.value.errors())
    assert "SECRET-BETA-" in raw, "the raw error does not carry the note, so this test is vacuous"
    published = repr(
        [
            {key: value for key, value in error.items() if key in _SAFE_VALIDATION_KEYS}
            for error in caught.value.errors()
        ]
    )
    assert "SECRET-BETA-" not in published
    assert "987" not in published
