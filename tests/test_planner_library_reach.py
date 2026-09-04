"""⚠️ GUARD. Every exercise in the library is reachable by some profile, and one plan is varied.

DB-free. Nothing in the gate could see an exercise no plan can prescribe: 762 tests passed while
six of the then-85 were structurally unreachable — three wall `core_tension` drills that fell
between the climbing pass's on-the-wall filter and the supplementary pass's off-the-wall one,
and three off-the-wall `power` exercises whose aspect the climbing pass had already spent. This
is the "compute the invariant from the data" shape (PR #63: 20 exercises in the wrong tuple,
ruff, mypy and 266 tests blind), so reach is MEASURED off `generate()` rather than reasoned.

`_ACCEPTABLY_UNREACHABLE` is the register, asserted in BOTH directions on the idiom of
`DELIBERATELY_UNPRESCRIBED` and `CELLS_WITH_NO_GEARLESS_OPTION`: an orphan not listed is a
defect, and a listed key that has become reachable is a stale exemption. It is EMPTY today, and
that is a measurement rather than an aspiration — `origin/dev` carried three.
"""

from collections import Counter
from datetime import date

from server.domain.exercises import EXERCISES
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner.blueprint import PlanBlueprint
from server.domain.planner.contract import PlannerInput
from server.domain.planner.generate import generate
from server.domain.vocabulary import EQUIPMENT

_MONDAY = date(2026, 8, 24)
_ALL_EQUIPMENT = tuple(sorted(spec.key for spec in EQUIPMENT))

# key -> why no profile can ever be prescribed it, and why that is acceptable. Add a row only
# with a reason a reviewer can check; a row added to make this test pass is the failure it
# exists to catch. `origin/dev` before PR A had three (`density_hangs`, `onsight_volume_on_rope`,
# `system_board_repeats`), all of which are reachable now.
# ⚠️ "No profile has the equipment" is never one of those reasons: `_PROFILES` hands every plan
# the FULL vocabulary, so an orphan here is always a rotation or a sampling gap, never a purchase.
_ACCEPTABLY_UNREACHABLE: dict[str, str] = {}

# Both disciplines x all three bands, at the largest grade gap so every phase appears, PLUS one
# short plan. Measured: these seven plans between them reach all 100 exercises in ~0.3 s, so the
# guard is cheap enough to sit in the local gate. `sessions_per_week` is varied because the band's
# block budget is what decides how much of a pool the climbing pass ever draws on.
# ⚠️ The last row is the PLAN-LENGTH dimension, and it was the one this guard was missing. Six
# max-gap plans are all 28-32 weeks, and a candidate pool is indexed by `_spread`, which counts
# WEEKS - so a long plan and a short one do not sample the same pool positions. PR C moved the
# base on-wall `endurance` pool from six entries to seven and `outdoor_route_mileage` (position
# 5 of 7) became unreachable at 32 weeks while staying reachable at 20; measured, 128 of the 224
# sport (grade x gap x sessions) combinations reach it. A gap of 3 is the shortest plan that
# still carries all five training phases plus deload and taper, which is the same reason
# `tests/test_planner_climbing_floor.py` uses it.
_PROFILES: tuple[tuple[Discipline, GradeSystemKey, str, str, int], ...] = (
    (Discipline.SPORT, GradeSystemKey.FRENCH, "6a", "8c", 3),
    (Discipline.SPORT, GradeSystemKey.FRENCH, "6c", "8c", 5),
    (Discipline.SPORT, GradeSystemKey.FRENCH, "7c", "8c", 7),
    (Discipline.BOULDER, GradeSystemKey.FONT, "6A", "8B+", 3),
    (Discipline.BOULDER, GradeSystemKey.FONT, "6C", "8B+", 5),
    (Discipline.BOULDER, GradeSystemKey.FONT, "7C", "8B+", 7),
    (Discipline.SPORT, GradeSystemKey.FRENCH, "6a", "6b+", 5),
)

# Kilian's requirement, and the floor is a SHARE of what the discipline can see rather than a
# count: 4 of 100 exercises are boulder-only and 13 rope-only, so a sport plan tops out at 96 and
# a boulder plan at 87, and a count would ask the two for different things. Measured today:
# beginner 67.7% (65/96) and 64.4% (56/87), intermediate 81.2% and 82.8%, advanced 96.9% and
# 98.9%, short sport plan 70.8%. Beginner is lowest by arithmetic, not by defect — the band puts
# 85-90% of its minutes on a wall, so little is left for the off-the-wall half of the library.
#
# ⚠️ **RE-BASELINED 68 → 63** (Kilian, 2026-09-04), and the old number was not a stricter version
# of this one: it was measuring a DEFECT. Four long accessories (`one_arm_lockoff_negatives`,
# `shoulder_band_arcs`, `steep_wall_tension_drill`, `toes_to_bar`) were reachable ONLY through a
# session running UNDER its type's window floor, where `_pick` took the longest candidate that
# fit instead of its plain rotation; round 3's climbing top-up closed that path. Widening
# `_length_pick`'s pool is not the way back and its docstring holds the numbers.
# 63 is the tightest floor honest behaviour supports: the lowest profile is 64.4% (56 of 87), so
# it carries exactly ONE exercise of slack — 55/87 = 63.2% passes, 54/87 = 62.1% does not — and
# that same margin absorbs a new library row this plan does not draw, since authoring one raises
# the denominator. Shown to fail: `_pick` reduced to `pool[0]` draws 57/96 = 59.4%.
_DISTINCT_SHARE_FLOOR_PCT = 63


def _plan(
    discipline: Discipline, system: GradeSystemKey, current: str, target: str, per_week: int
) -> PlanBlueprint:
    """One plan with every piece of equipment, so only the allocator can withhold an exercise."""
    return generate(
        PlannerInput(
            discipline=discipline,
            current_ordinal=ordinal_of(system, current),
            target_ordinal=ordinal_of(system, target),
            sessions_per_week=per_week,
            available_weekdays=0b1111111,
            strength_aspect_key=None,
            weakness_aspect_key=None,
            open_injury_keys=(),
            equipment_keys=_ALL_EQUIPMENT,
            start_date=_MONDAY,
        )
    )


def _blocks_by_exercise(plan: PlanBlueprint) -> Counter[str]:
    """How many blocks each exercise got, which is the only place variety is observable."""
    return Counter(
        block.exercise_key
        for mesocycle in plan.mesocycles
        for microcycle in mesocycle.microcycles
        for session in microcycle.sessions
        for block in session.blocks
    )


def test_every_exercise_the_library_authors_is_reachable_by_some_profile() -> None:
    """⚠️ GUARD, forward arm. An exercise no profile can be prescribed is content nobody can
    train on, and it is invisible to every other test: the plan is still valid and every floor
    still holds. Six were unreachable while the whole suite was green."""
    reached: set[str] = set()
    for profile in _PROFILES:
        reached |= set(_blocks_by_exercise(_plan(*profile)))
    orphans = sorted(
        spec.key for spec in EXERCISES if spec.key not in reached | _ACCEPTABLY_UNREACHABLE.keys()
    )
    assert not orphans, (
        f"no profile can be prescribed {orphans}. Either the allocator has stopped considering "
        f"them - eligibility is prescribable() and on-the-wall is only a PREFERENCE, see "
        f"generate._fill_slot - or they belong in _ACCEPTABLY_UNREACHABLE with a real reason."
    )


def test_no_pinned_unreachable_exercise_has_quietly_become_reachable() -> None:
    """⚠️ GUARD, reverse arm. A pinned list that is only checked one way rots into a stale
    exemption, which is how a real orphan hides behind somebody else's old reason."""
    reached: set[str] = set()
    for profile in _PROFILES:
        reached |= set(_blocks_by_exercise(_plan(*profile)))
    stale = sorted(key for key in _ACCEPTABLY_UNREACHABLE if key in reached)
    assert not stale, (
        f"{stale} are listed in _ACCEPTABLY_UNREACHABLE and are now prescribed. Delete those "
        f"rows - the register is a measurement, not documentation."
    )


def test_every_pinned_key_is_a_real_exercise() -> None:
    """A typo in the register is an exemption for nothing, and silently widens the forward arm."""
    keys = frozenset(spec.key for spec in EXERCISES)
    unknown = sorted(key for key in _ACCEPTABLY_UNREACHABLE if key not in keys)
    assert not unknown, f"_ACCEPTABLY_UNREACHABLE names exercises that do not exist: {unknown}."


def test_one_plan_draws_on_the_breadth_of_the_library() -> None:
    """⚠️ GUARD. Reach across a SWEEP hides per-plan repetition: the same six exercises could
    cover the library between them while every individual plan repeated three of them. Kilian's
    requirement is that one plan has a bit of everything."""
    for profile in _PROFILES:
        discipline = profile[0]
        possible = sum(
            1 for spec in EXERCISES if spec.discipline is None or spec.discipline is discipline
        )
        counts = _blocks_by_exercise(_plan(*profile))
        assert len(counts) * 100 >= _DISTINCT_SHARE_FLOOR_PCT * possible, (
            f"{discipline.value} {profile[2]} at {profile[4]}/wk draws on only {len(counts)} of "
            f"the {possible} exercises this discipline can see, against a floor of "
            f"{_DISTINCT_SHARE_FLOOR_PCT}%; a plan should have a bit of everything rather than "
            f"the same exercises always."
        )
