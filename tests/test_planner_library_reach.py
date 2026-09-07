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
_ACCEPTABLY_UNREACHABLE: dict[str, str] = {
    "campus_board_bumps": (
        "Authored for the POWER block, which ruling 51 dropped. Its one surviving row is "
        "PERFORMANCE and no week of the new plan draws it. Shown: put a POWER block anywhere "
        "in the plan and the row is prescribed again."
    ),
    "loaded_jump_squats": (
        "Rows in STRENGTH and POWER only; ruling 51 dropped POWER and the STRENGTH pool "
        "reaches this off-wall power row at no week of the block. Shown: restoring a POWER "
        "block prescribes it again."
    ),
    "weighted_pull_ups": (
        "Rows in STRENGTH, POWER and TAPER; ruling 51 dropped POWER and neither surviving row "
        "is drawn at any week. Shown: restoring a POWER block prescribes it again."
    ),
    "weighted_hanging_knee_raises": (
        "Rows in STRENGTH and POWER only, and `core_tension` is a SUPPORT_ASPECTS rotation "
        "that never reaches it in the strength block. Shown: restoring a POWER block "
        "prescribes it again."
    ),
    "open_hand_drag_hangs": (
        "A WEEK-POSITION orphan, not a phase one: `_spread` draws this hangboard row in "
        "STRENGTH weeks 10-11 and 17-18 and never in weeks 5-7, which is the single strength "
        "block a sixteen-week plan has. It was reachable only because these profiles used to "
        "be 28-32-week plans carrying a SECOND strength block at weeks 17-19. Shown: slide "
        "the strength block to weeks 9-11 or 17-19 and six or seven blocks of it appear."
    ),
    "auto_belay_interval_laps": (
        "The other WEEK-POSITION orphan, and NOT a power-block casualty. Its only row is "
        "POWER_ENDURANCE, and it is drawn when that block sits at weeks 5-7, 13-15 or 17-19 "
        "and at none of weeks 9-11, which is where ruling 51 puts it. Shown: slide the "
        "power-endurance block to any other slot and the row is prescribed again."
    ),
}

# Both disciplines x all three bands, with `sessions_per_week` varied because the band's block
# budget is what decides how much of a pool the climbing pass ever draws on. These seven plans
# between them reach 100 of 106 exercises in ~0.3 s, so the guard sits in the local gate.
# ⚠️ THE TARGET GRADES NO LONGER VARY THE LENGTH (ruling 49), so the max-gap targets are inert
# here and the last row is no longer a short plan. A candidate pool is indexed by `_spread`,
# which counts WEEKS, and two rows are now drawn only at week numbers no plan has - see
# `_ACCEPTABLY_UNREACHABLE`. ⚠️ Do NOT restore a length dimension by hand-lengthening a
# profile: `mesocycle_spans()` is the one source of the shape.
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
# count: 4 of 106 exercises are boulder-only and 13 rope-only, so a sport plan tops out at 102
# and a boulder plan at 93, and a count would ask the two for different things. ⚠️ RE-MEASURED
# at ruling 49's sixteen weeks: beginner 67.6% and 65.6%, intermediate 83.3% and 82.8%,
# advanced 85.3% and 86.0%, the 5-session beginner 78.4%. Beginner is lowest by arithmetic, not
# by defect — the band puts 85-90% of a loading week's minutes on a wall.
#
# ⚠️ **RE-BASELINED 68 → 63** (Kilian, 2026-09-04), and the old number was not a stricter version
# of this one: it was measuring a DEFECT. Four long accessories (`one_arm_lockoff_negatives`,
# `shoulder_band_arcs`, `steep_wall_tension_drill`, `toes_to_bar`) were reachable ONLY through a
# session running UNDER its type's window floor, where `_pick` took the longest candidate that
# fit instead of its plain rotation; round 3's climbing top-up closed that path. Widening
# `_length_pick`'s pool is not the way back and its docstring holds the numbers.
# ⚠️ 63 STANDS and is NOT re-based here — green on 7 of 7 under ruling 51's order. ⚠️ But its
# SLACK is gone: the lowest profile fell 79.2% -> 65.6% (61 of 93) against a floor needing 59,
# so TWO exercises could go undrawn now where fifteen could before. Moving it is KILIAN'S call.
# Shown to fail: `_pick` as `pool[0]` draws 58/101 = 57.4%.
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
