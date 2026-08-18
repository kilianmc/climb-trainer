"""The grade ladder — reference data and the ordinal maths, as pure Python.

**Never store a grade as a display string alone.** This is the single most expensive
thing to retrofit in the whole schema (see CLAUDE.md), so it is settled here, in
PR #2, before anything can persist a grade.

## How the ladder works

A `grade` is `(system, label, ordinal)`. The **ordinal is a shared integer ladder**:
every system that measures the same thing places its labels on the *same* rungs, so
`V5` and `6C` are the same integer and `target_ordinal - current_ordinal` is a
meaningful "grade gap" regardless of which scale the user prefers. Comparison,
sorting, pyramids and the plan generator's gap maths all work on the ordinal; the
label is display only.

## One ladder per discipline, in disjoint numeric bands

Boulder ordinals live in the 1000-band, rope ordinals in the 2000-band. **Boulder
and rope grades are deliberately NOT comparable**: bouldering-to-sport conversion is
genuinely contested and route length/style dominate it, so encoding an equivalence
would be inventing data — exactly the kind of thing that is expensive to unpick
later. The disjoint bands make a cross-discipline mistake loud (a nonsense gap of
~1000) instead of quietly plausible, and `convert()` refuses it outright.

Within a band, rungs are contiguous, so arithmetic on ordinals is still just `+`/`-`.

## Coverage gaps are real and expected

Scales do not have the same number of rungs. Font distinguishes `6B+` where the
V-scale does not; YDS distinguishes `5.11c` where French does not. Such a rung
simply has no label in that system — it is a hole in the mapping, not an error in
the ladder — and `convert()` raises `NoEquivalentGradeError` rather than rounding
silently to a neighbour.

## Labels are matched EXACTLY, and that is load-bearing

`7A` is Font (boulder); `7a` is French (rope). Case is the only thing separating
them, so no case-folding, no whitespace stripping, no "helpful" normalisation.
Grades reach the API as a `grade_id` resolved against the seeded table anyway (never
as free-typed text — see the input-minimisation rules in CLAUDE.md), so leniency
here would buy nothing and cost the Font/French distinction.

The equivalences below follow the commonly published conversion tables. They are a
convention, not a measurement; when in doubt the *ordinal* is the source of truth
and the cross-scale label is a convenience.
"""

import enum
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


class Discipline(enum.StrEnum):
    """Closed vocabulary, mirrored by the native Postgres `discipline` enum.

    `SPORT` covers rope grades generally (French, YDS) — the user-facing choice is
    "boulder or sport", which is why it is not called `ROUTE`.
    """

    BOULDER = "boulder"
    SPORT = "sport"


class GradeSystemKey(enum.StrEnum):
    """Stable machine keys. These are persisted in `grade_system.key`, so they are
    part of the data contract — renaming one is a migration, not a rename."""

    FONT = "font"
    V_SCALE = "v_scale"
    FRENCH = "french"
    YDS = "yds"


class UnknownGradeError(ValueError):
    """A label or ordinal that is not on the seeded ladder."""


class NoEquivalentGradeError(LookupError):
    """The rung exists, but the target system has no label on it (e.g. YDS 5.11c)."""


class CrossDisciplineError(ValueError):
    """Refused: boulder and rope grades are not comparable. See the module docstring."""


@dataclass(frozen=True, slots=True)
class GradeSystemSpec:
    key: GradeSystemKey
    name: str
    discipline: Discipline


@dataclass(frozen=True, slots=True)
class GradeSpec:
    system: GradeSystemKey
    label: str
    ordinal: int


GRADE_SYSTEMS: Final[tuple[GradeSystemSpec, ...]] = (
    GradeSystemSpec(GradeSystemKey.FONT, "Fontainebleau", Discipline.BOULDER),
    GradeSystemSpec(GradeSystemKey.V_SCALE, "V-scale", Discipline.BOULDER),
    GradeSystemSpec(GradeSystemKey.FRENCH, "French", Discipline.SPORT),
    GradeSystemSpec(GradeSystemKey.YDS, "Yosemite Decimal System", Discipline.SPORT),
)

# The first ordinal of each discipline's band. Bands are 1000 apart so that a
# cross-discipline subtraction produces an obviously absurd number.
_BAND_BASE: Final[MappingProxyType[Discipline, int]] = MappingProxyType(
    {Discipline.BOULDER: 1000, Discipline.SPORT: 2000}
)

# One tuple per rung, in ascending difficulty. `None` = that system has no label on
# this rung. Order in the file IS the ladder; do not sort or reorder these.
_BOULDER_RUNGS: Final[tuple[tuple[str | None, str | None], ...]] = (
    # (font, v_scale)
    ("3", "VB"),
    ("4", "V0"),
    ("4+", "V1"),
    ("5", "V2"),
    ("5+", None),
    ("6A", "V3"),
    ("6A+", None),
    ("6B", "V4"),
    ("6B+", None),
    ("6C", "V5"),
    ("6C+", None),
    ("7A", "V6"),
    ("7A+", "V7"),
    ("7B", "V8"),
    ("7B+", None),
    ("7C", "V9"),
    ("7C+", "V10"),
    ("8A", "V11"),
    ("8A+", "V12"),
    ("8B", "V13"),
    ("8B+", "V14"),
    ("8C", "V15"),
    ("8C+", "V16"),
    ("9A", "V17"),
)

_SPORT_RUNGS: Final[tuple[tuple[str | None, str | None], ...]] = (
    # (french, yds)
    ("3", "5.4"),
    ("3+", "5.5"),
    ("4", "5.6"),
    ("4+", "5.7"),
    ("5", "5.8"),
    ("5+", "5.9"),
    ("6a", "5.10a"),
    ("6a+", "5.10b"),
    ("6b", "5.10c"),
    ("6b+", "5.10d"),
    ("6c", "5.11a"),
    ("6c+", "5.11b"),
    (None, "5.11c"),  # French does not split this rung.
    ("7a", "5.11d"),
    ("7a+", "5.12a"),
    ("7b", "5.12b"),
    ("7b+", "5.12c"),
    ("7c", "5.12d"),
    ("7c+", "5.13a"),
    ("8a", "5.13b"),
    ("8a+", "5.13c"),
    ("8b", "5.13d"),
    ("8b+", "5.14a"),
    ("8c", "5.14b"),
    ("8c+", "5.14c"),
    ("9a", "5.14d"),
    ("9a+", "5.15a"),
    ("9b", "5.15b"),
    ("9b+", "5.15c"),
    ("9c", "5.15d"),
)


@dataclass(frozen=True, slots=True)
class _Ladder:
    discipline: Discipline
    systems: tuple[GradeSystemKey, ...]
    rungs: tuple[tuple[str | None, ...], ...]


_LADDERS: Final[tuple[_Ladder, ...]] = (
    _Ladder(Discipline.BOULDER, (GradeSystemKey.FONT, GradeSystemKey.V_SCALE), _BOULDER_RUNGS),
    _Ladder(Discipline.SPORT, (GradeSystemKey.FRENCH, GradeSystemKey.YDS), _SPORT_RUNGS),
)


def _build_grades() -> tuple[GradeSpec, ...]:
    grades: list[GradeSpec] = []
    for ladder in _LADDERS:
        base = _BAND_BASE[ladder.discipline]
        for step, rung in enumerate(ladder.rungs):
            ordinal = base + step
            for key, label in zip(ladder.systems, rung, strict=True):
                if label is not None:
                    grades.append(GradeSpec(key, label, ordinal))
    return tuple(grades)


GRADES: Final[tuple[GradeSpec, ...]] = _build_grades()

_SYSTEMS_BY_KEY: Final[MappingProxyType[GradeSystemKey, GradeSystemSpec]] = MappingProxyType(
    {spec.key: spec for spec in GRADE_SYSTEMS}
)
_ORDINAL_BY_LABEL: Final[MappingProxyType[GradeSystemKey, MappingProxyType[str, int]]] = (
    MappingProxyType(
        {
            spec.key: MappingProxyType({g.label: g.ordinal for g in GRADES if g.system is spec.key})
            for spec in GRADE_SYSTEMS
        }
    )
)
_LABEL_BY_ORDINAL: Final[MappingProxyType[GradeSystemKey, MappingProxyType[int, str]]] = (
    MappingProxyType(
        {
            spec.key: MappingProxyType({g.ordinal: g.label for g in GRADES if g.system is spec.key})
            for spec in GRADE_SYSTEMS
        }
    )
)


def system(key: GradeSystemKey) -> GradeSystemSpec:
    return _SYSTEMS_BY_KEY[key]


def systems_for(discipline: Discipline) -> tuple[GradeSystemSpec, ...]:
    return tuple(s for s in GRADE_SYSTEMS if s.discipline is discipline)


def grades_for(key: GradeSystemKey) -> tuple[GradeSpec, ...]:
    """Every grade in one system, ascending. Ordering is the ladder's, not the label's."""
    return tuple(g for g in GRADES if g.system is key)


def ordinal_of(key: GradeSystemKey, label: str) -> int:
    """Ladder position of `label` in `key`. Exact match — see the module docstring."""
    try:
        return _ORDINAL_BY_LABEL[key][label]
    except KeyError as exc:
        raise UnknownGradeError(f"{label!r} is not a {key.value} grade") from exc


def label_at(key: GradeSystemKey, ordinal: int) -> str:
    """The `key` label on rung `ordinal`.

    Raises `NoEquivalentGradeError` when the rung is on this system's ladder but
    unlabelled in it, and `UnknownGradeError` when the rung is off the ladder
    entirely — the caller usually wants to treat those differently.
    """
    labels = _LABEL_BY_ORDINAL[key]
    try:
        return labels[ordinal]
    except KeyError:
        pass
    discipline = _SYSTEMS_BY_KEY[key].discipline
    base = _BAND_BASE[discipline]
    if base <= ordinal < base + len(_rungs_for(discipline)):
        raise NoEquivalentGradeError(f"{key.value} has no label on ordinal {ordinal}")
    raise UnknownGradeError(f"ordinal {ordinal} is not on the {discipline.value} ladder")


def convert(label: str, *, from_system: GradeSystemKey, to_system: GradeSystemKey) -> str:
    """Translate a label between two systems of the SAME discipline.

    Refuses boulder <-> rope with `CrossDisciplineError`, because that conversion is
    not a fact we have. See the module docstring.
    """
    source = _SYSTEMS_BY_KEY[from_system]
    target = _SYSTEMS_BY_KEY[to_system]
    if source.discipline is not target.discipline:
        raise CrossDisciplineError(
            f"refusing to convert {source.discipline.value} {from_system.value} to "
            f"{target.discipline.value} {to_system.value}: not comparable"
        )
    return label_at(to_system, ordinal_of(from_system, label))


def _rungs_for(discipline: Discipline) -> tuple[tuple[str | None, ...], ...]:
    for ladder in _LADDERS:
        if ladder.discipline is discipline:
            return ladder.rungs
    raise UnknownGradeError(f"no ladder for discipline {discipline!r}")  # pragma: no cover
