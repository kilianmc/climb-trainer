"""⚠️ GUARD. A climber with no gear gets a real plan, and every gap in it is named.
DB-free. Critical domain rules, and a project-wide invariant that silently rots: every claim here
is a claim about `server/domain/exercises.py`, which is content edited on its own schedule.
Retiring one bodyweight exercise can take a phase below the three fillable aspects a session needs,
and nothing else in the gate would notice — the generator would keep returning a plan, one block
thinner, with a shortfall that reads as normal. **Kilian 2026-08-24, closing issue #61: the
generator GENERATES and names the shortfall** — never a refusal for lack of gear, never a gate.
This is what makes that promise mechanical. Shown to fail before being trusted; captures in
`.claude/pr-11a-state.md`.
"""

from datetime import date

import pytest

# Bare module name, not `tests.test_exercise_library`: `tests/` has no `__init__.py`, so the
# dotted form makes mypy resolve one file under two module names and fail before it checks
# anything. The matcher is deliberately shared rather than copied — see its comment there.
from test_exercise_library import IMPROVISED_EDGE_RE

from server.domain.exercises import CELLS_WITH_NO_GEARLESS_OPTION
from server.domain.grades import Discipline, GradeSystemKey, ordinal_of
from server.domain.planner.blueprint import PlanBlueprint, SessionBlueprint, Shortfall
from server.domain.planner.contract import PlannerInput
from server.domain.planner.generate import generate
from server.domain.planner.selection import (
    ASPECT_EMPHASIS,
    BLOCKS_PER_SESSION,
    candidates,
    prescribable,
    shortfall_message,
    unlock_options,
)
from server.domain.vocabulary import INJURY_AREAS, ActivityKind, Phase

_MONDAY = date(2026, 8, 24)
_ALL_INJURIES = tuple(sorted(spec.key for spec in INJURY_AREAS))
_CLIMBING_SHORTFALL_OPENER = "Climbing is the core of this plan"


def _gearless_input(**overrides: object) -> PlannerInput:
    """A plannable climber with **zero equipment**, three sessions a week, gap 3.

    Gap 3 is chosen because it is the shortest plan whose block phases cover all five
    training phases, so a per-phase claim asserted over one plan really is asserted over
    every phase — deloads and the taper included.
    """
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
    return PlannerInput(**fields)  # type: ignore[arg-type]


def _every_session(plan: PlanBlueprint) -> list[tuple[Phase, SessionBlueprint]]:
    return [
        (microcycle.phase, session)
        for mesocycle in plan.mesocycles
        for microcycle in mesocycle.microcycles
        for session in microcycle.sessions
    ]


def _all_shortfalls(plan: PlanBlueprint) -> list[Shortfall]:
    found = list(plan.shortfalls)
    for _phase, session in _every_session(plan):
        found.extend(session.shortfalls)
        found.extend(block.shortfall for block in session.blocks if block.shortfall is not None)
    return found


@pytest.mark.parametrize("phase", list(Phase))
def test_every_phase_has_at_least_three_gearless_aspects(phase: Phase) -> None:
    """The measured floor, and it is **exactly** `BLOCKS_PER_SESSION` in two phases.

    Measured against the installed library rather than assumed: with no equipment and no
    open injury, `power_endurance` and `performance` have precisely three fillable aspects
    and every other phase has more. So a climber who has ticked nothing can always be given
    three filled blocks — and one retired bodyweight exercise in either of those two phases
    takes that below three, which is what this guard exists to catch.

    ⚠️ "Gearless" here means the climber has no gear. It does **not** mean the exercise
    carries no contraindication — see `test_the_terminal_all_injuries_case_is_a_named_slot`
    for the case where it does, which is a different and much narrower claim.
    """
    fillable = [
        aspect
        for aspect in ASPECT_EMPHASIS[phase]
        if prescribable(
            candidates(phase, aspect),
            discipline=Discipline.SPORT,
            equipment_keys=(),
            open_injury_keys=(),
        )
    ]
    assert len(fillable) >= BLOCKS_PER_SESSION, (
        f"{phase.value} has only {len(fillable)} aspect(s) a climber with no gear can train "
        f"({fillable}), and a session needs {BLOCKS_PER_SESSION}. Author a no-equipment "
        f"exercise prescribed in {phase.value} in server/domain/exercises.py."
    )


@pytest.mark.parametrize(("phase", "aspect"), CELLS_WITH_NO_GEARLESS_OPTION)
def test_each_gearless_gap_yields_a_shortfall_naming_real_equipment(
    phase: Phase, aspect: str
) -> None:
    """Each of the seventeen cells has to produce an answer, not just fail to fill.

    A shortfall with empty `options` in one of these cells would mean the app admitted a
    limitation without saying what would fix it — which is exactly the "thin block with no
    explanation" the whole decision exists to avoid.
    """
    options = unlock_options(phase, aspect, discipline=Discipline.SPORT, open_injury_keys=())
    assert options, (
        f"({phase.value}, {aspect}) is listed as having no gearless option but nothing "
        f"would unlock it either. Every exercise in the cell was filtered out by something "
        f"other than equipment — check the discipline scoping."
    )
    assert all(option for option in options)
    assert all(list(option) == sorted(option) for option in options)
    assert list(options) == sorted(options)
    message = shortfall_message(phase, aspect, options, open_injury_keys=())
    assert message.endswith(".")


def test_a_gearless_plan_is_complete_and_every_thin_slot_is_explained() -> None:
    """The whole decision, end to end: three blocks a session, and no unexplained gap.

    ⚠️ Since the climbing floor landed (issue #84) a gearless session also carries exactly
    ONE session-level shortfall — nowhere to climb — and that is the naming half of #61, not
    a thin plan: the three blocks are still there.
    """
    plan = generate(_gearless_input())
    sessions = _every_session(plan)
    assert sessions
    for phase, session in sessions:
        assert len(session.blocks) >= BLOCKS_PER_SESSION, (
            f"a {phase.value} session came back with {len(session.blocks)} block(s) for a "
            f"climber with no gear."
        )
        # Every displaced block explains itself; nothing is left unaccounted for.
        assert all(block.aspect_key for block in session.blocks)
        assert len(session.shortfalls) == 1
        assert session.shortfalls[0].options, (
            f"a {phase.value} session with no wall time names no equipment that would give it any."
        )
    assert plan.shortfalls, "a zero-equipment plan that names no shortfall at all is a lie."


def test_the_terminal_all_injuries_case_is_a_named_slot_not_an_empty_one() -> None:
    """⚠️ The one honest exception, and the invariant it does *not* break.

    Zero equipment plus all eleven injury areas open leaves `power_endurance` and `performance`
    with no surviving candidate in any aspect — safety outranks filling a slot. So the session
    becomes an `other`-kind slot titled "Recovery", no blocks, a shortfall per empty slot naming
    the injuries, and the one climbing shortfall every wall-less session now carries (issue #84),
    which names equipment where a wall survives every flag and the injuries where none does.

    The invariant is **never an *unexplained* empty session**, so this asserts the explanation.
    """
    plan = generate(_gearless_input(open_injury_keys=_ALL_INJURIES))
    empty = [(phase, session) for phase, session in _every_session(plan) if not session.blocks]
    assert empty, (
        "the terminal case has disappeared from the library — good news, but this test now "
        "asserts nothing. Re-derive which phases have no injury-surviving gearless candidate."
    )
    assert {phase for phase, _ in empty} == {Phase.POWER_ENDURANCE, Phase.PERFORMANCE}
    for _phase, session in empty:
        assert session.title == "Recovery"
        assert session.activity_kind is ActivityKind.OTHER
        assert session.estimated_minutes is None
        assert session.shortfalls
        climbing = [one for one in session.shortfalls if _CLIMBING_SHORTFALL_OPENER in one.message]
        assert len(climbing) == 1, "a session with no wall time says so exactly once."
        for shortfall in session.shortfalls:
            if _CLIMBING_SHORTFALL_OPENER in shortfall.message:
                continue
            assert shortfall.options == ()
            assert "injured" in shortfall.message


def test_no_shortfall_message_suggests_an_improvised_edge() -> None:
    """⚠️ SAFETY. The same word-boundary matcher `tests/test_exercise_library.py` uses.

    A shortfall names equipment rows and nothing else. The failure this prevents is not a
    broken build: "no hangboard? a door frame works" is the most injury-prone suggestion
    this app could make, and a shortfall message is exactly where a well-meaning edit would
    put it. `exercise.substitution_hint` is deliberately never read by the generator.
    """
    plans = [
        generate(_gearless_input()),
        generate(_gearless_input(open_injury_keys=_ALL_INJURIES)),
        generate(_gearless_input(open_injury_keys=("elbow", "fingers"))),
    ]
    messages = [shortfall.message for plan in plans for shortfall in _all_shortfalls(plan)]
    assert messages
    offenders = [message for message in messages if IMPROVISED_EDGE_RE.search(message)]
    assert not offenders, (
        f"these shortfall messages read as a suggestion to improvise: {offenders}. A "
        f"shortfall names equipment rows only — never a movement substitute, never an edge."
    )
