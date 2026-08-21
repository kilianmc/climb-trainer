"""The bounds at the edge: what `PATCH /api/profile` refuses before any SQL runs.

CLAUDE.md asks for both halves of every bound — a `CHECK` in the migration *and* a
Pydantic `Field` — and they are not interchangeable. This file is about the second half,
and about what it buys: a 422 naming the field, with no database round trip, instead of an
`IntegrityError` in the middle of a handler. Under the testing policy these are "critical
domain rules": each one is a persisted constraint, and a bound that is silently missing
looks exactly like a bound that is present.

**DB-free**, so it runs in the local gate — the models are validated directly rather than
through a request, because a `TestClient` would add an auth fixture and a session
dependency to a test about arithmetic.

## `duration_minutes` has no endpoint yet, and is tested anyway

It is the specific obligation PR #9 owes (CLAUDE.md, "The domain schema"): `srpe_load` is
`rpe::integer * duration_minutes`, so a payload in **seconds** overflows `SMALLINT` before
it widens into the `INTEGER` column — and on the outbox path that is a write which retries
forever and can never succeed. The bound lives in `server/fields.py` from this PR, and
this is the test that keeps it there until PR #10's logging endpoint imports it.
"""

import pytest
from pydantic import TypeAdapter, ValidationError

from server.fields import DURATION_MINUTES_MAX, DurationMinutes
from server.models import SET_NOTE_MAX
from server.profile.routes import InjuryIn, ProfilePatchRequest

_duration = TypeAdapter(DurationMinutes)


@pytest.mark.parametrize("minutes", [1, 90, DURATION_MINUTES_MAX])
def test_a_plausible_duration_is_accepted(minutes: int) -> None:
    """The positive control. A bound that rejects everything proves nothing."""
    assert _duration.validate_python(minutes) == minutes


@pytest.mark.parametrize(
    "minutes",
    [
        pytest.param(0, id="zero-is-not-an-activity"),
        pytest.param(-30, id="negative"),
        pytest.param(DURATION_MINUTES_MAX + 1, id="one-past-the-check-constraint"),
        pytest.param(3600, id="an-hour-expressed-in-SECONDS"),
        pytest.param(5400, id="ninety-minutes-expressed-in-SECONDS"),
    ],
)
def test_an_out_of_range_duration_is_rejected_at_the_edge(minutes: int) -> None:
    """`le=1440` is the one that matters: 3600 is a lie about units, not a long session."""
    with pytest.raises(ValidationError):
        _duration.validate_python(minutes)


def test_an_empty_patch_is_valid_and_changes_nothing() -> None:
    """`None` everywhere means "not in this request", so an empty body is legal.

    Worth pinning: making any field required would break the per-step writes the whole
    onboarding flow depends on.
    """
    payload = ProfilePatchRequest()
    assert payload.target_grade_id is None
    assert payload.equipment_ids is None


@pytest.mark.parametrize(
    ("body", "empty"),
    [
        pytest.param({}, True, id="nothing-at-all"),
        pytest.param({"target_grade_id": None}, True, id="an-explicit-null-is-still-no-change"),
        pytest.param({"available_weekdays": 0}, False, id="zero-days-is-an-answer"),
        pytest.param({"equipment_ids": []}, False, id="an-empty-list-is-an-answer"),
        pytest.param({"injuries": []}, False, id="no-injuries-is-an-answer"),
    ],
)
def test_is_empty_separates_no_request_from_an_empty_ANSWER(
    body: dict[str, object], empty: bool
) -> None:
    """The handler skips every write when this is true, so the distinction is load-bearing.

    `{}` must not materialise a row (it used to, with placeholder values). `{"injuries": []}`
    must, because "no current injuries" is a real answer and stamping
    `injuries_reviewed_at` is the only record that the step was taken.
    """
    assert ProfilePatchRequest.model_validate(body).is_empty() is empty


@pytest.mark.parametrize(
    ("body", "was_sent"),
    [
        pytest.param({"injury_area_id": 3}, False, id="omitted-preserves"),
        pytest.param({"injury_area_id": 3, "note": None}, True, id="explicit-null-clears"),
        pytest.param({"injury_area_id": 3, "note": "sore"}, True, id="a-value-sets"),
    ],
)
def test_an_omitted_note_is_distinguishable_from_an_explicit_null(
    body: dict[str, object], was_sent: bool
) -> None:
    """`note` is the one field where omitted and null mean different things.

    After validation the value is `None` in both of the first two cases, so `model_fields_set`
    is the ONLY thing that can tell them apart — and the write path depends on it: omitting a
    note must not wipe the one piece of free text in the product.
    """
    entry = InjuryIn.model_validate(body)
    assert entry.note_was_sent is was_sent


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"sessions_per_week": 0}, id="sessions-below-1"),
        pytest.param({"sessions_per_week": 8}, id="sessions-above-7"),
        pytest.param({"available_weekdays": -1}, id="weekday-mask-negative"),
        pytest.param({"available_weekdays": 128}, id="weekday-mask-past-7-bits"),
        pytest.param({"target_grade_id": 0}, id="lookup-id-below-1"),
        pytest.param(
            {"aspect_ratings": [{"climbing_aspect_id": 1, "score": 0}]}, id="score-below-1"
        ),
        pytest.param(
            {"aspect_ratings": [{"climbing_aspect_id": 1, "score": 6}]}, id="score-above-5"
        ),
        pytest.param({"primary_discipline": "boulder"}, id="discipline-is-DERIVED-not-accepted"),
        pytest.param({"targetGradeId": 1}, id="camelCase-key-is-not-silently-ignored"),
        pytest.param({"equipment_ids": [1, 1]}, id="duplicate-equipment-id"),
        pytest.param(
            {"aspect_ratings": [{"climbing_aspect_id": 1, "score": 3}] * 2}, id="aspect-rated-twice"
        ),
        pytest.param({"injuries": [{"injury_area_id": 1}] * 2}, id="area-flagged-twice"),
        pytest.param({"injuries": [{"injury_area_id": 1, "note": ""}]}, id="empty-note"),
        pytest.param(
            {"injuries": [{"injury_area_id": 1, "note": "x" * (SET_NOTE_MAX + 1)}]},
            id="note-past-the-column-length",
        ),
    ],
)
def test_an_out_of_range_or_unknown_field_is_rejected(body: dict[str, object]) -> None:
    """Every bound the profile persists, plus `extra="forbid"`.

    The two `extra="forbid"` cases are here rather than in a file of their own because
    they fail the same way and for the same reason: a key the model does not name must
    never reach the ORM. `primary_discipline` is the interesting one — it is a real
    column, and refusing it is what stops a client setting a discipline that contradicts
    its own target grade.
    """
    with pytest.raises(ValidationError):
        ProfilePatchRequest.model_validate(body)


def test_a_list_longer_than_its_vocabulary_is_rejected() -> None:
    """Bounded even when every id in it is valid: an unbounded list is a write amplifier."""
    with pytest.raises(ValidationError):
        ProfilePatchRequest.model_validate({"equipment_ids": list(range(1, 500))})


def test_a_note_is_stripped_and_a_whole_step_validates() -> None:
    """The other positive control: the shape onboarding's last step actually sends."""
    payload = ProfilePatchRequest.model_validate(
        {"injuries": [{"injury_area_id": 3, "note": "  left A2  "}]}
    )
    assert payload.injuries is not None
    assert payload.injuries[0].note == "left A2"
