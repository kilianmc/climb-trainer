"""The reproducibility promise: `server/models.py::Plan` says version + input reproduces the tree.

DB-free.

Justified by CLAUDE.md's "project-wide invariants that silently rot" — this is a **GUARD**,
and its failure mode is the reason it exists: same generator version, same profile, a
different plan, and nothing anywhere says why. The missing third input is the exercise
library, so `library_digest()` folds it into the input and a content edit reads as a
different input rather than as a broken promise.

The subprocess is not ceremony. A digest built from `hash()` or from set iteration is stable
within one interpreter and different in the next, which is precisely the bug that would
survive an in-process assertion — `PYTHONHASHSEED` is randomised per process by default, and
this pins the value across two of them.

The other half of the same promise is below the digest tests: `generate()` twice yields
identical trees, and `generator_input()` is canonical and survives a JSON round trip. Those
are what the digest is *for* — a stable digest inside an unstable tree proves nothing.
"""

import dataclasses
import json
import subprocess  # noqa: S404 - a second interpreter is the only way to see a per-process hash
import sys
from datetime import date

import pytest

from server.domain.exercises import EXERCISES
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner import (
    GENERATOR_VERSION,
    PlannerInput,
    fingerprint,
    generate,
    generator_input,
    library_digest,
)

_MONDAY = date(2026, 8, 24)


def _input() -> PlannerInput:
    """One plannable climber. Gap 3, so the plan covers all five training phases."""
    current = ordinal_of(GradeSystemKey.FRENCH, "6a")
    return PlannerInput(
        discipline=Discipline.SPORT,
        current_ordinal=current,
        target_ordinal=current + 3,
        sessions_per_week=3,
        available_weekdays=0b0100101,
        strength_aspect_key="technique",
        weakness_aspect_key="finger_strength",
        open_injury_keys=("elbow",),
        equipment_keys=("hangboard", "pull_up_bar"),
        start_date=_MONDAY,
    )


_DIGEST_IN_A_FRESH_PROCESS = (
    "import os, sys; "
    "sys.path.insert(0, os.getcwd()); "
    "from server.domain.planner import library_digest; "
    "print(library_digest())"
)


def test_the_digest_is_the_same_in_a_second_interpreter() -> None:
    """Stable across processes, not just within one: the value is persisted and compared later."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        [sys.executable, "-c", _DIGEST_IN_A_FRESH_PROCESS],
        capture_output=True,
        check=True,
        text=True,
    )
    assert completed.stdout.strip() == library_digest()


def test_the_digest_is_stable_when_nothing_changes() -> None:
    assert library_digest() == library_digest()


def test_editing_one_prescription_moves_the_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive control. A detector that cannot see its own violation is worse than none.

    The edit is deliberately the smallest that could matter — one integer on one set of one
    exercise — because a digest that only notices an added exercise would let every reword
    and every retuned prescription through, and those are the edits that actually happen.
    """
    before = library_digest()
    first, *rest = EXERCISES
    tweaked = dataclasses.replace(
        first,
        prescriptions=(
            dataclasses.replace(first.prescriptions[0], sets=first.prescriptions[0].sets + 1),
            *first.prescriptions[1:],
        ),
    )
    monkeypatch.setattr(fingerprint, "EXERCISES", (tweaked, *rest))
    assert library_digest() != before


def test_reordering_the_library_moves_the_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order is content: selection walks the library in authored order, so a reorder changes
    the generated plan and has to read as a different input."""
    before = library_digest()
    monkeypatch.setattr(fingerprint, "EXERCISES", (EXERCISES[1], EXERCISES[0], *EXERCISES[2:]))
    assert library_digest() != before


def test_generating_twice_yields_an_identical_tree() -> None:
    """The promise itself, at the only level it can actually break.

    Frozen dataclasses compare by value all the way down, so this is a deep comparison of
    every mesocycle, week, session, block and set — which is what makes it able to see the
    failure that matters: one exercise chosen differently in one session of one week.
    """
    assert generate(_input()) == generate(_input())


def test_generator_input_is_canonical_and_survives_a_json_round_trip() -> None:
    """It is stored in `plan.generator_input` (`jsonb`) and compared against a later run.

    So it has to survive the trip: anything that reaches it must be a JSON scalar or a list
    of them, and the serialisation must be byte-stable. A `date` or an enum left raw would
    raise at insert time in #11b rather than here.
    """
    payload = generator_input(_input())
    round_tripped = json.loads(json.dumps(payload, sort_keys=True))
    assert round_tripped == payload
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        generator_input(_input()), sort_keys=True
    )


def test_generator_input_carries_the_version_the_digest_and_every_input_field() -> None:
    """The library is the third input, and the version is the second.

    Asserted as a key set rather than a value snapshot: a new field on `PlannerInput` joins
    automatically via `dataclasses.fields()`, and this is what fails if somebody replaces
    that with a hand-written list and forgets one.
    """
    payload = generator_input(_input())
    expected = {field.name for field in dataclasses.fields(_input())}
    assert set(payload) == expected | {"generator_version", "library_digest"}
    assert payload["generator_version"] == GENERATOR_VERSION
    assert payload["library_digest"] == library_digest()
    assert payload["start_date"] == _MONDAY.isoformat()


def test_a_content_edit_changes_the_input_rather_than_breaking_the_promise() -> None:
    """The reason the digest is in there at all, stated as a behaviour.

    Same version, same profile, an edited library: the tree legitimately differs, and the
    recorded input differs with it. Without the digest the two would be indistinguishable
    from a broken generator.
    """
    before = generator_input(_input())
    first, *rest = EXERCISES
    tweaked = dataclasses.replace(
        first,
        prescriptions=(
            dataclasses.replace(first.prescriptions[0], sets=first.prescriptions[0].sets + 1),
            *first.prescriptions[1:],
        ),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fingerprint, "EXERCISES", (tweaked, *rest))
        after = generator_input(_input())
    assert after["generator_version"] == before["generator_version"]
    assert after["library_digest"] != before["library_digest"]
