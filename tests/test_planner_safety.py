"""⚠️ GUARD. Nothing the generator says to a user may suggest losing weight.
DB-free. CLAUDE.md's hard rule binds the plan generator by name, and this is the only thing in the
gate that can see a generated *sentence*: `tests/test_schema_no_weight_targets.py` guards
identifiers and is structurally blind to prose, which is where a recommendation would live.

The second half is the `String(80)` widths on `plan.name` and `planned_session.title`. The
blueprint deliberately does not check them (a column width is not a CHECK), so a string that fits
the preview and not the column would first appear in PR #11b's bulk insert. Shown to fail before
being trusted; captures in `.claude/pr-11a-state.md`.
"""

import re
from datetime import date
from typing import Any

import pytest
from sqlalchemy import String
from sqlalchemy.sql.elements import KeyedColumnElement

from server.domain.exercises import EXERCISES
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner.blueprint import PlanBlueprint
from server.domain.planner.contract import REFUSAL_MESSAGES, PlannerInput
from server.domain.planner.generate import generate
from server.domain.vocabulary import INJURY_AREAS
from server.models import Plan, PlannedSession

# ⚠️ PHRASES, not words, and that is the whole design of this matcher. `weight` on its own
# is in the vocabulary the app legitimately shows — "Weight belt or vest" and "Free weights"
# are equipment rows, and a shortfall message names them — so a bare stem would fire on an
# honest sentence, and the tempting fix for that false positive is to delete the entry. Same
# trap `IMPROVISED_EDGE_RE` documents for `"door"` inside `"outdoor"`.
#
# The list is the euphemism family, because the rule is about the *advice* and not the word:
# "get to your climbing weight" and "lose a couple of kilos" are the same sentence.
_WEIGHT_LOSS_PATTERNS = (
    r"\bweight loss\b",
    r"\blos(?:e|ing|s of)\s+(?:weight|body ?weight|kilos?|kgs?|pounds?|lbs?)\b",
    # Up to three intervening words, because "drop a couple of kilos" is the sentence
    # somebody would actually write and a fixed `(?:some )?` missed it.
    r"\b(?:drop|shed|cut|reduce)\s+(?:\S+\s+){0,3}(?:weight|body ?weight|kilos?|kgs?|pounds?)\b",
    r"\b(?:goal|target|ideal|climbing|competition|comp|racing|send|performance) weight\b",
    r"\bbody fat\b",
    r"\bbmi\b",
    r"\blighter\b",
    r"\bslim(?:mer|ming)?\b",
    r"\bleaner\b",
    r"\bcalorie",
    r"\bdiet(?:ing)?\b",
    r"\bstrength[- ]to[- ]weight\b",
)
_WEIGHT_LOSS_RE = re.compile("|".join(_WEIGHT_LOSS_PATTERNS), re.IGNORECASE)

_MONDAY = date(2026, 8, 24)
_FULLY_EQUIPPED = tuple(sorted({key for spec in EXERCISES for key in spec.equipment_keys}))
_ALL_INJURIES = tuple(sorted(spec.key for spec in INJURY_AREAS))


def _plan(**overrides: object) -> PlanBlueprint:
    current = ordinal_of(GradeSystemKey.FRENCH, "6a")
    fields: dict[str, object] = {
        "discipline": Discipline.SPORT,
        "current_ordinal": current,
        "target_ordinal": current + 3,
        "sessions_per_week": 3,
        "available_weekdays": 0b0100101,
        "strength_aspect_key": "technique",
        "weakness_aspect_key": "finger_strength",
        "open_injury_keys": (),
        "equipment_keys": (),
        "start_date": _MONDAY,
    }
    fields.update(overrides)
    return generate(PlannerInput(**fields))  # type: ignore[arg-type]


def _every_string(plan: PlanBlueprint) -> list[str]:
    """Every string in a plan a user can read: name, titles, shortfalls, notes."""
    strings = [plan.name, *(note.message for note in plan.notes)]
    strings.extend(shortfall.message for shortfall in plan.shortfalls)
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                strings.append(session.title)
                strings.extend(shortfall.message for shortfall in session.shortfalls)
                strings.extend(
                    block.shortfall.message
                    for block in session.blocks
                    if block.shortfall is not None
                )
    return strings


# Every arm the generator has: fully equipped and clean, gearless, injured, gearless and
# fully injured (the Recovery slot), fewer days than sessions (a note), and the capped gap
# (the other note). Between them these produce every string the module can build.
_ARMS: tuple[dict[str, object], ...] = (
    {"equipment_keys": _FULLY_EQUIPPED},
    {},
    {"open_injury_keys": ("elbow", "fingers")},
    {"open_injury_keys": _ALL_INJURIES},
    {"sessions_per_week": 5, "available_weekdays": 0b0000101},
    {"target_ordinal": ordinal_of(GradeSystemKey.FRENCH, "6a") + 9},
)


@pytest.mark.parametrize("overrides", _ARMS)
def test_no_generated_string_suggests_losing_weight(overrides: dict[str, object]) -> None:
    """⚠️ The hard rule. Low strength-to-weight means *get stronger*, never *get lighter*.

    Not a hypothetical: the plan tree is where a "you'd send this at 3 kg lighter" insight
    would naturally be attached, and a generated string is the one surface no other guard in
    this repo inspects.
    """
    offenders = [text for text in _every_string(_plan(**overrides)) if _WEIGHT_LOSS_RE.search(text)]
    assert not offenders, (
        f"these generated strings read as body-composition advice: {offenders}. See "
        f"CLAUDE.md, 'The app never recommends losing weight' — the answer is always "
        f"'get stronger', and there is no setting behind which the other answer is allowed."
    )


def test_no_refusal_sentence_suggests_losing_weight() -> None:
    """The refusals are generated copy too, and they are what a blocked user actually reads."""
    offenders = [text for text in REFUSAL_MESSAGES.values() if _WEIGHT_LOSS_RE.search(text)]
    assert not offenders, offenders


def test_the_detector_sees_its_own_violation() -> None:
    """The positive control. A matcher nobody has watched fire is not a matcher.

    The second half matters as much as the first: the app's own legitimate vocabulary — two
    equipment rows and the phrase a shortfall builds from them — must NOT match, or the
    detector becomes a false positive somebody silences by deleting a pattern.
    """
    for planted in (
        "Losing weight would improve your ratio.",
        "Aim for your climbing weight before the trip.",
        "Drop a couple of kilos and this grade gets easier.",
        "Your BMI suggests an easier route to 7a.",
        "You will climb harder a little lighter.",
        "Track your body fat alongside your sessions.",
    ):
        assert _WEIGHT_LOSS_RE.search(planted), planted
    for honest in (
        "Weight belt or vest",
        "Free weights",
        "To train finger strength in this phase you need one of these: hangboard, no-hang device.",
        "To train power in this phase you need one of these: free weights, pull-up bar.",
        "16-week sport plan",
        "Add or remove load so the last two seconds are hard.",
    ):
        assert not _WEIGHT_LOSS_RE.search(honest), honest


@pytest.mark.parametrize("overrides", _ARMS)
def test_every_generated_string_fits_the_column_it_is_inserted_into(
    overrides: dict[str, object],
) -> None:
    """`plan.name` and `planned_session.title` are `String(80)`; #11b inserts both.

    The widths are read off the models rather than written down here, so a column that is
    widened or narrowed cannot leave this test asserting the old number.
    """
    name_limit = _width_of(Plan.__table__.c.name)
    title_limit = _width_of(PlannedSession.__table__.c.title)

    plan = _plan(**overrides)
    assert len(plan.name) <= name_limit, plan.name
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                assert len(session.title) <= title_limit, session.title


def _width_of(column: KeyedColumnElement[Any]) -> int:
    """The declared `String(n)` width, read off the model so this file pins no number."""
    kind = column.type
    assert isinstance(kind, String)
    assert kind.length is not None
    return kind.length
