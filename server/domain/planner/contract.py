"""The generator's contract with its caller: the version, the input, and the refusals.

Separate from `__init__.py` on purpose. `schedule.py` has to raise `no_available_days`, so
if these lived in the package `__init__` — which re-exports `schedule` — the import would
be circular. `__init__.py` is therefore a pure re-export facade and every name it publishes
is defined in a sibling module. The plan's "these live in `__init__.py`" is satisfied by the
re-export; moving the definitions there would break the package on import.

## `RefusalReason` is closed, and each reason owns exactly one sentence

`REFUSAL_MESSAGES` is the only place a refusal is worded. `CannotPlanError` takes the
reason alone and looks the sentence up, rather than taking `(reason, message)`: two call
sites raising the same reason with different wording is precisely what "one fixed sentence
each" forbids, and the API test and the web copy both quote these verbatim.

## What a refusal is, and what it is not

A refusal is a **stored-state** problem the user can fix by answering something — never a
lack of equipment. A climber with no gear gets a complete plan with the shortfall named per
block (Kilian, 2026-08-24); that is not on this list and must never be added to it.

## `sessions_per_week` and `available_weekdays` are NOT nullable here

`user_profile` allows NULL for both, and NULL must never be given a default — but an
"unanswered" value has no representation in a *plannable* input, so the two `_unanswered`
reasons are raised where the profile is read (`server/plans/routes.py`), not here. The two
reasons live in this enum anyway, because the HTTP mapping is one `except CannotPlanError`
and splitting the vocabulary across two modules would be worse than the asymmetry.
"""

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Final

from server.domain.grades import GRADES, Discipline, system
from server.domain.vocabulary import CLIMBING_ASPECTS, EQUIPMENT, INJURY_AREAS

# The version describes the ALGORITHM, so it lives in the domain rather than beside the
# endpoint, and it bumps on any behaviour change — the constants in this package included.
# `server/models.py::Plan` promises version + input reproduces the tree, and a constant
# tweaked without a bump makes that promise false silently.
GENERATOR_VERSION: Final = "3.0.0"

MAX_WEEKDAY_MASK: Final = 0b111_1111
MIN_SESSIONS_PER_WEEK: Final = 1
MAX_SESSIONS_PER_WEEK: Final = 7

_ASPECT_KEYS: Final[frozenset[str]] = frozenset(spec.key for spec in CLIMBING_ASPECTS)
_EQUIPMENT_KEYS: Final[frozenset[str]] = frozenset(spec.key for spec in EQUIPMENT)
_INJURY_KEYS: Final[frozenset[str]] = frozenset(spec.key for spec in INJURY_AREAS)

# Which ordinals belong to which discipline, built from the ladder rather than from the
# 1000-band arithmetic: `_BAND_BASE` is private to `server/domain/grades.py` and the band
# width is an implementation detail of that module, not a contract with this one.
_ORDINALS_BY_DISCIPLINE: Final[Mapping[Discipline, frozenset[int]]] = MappingProxyType(
    {
        discipline: frozenset(
            grade.ordinal for grade in GRADES if system(grade.system).discipline is discipline
        )
        for discipline in Discipline
    }
)
_ALL_ORDINALS: Final[frozenset[int]] = frozenset(grade.ordinal for grade in GRADES)


class RefusalReason(enum.StrEnum):
    """Why a plan cannot be built. Closed, and mapped to HTTP at a single call site."""

    NO_TARGET_GRADE = "no_target_grade"
    NO_CURRENT_GRADE = "no_current_grade"
    SESSIONS_PER_WEEK_UNANSWERED = "sessions_per_week_unanswered"
    AVAILABLE_WEEKDAYS_UNANSWERED = "available_weekdays_unanswered"
    NO_AVAILABLE_DAYS = "no_available_days"
    CROSS_DISCIPLINE_GRADES = "cross_discipline_grades"


# One sentence per reason: what is missing, then the ask. Reworked on Kilian's dev-server
# sign-off (2026-08-24) — naming only the missing answer left the reader with nothing to do, so
# each sentence now sends them to finish their profile setup. Frozen. The `/plan` screen copies
# five of them verbatim and `tests/test_planner_refusal_copy.py` fails until both copies move
# together.
REFUSAL_MESSAGES: Final[Mapping[RefusalReason, str]] = MappingProxyType(
    {
        RefusalReason.NO_TARGET_GRADE: (
            "Your plan is built around a target grade. Finish setting up your profile and "
            "we'll build it."
        ),
        RefusalReason.NO_CURRENT_GRADE: (
            "Your plan needs to know what you climb now as well as what you're aiming at. "
            "Finish setting up your profile and we'll build it."
        ),
        RefusalReason.SESSIONS_PER_WEEK_UNANSWERED: (
            "Your plan needs to know how often you can train. Finish setting up your profile "
            "and we'll build it."
        ),
        RefusalReason.AVAILABLE_WEEKDAYS_UNANSWERED: (
            "Your plan needs to know which days you can train. Finish setting up your profile "
            "and we'll build it."
        ),
        RefusalReason.NO_AVAILABLE_DAYS: (
            "You haven't marked any day as available, so there's nowhere to put a session. "
            "Tick at least one day in your profile and we'll build it."
        ),
        RefusalReason.CROSS_DISCIPLINE_GRADES: (
            "Your current and target grades are on different ladders, and boulder and sport "
            "grades can't be compared. Pick both for the same discipline in your profile and "
            "we'll build it."
        ),
    }
)


class CannotPlanError(Exception):
    """A well-formed request against stored state no plan can be built from.

    `reason` is for the caller to branch on, `message` is for the user. Never carries the
    input that caused it: CLAUDE.md's input-minimisation rules forbid echoing a request
    back in a 4xx, and this exception is rendered straight into one.
    """

    def __init__(self, reason: RefusalReason) -> None:
        self.reason = reason
        self.message = REFUSAL_MESSAGES[reason]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class PlannerInput:
    """Everything `generate()` reads. No ids the domain would have to resolve, no clock.

    `available_weekdays` is a 7-bit mask with **Monday = bit 0**, matching
    `user_profile.available_weekdays` and `planned_session.weekday`. `equipment_keys` is an
    AND set and `()` is legal — a climber with no gear is the common case, not an edge one.

    `strength_aspect_key` / `weakness_aspect_key` are optional because the columns behind
    them are nullable and the refusal list has no entry for either: an unanswered headline
    aspect costs the weakness bias, not the plan.

    `start_date` is **already the Monday the plan starts on**. Normalising it is the
    caller's job because the caller knows the timezone; validated here rather than trusted,
    because an off-by-one weekday would put every session in the plan on the wrong day.
    """

    discipline: Discipline
    current_ordinal: int
    target_ordinal: int
    sessions_per_week: int
    available_weekdays: int
    strength_aspect_key: str | None
    weakness_aspect_key: str | None
    open_injury_keys: tuple[str, ...]
    equipment_keys: tuple[str, ...]
    start_date: date

    def __post_init__(self) -> None:
        if not MIN_SESSIONS_PER_WEEK <= self.sessions_per_week <= MAX_SESSIONS_PER_WEEK:
            raise ValueError(
                f"sessions_per_week must be {MIN_SESSIONS_PER_WEEK}-{MAX_SESSIONS_PER_WEEK} "
                f"(ck_user_profile_sessions_per_week_in_range), got {self.sessions_per_week}. "
                f"NULL is a refusal, not a value — see RefusalReason."
            )
        if not 0 <= self.available_weekdays <= MAX_WEEKDAY_MASK:
            raise ValueError(
                f"available_weekdays is a 7-bit mask, Monday = bit 0 "
                f"(ck_user_profile_available_weekdays_is_7_bits), got "
                f"{self.available_weekdays}."
            )
        if self.start_date.weekday() != 0:
            raise ValueError(
                f"start_date must already be a Monday; {self.start_date} is a "
                f"{self.start_date.strftime('%A')}. The caller normalises it — the domain "
                f"has no clock and no timezone, so it cannot do it here."
            )
        for key in (self.strength_aspect_key, self.weakness_aspect_key):
            if key is not None and key not in _ASPECT_KEYS:
                raise ValueError(f"{key!r} is not a climbing aspect key.")
        if (
            self.strength_aspect_key is not None
            and self.strength_aspect_key == self.weakness_aspect_key
        ):
            raise ValueError(
                "strength and weakness cannot be the same aspect "
                "(ck_user_profile_strength_and_weakness_differ)."
            )
        _require_sorted_subset(self.open_injury_keys, _INJURY_KEYS, "injury area")
        _require_sorted_subset(self.equipment_keys, _EQUIPMENT_KEYS, "equipment")
        self._check_ordinals()

    @property
    def grade_gap(self) -> int:
        """Rungs between here and the target. Meaningful only within one discipline's band."""
        return self.target_ordinal - self.current_ordinal

    def _check_ordinals(self) -> None:
        """Refuse a cross-band pair rather than trust it, per the plan's refusal table.

        `server/domain/grades.py` puts the two disciplines in disjoint bands so a mistake
        is a nonsense gap of ~1000 instead of a plausible one. That only helps if somebody
        looks, so this looks: a grade off the ladder entirely is a bug in the caller's
        resolution and raises, while a grade on the *wrong* ladder is a stored-state
        problem the user can fix and refuses.
        """
        for ordinal in (self.current_ordinal, self.target_ordinal):
            if ordinal not in _ALL_ORDINALS:
                raise ValueError(
                    f"ordinal {ordinal} is on no grade ladder. Ordinals reach the domain "
                    f"from a seeded `grade` row, so this is a resolution bug, not user state."
                )
        band = _ORDINALS_BY_DISCIPLINE[self.discipline]
        if self.current_ordinal not in band or self.target_ordinal not in band:
            raise CannotPlanError(RefusalReason.CROSS_DISCIPLINE_GRADES)


def _require_sorted_subset(keys: tuple[str, ...], valid: frozenset[str], vocabulary: str) -> None:
    """Sorted and duplicate-free, because the tuple order reaches the generator's output.

    Selection rotates on an index, `generator_input` is hashed into the reproducibility
    promise, and a set is not iteration-order stable across processes — so the boundary is
    where a set becomes a sorted tuple, and this is the boundary.
    """
    for key in keys:
        if key not in valid:
            raise ValueError(
                f"{key!r} is not a {vocabulary} key. The authority is server/domain/vocabulary.py."
            )
    if list(keys) != sorted(set(keys)):
        raise ValueError(
            f"{vocabulary} keys must be sorted and unique, got {keys!r}. The generator is "
            f"reproducible, and an unordered input makes the same profile hash two ways."
        )
