"""⚠️ No goal weight, no target weight, no BMI — anywhere in the schema, ever.

**The rule and its reason are in CLAUDE.md, "The app never recommends losing weight".**
Short version: climbing has a documented disordered-eating problem, this project's
governing principle is user health first, and the app's answer to a low
strength-to-weight ratio is *get stronger*, never *get lighter*. A schema with nowhere to
put a goal weight is a schema in which that feature cannot be built by accident, and the
whole point of testing it is that prose in a markdown file gets "simplified" away by a
later change while a failing test does not.

Two guards, plus the nullability of the one weight column that legitimately exists:

1. **No column, table, index or constraint name may pair a weight word with a goal word,
   and none may contain `bmi`.**
2. **`logged_set.body_weight_kg` — the %BW snapshot — must stay NULLABLE.** A NOT NULL
   there would mean the app had to demand a weight before it would record a performance,
   which is the same coercion by a different route. It is also genuinely absent
   sometimes: there may be no recent weigh-in, and with `show_body_metrics` off nothing
   ever asks for one.

**No database.** This reads `Base.metadata` and the ORM mappers, so it runs in the local
gate as well as CI — which matters, because the mistake it catches is made while writing a
model.

## ⚠️ Limits worth stating, because this file otherwise reads as complete

It is a **name** matcher. It cannot know intent, and the wordlist is the whole of it — so
the honest description is "it catches the spellings somebody thought of", and the list of
those is right here in the file. Specifically:

- **A differently-worded column walks straight through.** `aspirational_kg`,
  `race_mass`, `where_i_want_to_be_kg` — none of these are in `GOAL_WORDS` or
  `FORBIDDEN_PHRASES`, and adding words forever is not a strategy. The wordlist covers the
  vocabulary CLAUDE.md's own prose uses plus the euphemisms common in the sport; treat a
  miss as a wordlist bug and add the name to `FORBIDDEN_COLUMN_NAMES` in the same commit.
- **`jsonb` is invisible.** `plan.generator_input` could carry `{"goal_weight_kg": 62}` and
  nothing here would see it, because there are no column names inside a JSONB document.
- **So is a repurposed column.** Storing a goal weight in `journal_entry.body_weight_kg`,
  or in a `note`, is a write-path decision this file cannot reach.
- **It is a schema guard, not a product guard.** It cannot see a coaching string, a chart
  annotation or a generated recommendation that tells somebody to lose weight — which is
  the *actual* rule. `tests/` has no guard for that and probably cannot have one; it is a
  review obligation on PR #11, and the schema guard exists to make the feature hard to
  build, not impossible.

## Every guard here carries a positive control

Per CLAUDE.md: a detector that cannot see its own violation is worse than none. The
`test_detector_*` cases below build throwaway tables that DO violate the rules and assert
the detectors flag them, and assert the near-misses (`body_weight_kg`, `target_load_kg`)
are *not* flagged — an over-eager matcher that flagged the legitimate columns would have
to be loosened, and loosening is how a guard quietly stops guarding.
"""

import re
from collections.abc import Iterable

import pytest
from sqlalchemy import Column, Date, Integer, MetaData, Numeric, String, Table

from server.models import Base, LoggedSet

# ⚠️ **The wordlist is the whole guard.** The AST/metadata harness was right from the
# start and the vocabulary was the defect: the first version caught exactly the four
# strings its own positive control fed it, and missed `body_mass_index`,
# `climbing_weight_kg`, `target_body_fat_pct`, `ideal_mass_kg`, `target_mass_kg`,
# `goal_kg`, `desired_mass` and `bodymassindex` — several of which CLAUDE.md's own prose
# spells out by name. Every one of those is in the positive control below now. If you add
# a word here, add a name to that control in the same commit.
#
# Names are matched against a STRIPPED form (lowercase, separators removed), so
# `body_mass_index`, `bodyMassIndex` and `bodymassindex` are one string to this file.

# Forbidden outright, whatever else the name says. BMI and body-fat/composition metrics
# are the body-composition numbers CLAUDE.md's reasoning covers directly ("nor that a
# body-composition change would improve performance") — there is no legitimate column in
# this product with these in its name. `climbingweight` and `racingweight` are here
# because CLAUDE.md names "a 'climbing weight'" explicitly and no pairing rule would see
# it: "climbing" is not an aspiration word anywhere else in the schema.
# Multi-word, so a stripped-form substring match is safe.
FORBIDDEN_PHRASES = (
    "bodymassindex",
    "bodymassidx",
    "bodyfat",
    "fatfree",
    "leanmass",
    "bodycomposition",
    "skinfold",
    "waistcircumference",
    # The euphemism family. "Climbing weight", "competition weight", "send weight",
    # "performance weight" and "racing weight" are all the same sentence with the goal word
    # removed, so no pairing rule can see them — which is exactly why they are the phrasing
    # that survives a review. CLAUDE.md names "a 'climbing weight'" explicitly.
    "climbingweight",
    "racingweight",
    "compweight",
    "competitionweight",
    "sendweight",
    "performanceweight",
)

# ⚠️ `bmi` is matched as a whole TOKEN, never as a substring of the stripped form.
# "submitted" contains `bmi` (su-BMI-tted), so a substring match flags
# `activity.submitted_at` — a false positive on a real column, which is precisely the kind
# that gets a guard loosened or deleted outright. It is in PERMITTED_COLUMN_NAMES below and
# must stay there.
#
# **Tokenising splits camelCase as well as separators.** It did not, for one round, while
# the docstring claimed names were matched on a stripped form — so `bmiValue` and `bmiScore`
# passed while `bmi_value` was caught. A Python attribute is as likely to be camelCase as
# not once it reaches the TypeScript side of a payload.
FORBIDDEN_TOKENS = frozenset({"bmi"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_SEPARATORS = re.compile(r"[^a-z0-9]+")

# Forbidden in COMBINATION: a bodyweight word plus an aspiration word.
WEIGHT_WORDS = ("weight", "mass", "kg", "lbs", "wt", "bw")

# Note the second group: a **bound** is a goal wearing different clothes. `max_weight_kg`
# reads as a validation limit and functions as a target, and `cut_weight` / `dream_weight`
# are how it gets said out loud. All of `min`/`max`/`limit`/`ceiling`/`cut`/`dream` were
# missing for a round.
GOAL_WORDS = (
    "goal",
    "target",
    "ideal",
    "desire",
    "aim",
    "objective",
    "optimal",
    "recommended",
    "min",
    "max",
    "limit",
    "ceiling",
    "cut",
    "dream",
)

# ⚠️ The one exemption, and it is scoped to the ONLY collision it was written for.
#
# `kg` had to join WEIGHT_WORDS to catch `goal_kg`, and that immediately collides with
# `prescribed_set.target_load_kg` — the weight on a BELT, not a body. So a qualifier from
# this list stands the pairing rule down **only when the matched weight word is a generic
# unit** (`kg`, `lbs`).
#
# For one round it was applied unconditionally, and before the pairing check — which made
# it a blanket bypass: `goal_weight_load_kg`, `target_bodyweight_vest`, `target_mass_added`
# and `goal_body_mass_belt` all passed, because `weight` and `mass` are not ambiguous and
# should never have been exemptible. All four are in the positive control now. If a real
# column ever needs adding here, prefer renaming the column.
EXTERNAL_LOAD_WORDS = ("load", "added", "plate", "belt", "vest", "dumbbell", "barbell")

# Weight words that name a UNIT rather than a body. Only these are exemptible.
AMBIGUOUS_UNIT_WORDS = ("kg", "lbs", "wt")

# The nullability arm uses a deliberately NARROWER vocabulary than the naming arm: it must
# fire on a bodyweight column made NOT NULL and stay silent about `actual_load_kg`, so it
# looks for an actual bodyweight rather than for any mass-like word.
BODYWEIGHT_PHRASES = ("bodyweight", "bodymass")

_SEPARATORS = re.compile(r"[^a-z0-9]+")

# The %BW snapshot. Named here so a rename cannot make the nullability guard vacuous —
# `test_the_snapshot_column_still_exists` fails first if this stops being true.
SNAPSHOT_TABLE = "logged_set"
SNAPSHOT_COLUMN = "body_weight_kg"


def _strip(name: str) -> str:
    """Lowercase, separators removed: `body_mass_index` and `BodyMassIndex` become one."""
    return _SEPARATORS.sub("", name.lower())


def _tokens(name: str) -> set[str]:
    """Lowercase tokens, split on separators AND on camelCase boundaries.

    `bmiValue` -> {'bmi', 'value'}; `body_mass_index` -> {'body', 'mass', 'index'};
    `submitted_at` -> {'submitted', 'at'} — which is what keeps `bmi` out of it.
    """
    return set(_TOKEN_SEPARATORS.split(_CAMEL_BOUNDARY.sub("_", name).lower()))


def _offending_names(names: Iterable[str]) -> list[str]:
    """Every name forbidden outright, or pairing a bodyweight word with an aspiration."""
    offences = []
    for name in names:
        stripped = _strip(name)
        forbidden_token = _tokens(name) & FORBIDDEN_TOKENS
        if forbidden_token:
            offences.append(f"{name} (forbidden token: {sorted(forbidden_token)})")
            continue
        phrase = next((p for p in FORBIDDEN_PHRASES if p in stripped), None)
        if phrase is not None:
            offences.append(f"{name} (forbidden: {phrase!r})")
            continue
        matched_weight = [word for word in WEIGHT_WORDS if word in stripped]
        if not matched_weight or not any(word in stripped for word in GOAL_WORDS):
            continue
        # The exemption applies ONLY if every weight word matched was a generic unit.
        # `goal_weight_load_kg` matches `weight` as well as `kg`, so it is not exempt.
        unambiguous = [word for word in matched_weight if word not in AMBIGUOUS_UNIT_WORDS]
        if not unambiguous and any(word in stripped for word in EXTERNAL_LOAD_WORDS):
            continue
        offences.append(f"{name} (weight + goal: {matched_weight})")
    return offences


def _every_name(metadata: MetaData) -> list[str]:
    """Table, column, constraint and index names — everything a developer gets to name.

    Constraints and indexes are included because a `CHECK (weight <= goal_weight)` would
    need a name too, and the column it referenced might live somewhere this walk of
    `metadata` had already passed.
    """
    names = []
    for table in metadata.sorted_tables:
        names.append(table.name)
        names.extend(f"{table.name}.{column.name}" for column in table.columns)
        # `isinstance(..., str)` rather than `is not None`: an unnamed constraint's name
        # is SQLAlchemy's `_NoneName.NONE_NAME` sentinel, not None, so the obvious check
        # would let it through and then compare an enum member against substrings.
        names.extend(c.name for c in table.constraints if isinstance(c.name, str))
        names.extend(index.name for index in table.indexes if isinstance(index.name, str))
    return names


def _mapped_attribute_names() -> list[str]:
    """Every ORM attribute name, which is a SEPARATE namespace from the column names.

    `goal_weight_kg: Mapped[Decimal] = mapped_column("gw")` gives the column the name `gw`
    and the attribute the name `goal_weight_kg` — so a metadata-only walk sees nothing,
    while every line of application code, every `select()` and every Pydantic field built
    from the model says `goal_weight_kg`. The attribute is the name that would actually
    spread, so it is checked too rather than caveated.
    """
    names: list[str] = []
    for mapper in Base.registry.mappers:
        names.extend(f"{mapper.class_.__name__}.{attr.key}" for attr in mapper.attrs)
    return names


def _non_nullable_weight_snapshots(metadata: MetaData) -> list[str]:
    """Any bodyweight column declared NOT NULL. There must never be one."""
    offences = []
    for table in metadata.sorted_tables:
        for column in table.columns:
            stripped = _strip(column.name)
            if not any(phrase in stripped for phrase in BODYWEIGHT_PHRASES):
                continue
            if not column.nullable:
                offences.append(f"{table.name}.{column.name}")
    return offences


def test_the_schema_has_no_goal_weight_target_weight_or_bmi() -> None:
    names = _every_name(Base.metadata) + _mapped_attribute_names()
    # Non-vacuity: an empty metadata must not read as compliance.
    assert len(names) > 100, f"only {len(names)} names found — is Base.metadata populated?"
    assert not _offending_names(names), (
        "the schema has grown a weight-goal name (column OR ORM attribute):\n  "
        + "\n  ".join(_offending_names(names))
        + "\n\nThe app never recommends losing weight — low strength-to-weight means "
        "'get stronger', never 'get lighter'. See CLAUDE.md, 'The app never recommends "
        "losing weight'. If a feature seems to need this column, it is the feature that "
        "is wrong."
    )


def test_the_snapshot_column_still_exists() -> None:
    """Non-vacuity for the nullability guard below: the column it guards must be real."""
    assert SNAPSHOT_TABLE in Base.metadata.tables
    assert SNAPSHOT_COLUMN in Base.metadata.tables[SNAPSHOT_TABLE].columns
    assert LoggedSet.body_weight_kg.key == SNAPSHOT_COLUMN


def test_every_bodyweight_column_is_nullable() -> None:
    assert not _non_nullable_weight_snapshots(Base.metadata), (
        "a bodyweight column is NOT NULL:\n  "
        + "\n  ".join(_non_nullable_weight_snapshots(Base.metadata))
        + "\n\nThat would make the app demand a weight before it would record a "
        "performance. The %BW snapshot is optional by design: there may be no recent "
        "weigh-in, and with `show_body_metrics` off nothing ever asks for one."
    )


# ⚠️ Every one of these was a MISS before 2026-08-21. The first eight are the reviewer's
# list; the last three were caught by the original wordlist and must keep being caught.
FORBIDDEN_COLUMN_NAMES = (
    # Round 1's original four — must keep being caught.
    "goal_weight_kg",
    "target_weight",
    "bmi",
    "desired_mass",
    # Round 2's misses.
    "body_mass_index",
    "bodymassindex",
    "climbing_weight_kg",
    "target_body_fat_pct",
    "ideal_mass_kg",
    "target_mass_kg",
    "goal_kg",
    # Round 3: the EXTERNAL_LOAD_WORDS blanket bypass. `weight` and `mass` are never
    # ambiguous, so no external-load qualifier may exempt them.
    "goal_weight_load_kg",
    "target_bodyweight_vest",
    "target_mass_added",
    "goal_body_mass_belt",
    # Round 3: whole categories the wordlist had no word for.
    "lean_mass_kg",
    "fat_free_mass",
    "skinfold_mm",
    "waist_circumference_cm",
    "body_mass_idx",
    "comp_weight",
    "competition_weight",
    "send_weight",
    "performance_weight",
    # Round 3: bounds are goals.
    "min_weight_kg",
    "max_weight_kg",
    "weight_ceiling_kg",
    "cut_weight_kg",
    # Round 3: `wt` was not a weight word.
    "wt_goal",
    # Round 3: camelCase escaped the token split.
    "bmiValue",
    "bmiScore",
)

# Names that must NEVER be flagged. A guard that fails on legitimate columns gets
# loosened, and loosening is how it stops guarding — so specificity is tested as hard as
# sensitivity. `target_load_kg` is the pointed one: it pairs an aspiration word with `kg`
# and is exempted only by `EXTERNAL_LOAD_WORDS`.
PERMITTED_COLUMN_NAMES = (
    # ⚠️ `submitted_at` contains `bmi` (su-BMI-tted). This is the false positive that a
    # stripped-substring match for `bmi` produces, and the reason that one word is
    # token-scoped. It has caught the mistake twice; do not remove it.
    "activity.submitted_at",
    # `target_load_kg` is the pointed one: an aspiration word plus `kg`, exempt only
    # because `load` marks it as external weight on a belt.
    "logged_set.body_weight_kg",
    "journal_entry.body_weight_kg",
    "logged_set.body_weight_as_of",
    "prescribed_set.target_load_kg",
    "prescribed_set.target_reps",
    "prescribed_set.target_grade_id",
    "logged_set.actual_load_kg",
    "user_profile.target_grade_id",
    "ascent.attempts",
    "microcycle.is_deload",
)


def _violating_metadata() -> MetaData:
    """A throwaway schema containing every violation, for the positive controls.

    Its own `MetaData`, so nothing here can leak into `Base.metadata` and nothing here
    needs the naming convention.
    """
    metadata = MetaData()
    Table(
        "bad_profile",
        metadata,
        Column("id", Integer, primary_key=True),
        *(Column(name, Numeric(6, 2)) for name in FORBIDDEN_COLUMN_NAMES),
        # NOT NULL, which arm 2 must catch independently of the naming arm.
        Column("body_weight_kg", Numeric(5, 2), nullable=False),
    )
    return metadata


@pytest.mark.parametrize("name", FORBIDDEN_COLUMN_NAMES)
def test_detector_sees_every_forbidden_spelling(name: str) -> None:
    """Positive control for arm 1, one case per spelling so a miss names itself."""
    offences = " ".join(_offending_names([f"bad_profile.{name}"]))
    assert name in offences, f"{name!r} slipped past the wordlist"


def test_detector_sees_all_of_them_together_in_real_metadata() -> None:
    """And through the metadata walk, not just the string matcher."""
    offences = " ".join(_offending_names(_every_name(_violating_metadata())))
    for name in FORBIDDEN_COLUMN_NAMES:
        assert name in offences


@pytest.mark.parametrize("name", PERMITTED_COLUMN_NAMES)
def test_detector_does_not_flag_a_legitimate_column(name: str) -> None:
    assert not _offending_names([name]), f"{name!r} is legitimate and must not be flagged"


def test_detector_sees_a_not_null_bodyweight_column() -> None:
    """Positive control for arm 2."""
    offences = _non_nullable_weight_snapshots(_violating_metadata())
    assert offences == ["bad_profile.body_weight_kg"]


def test_detector_ignores_a_nullable_bodyweight_column() -> None:
    """And does not fire on the shape the real schema uses."""
    metadata = MetaData()
    Table(
        "fine",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("body_weight_kg", Numeric(5, 2), nullable=True),
        Column("body_weight_as_of", Date, nullable=True),
        Column("note", String(10), nullable=True),
    )
    assert not _non_nullable_weight_snapshots(metadata)
