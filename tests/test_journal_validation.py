"""The bounds at the edge: what `PUT /api/journal/{client_uuid}` refuses before any SQL runs.

**DB-free**, so it runs in the local gate — the request model is validated directly rather than
through a request, mirroring `tests/test_sessions_validation.py`. Nothing here touches a row and
nothing in `tests/test_journal_log.py` restates these.

⚠️ **The `not_empty` arm is the one that matters.** Without it an entry carrying only a date is a
named `CHECK` violation in the middle of the handler — a 500 the client reads as our fault, and
on a retrying client a payload that can never succeed (`server/fields.py`).
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from server.journal.routes import _NOT_EMPTY_FIELDS, JournalEntryRequest
from server.models import JOURNAL_BODY_MAX, Base

_TODAY = datetime.now(UTC).date()

# Read off `Base.metadata`, not the mapped `__table__`, which mypy types as a `FromClause`
# and will not let anybody read a constraint list off.
_TABLE = Base.metadata.tables["journal_entry"]

# The five fields the CHECK counts, each as a payload fragment that satisfies it ALONE. A
# weigh-in on its own is in here deliberately: that is why `body` is nullable.
_ALONE: dict[str, Any] = {
    "body": "fingers feel tweaky",
    "feel": 3,
    "sleep_quality": 5,
    "skin": 1,
    "body_weight_kg": "71.4",
}


def _entry(**overrides: Any) -> dict[str, Any]:
    """One valid entry, so every negative case below differs from it in exactly one field."""
    payload: dict[str, Any] = {"entry_date": _TODAY.isoformat(), "feel": 3}
    return payload | overrides


def test_a_full_payload_is_accepted() -> None:
    """The positive control. A model that rejects everything proves nothing at all."""
    request = JournalEntryRequest.model_validate(
        _entry(
            body="  felt strong, skin holding up  ",
            feel=4,
            sleep_quality=5,
            skin=3,
            body_weight_kg="71.4",
            logged_session_id=12,
        )
    )
    assert request.body == "felt strong, skin holding up"
    assert (request.feel, request.sleep_quality, request.skin) == (4, 5, 3)
    assert request.logged_session_id == 12


def test_the_edge_VALIDATOR_NAMES_EXACTLY_THE_COLUMNS_THE_CHECK_NAMES() -> None:
    """⚠️ A validator narrower than the CHECK 500s; wider it 422s a legal row. Read OFF the
    constraint, so a sixth column added to `not_empty` alone lands red here."""
    check = next(
        constraint
        for constraint in _TABLE.constraints
        if isinstance(constraint, CheckConstraint) and str(constraint.name).endswith("not_empty")
    )
    sql = str(check.sqltext)
    # ⚠️ A word boundary, not `in`: `body` is a prefix of `body_weight_kg`, so a substring test
    # would credit `body` off its neighbour's clause and read green with the arm missing.
    named = {
        name
        for name in _TABLE.columns.keys()
        if re.search(rf"\b{re.escape(name)} IS NOT NULL", sql)
    }
    assert len(named) == 5, f"the CHECK names {named}, which is not the five columns expected"
    assert named == set(_NOT_EMPTY_FIELDS)


@pytest.mark.parametrize("field", sorted(_ALONE))
def test_each_of_the_five_fields_SATISFIES_THE_CHECK_ALONE(field: str) -> None:
    """Not stricter than the database: a weigh-in with nothing written is a real entry."""
    request = JournalEntryRequest.model_validate(
        {"entry_date": _TODAY.isoformat(), field: _ALONE[field]}
    )
    assert getattr(request, field) is not None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="a_date_alone"),
        pytest.param({"logged_session_id": 12}, id="a_date_and_a_session"),
        pytest.param({"body": None, "feel": None}, id="explicit_nulls"),
    ],
)
def test_an_ENTRY_CARRYING_NOTHING_is_refused_AT_THE_EDGE(payload: dict[str, Any]) -> None:
    """`entry_date` and `logged_session_id` are not content. This is the 500 that must not be."""
    with pytest.raises(ValidationError) as caught:
        JournalEntryRequest.model_validate({"entry_date": _TODAY.isoformat()} | payload)
    assert "at least one of" in str(caught.value)


@pytest.mark.parametrize("field", ["feel", "sleep_quality", "skin"])
@pytest.mark.parametrize("value", [0, -1, 6, 100])
def test_a_wellbeing_score_OUTSIDE_ONE_TO_FIVE_is_refused(field: str, value: int) -> None:
    """`CHECK (BETWEEN 1 AND 5)` on all three columns; `0` is not "unanswered", NULL is."""
    with pytest.raises(ValidationError):
        JournalEntryRequest.model_validate(_entry(**{field: value}))


@pytest.mark.parametrize("field", ["feel", "sleep_quality", "skin"])
@pytest.mark.parametrize("value", [1, 5])
def test_both_ENDS_of_the_wellbeing_scale_are_INSIDE_it(field: str, value: int) -> None:
    """The inclusive half. An exclusive bound would refuse the two most common answers."""
    assert getattr(JournalEntryRequest.model_validate(_entry(**{field: value})), field) == value


@pytest.mark.parametrize("value", ["19.9", "0", "-1", "300.01", "1000"])
def test_a_weigh_in_outside_the_columns_range_is_refused(value: str) -> None:
    """`CHECK (body_weight_kg BETWEEN 20 AND 300)`, mirrored so it is a 422 and not a 500."""
    with pytest.raises(ValidationError):
        JournalEntryRequest.model_validate(_entry(body_weight_kg=value))


@pytest.mark.parametrize("value", ["20", "300", "71.333"])
def test_a_plausible_weigh_in_is_accepted_including_an_unrounded_one(value: str) -> None:
    """No `decimal_places`: a scale reading of 71.333 is a measurement, not a 422 (`LoadKg`)."""
    assert JournalEntryRequest.model_validate(_entry(body_weight_kg=value)).body_weight_kg


@pytest.mark.parametrize("value", ["", "   ", "\n\t "], ids=["empty", "spaces", "whitespace"])
def test_a_blank_body_is_refused_rather_than_stored_as_an_empty_string(value: str) -> None:
    """`min_length=1` after stripping: two spellings of "nothing said" is one too many."""
    with pytest.raises(ValidationError):
        JournalEntryRequest.model_validate(_entry(body=value))


def test_a_body_longer_than_the_column_is_refused() -> None:
    """`String(JOURNAL_BODY_MAX)` mirrored, so an over-long paste is a 422 and not a `DataError`."""
    JournalEntryRequest.model_validate(_entry(body="a" * JOURNAL_BODY_MAX))
    with pytest.raises(ValidationError):
        JournalEntryRequest.model_validate(_entry(body="a" * (JOURNAL_BODY_MAX + 1)))


@pytest.mark.parametrize("days", [-366, -400, 2, 30])
def test_an_entry_date_outside_the_window_is_refused(days: int) -> None:
    """The shared window in `server/fields.py`: a year back, a day forward for UTC+14 skew."""
    with pytest.raises(ValidationError):
        JournalEntryRequest.model_validate(
            _entry(entry_date=(_TODAY + timedelta(days=days)).isoformat())
        )


@pytest.mark.parametrize("days", [0, -1, -365, 1])
def test_an_entry_date_inside_the_window_is_accepted(days: int) -> None:
    """Backdating a diary entry a year is a real thing to want; both ends are inclusive."""
    assert JournalEntryRequest.model_validate(
        _entry(entry_date=(_TODAY + timedelta(days=days)).isoformat())
    ).entry_date == _TODAY + timedelta(days=days)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"goal_weight_kg": 65}, id="a_goal_weight"),
        pytest.param({"target_weight_kg": 65}, id="a_target_weight"),
        pytest.param({"bmi": 21}, id="a_bmi"),
        pytest.param({"notes": "typo for body"}, id="a_plausible_typo"),
    ],
)
def test_an_UNKNOWN_FIELD_is_refused(payload: dict[str, Any]) -> None:
    """`extra="forbid"`. The first three could never be stored — there is no column — and a
    silently ignored one would look accepted."""
    with pytest.raises(ValidationError):
        JournalEntryRequest.model_validate(_entry(**payload))


def test_a_logged_session_id_below_the_sanity_floor_is_refused() -> None:
    """`LookupId` — an id is resolved by looking it up, never by trusting its shape."""
    with pytest.raises(ValidationError):
        JournalEntryRequest.model_validate(_entry(logged_session_id=0))
