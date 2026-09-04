"""`PHASE_GUIDE` must cover every `Phase`, and every claim it makes is measured off a plan.

Coverage is asserted in BOTH directions: a new `Phase` cannot ship with no explanation, and a
stale entry cannot linger as dead copy. The lead claims used to be compared to `ASPECT_EMPHASIS`,
a table of intentions, so the file checked the app's intention against itself — and stayed green
while all six sentences were false. They now `generate()` plans and read them, in four shapes.

⚠️ Links are checked as a 2-3 item list, never for reachability: a short tuple is legal Python
and renders as a phase with a lone pointer where the copy claims a set of sources.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import cache

from test_planner_climbing_floor import _CLIMBERS, _block_seconds, _input, _on_wall

from server.domain.exercises import DELIBERATELY_UNPRESCRIBED
from server.domain.grades import Discipline, GradeSystemKey
from server.domain.planner.blueprint import SessionBlueprint
from server.domain.planner.generate import generate
from server.domain.vocabulary import (
    PHASE_GUIDE,
    PLAN_GOAL,
    GuideLink,
    Phase,
    PhaseGuide,
    ProtocolKind,
)

_KEYS = tuple(guide.phase.value for guide in PHASE_GUIDE)

# What each phase's authored `how_to_train` CLAIMS, restated as data on `_BASE_WALL_EMPHASIS`'s
# idiom. Four tables because the sentences make four different kinds of claim.
COPY_CLAIMS_LEAD: dict[Phase, tuple[str, ...]] = {
    Phase.BASE: ("endurance", "technique"),
    Phase.POWER: ("power", "finger_strength"),
    Phase.PERFORMANCE: ("power",),
}

# The deload names two aspects and neither leads alone: measured, technique opens 45.6% of
# deload sessions and mobility 10.0%, so the claim is the majority they lead between them.
COPY_CLAIMS_DELOAD_PAIR: tuple[str, ...] = ("technique", "mobility")

# `PHASE_GUIDE[strength]`'s claim is ORDER: one or two hangboard sessions in a five-session
# week can never be modal, and measured finger strength opens 18.3% of strength sessions.
COPY_CLAIMS_GOES_FIRST: tuple[Phase, str] = (Phase.STRENGTH, "finger_strength")

# A real hangboard block, and the only kinds allowed in front of one. Measured over the sweep,
# 56 of 80 strength sessions open with the hangboard and 24 sit behind a limit boulder.
_HANGBOARD_PROTOCOLS = frozenset({ProtocolKind.MAX_HANG, ProtocolKind.REPEATERS})
_MAY_PRECEDE_A_HANG = _HANGBOARD_PROTOCOLS | {ProtocolKind.LIMIT_BOULDER}

# "the aerobic work underneath… never enough to out-train the quality the block is named after":
# a PAIRWISE minutes claim, and the only one of that block's rankings true on every profile.
COPY_CLAIMS_OUT_MINUTES: dict[Phase, tuple[str, str]] = {
    Phase.POWER_ENDURANCE: ("power_endurance", "endurance")
}

# "power sits last on purpose", `PHASE_GUIDE[base]`, measured against the three qualities the
# same sentence says base is for. The share ceiling in test_planner_climbing_floor.py is its twin.
COPY_CLAIMS_LAST: dict[Phase, tuple[str, tuple[str, ...]]] = {
    Phase.BASE: ("power", ("endurance", "technique", "anaerobic_capacity"))
}

# Every aspect a phase's copy tells the reader is NOT prescribed there.
COPY_CLAIMS_ABSENT: dict[Phase, tuple[str, ...]] = {
    Phase.POWER: ("power_endurance",),
    Phase.POWER_ENDURANCE: ("general_strength",),
    Phase.PERFORMANCE: ("anaerobic_capacity",),
    Phase.TAPER: (
        "finger_strength",
        "power_endurance",
        "anaerobic_capacity",
        "general_strength",
    ),
}

# 2-3 per phase is the authored range: one source cannot show a contested claim from both
# sides, and more than three is a reading list rather than a pointer.
MIN_LINKS = 2
MAX_LINKS = 3

# Six climbers x four session counts at the file's default gap of 3, `weakness_aspect_key=None`
# as every plan-shape test runs: 24 plans, about a second, cached across every arm below.
_SESSION_COUNTS: tuple[int, ...] = (2, 3, 5, 7)


@dataclass(frozen=True, slots=True)
class _Climber:
    """One generated plan's inputs, frozen so `@cache` can key generation on it."""

    discipline: Discipline
    system: GradeSystemKey
    grade: str
    sessions: int


_SWEEP: tuple[_Climber, ...] = tuple(
    _Climber(discipline, system, grade, sessions)
    for _level, discipline, system, grade in _CLIMBERS
    for sessions in _SESSION_COUNTS
)


@cache
def _sessions_by_phase(climber: _Climber) -> Mapping[Phase, tuple[SessionBlueprint, ...]]:
    """Every session of one generated plan, grouped by the phase of the week it sits in."""
    plan = generate(
        _input(climber.discipline, climber.system, climber.grade, climber.sessions, 0b111_1111)
    )
    grouped: dict[Phase, list[SessionBlueprint]] = {}
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            grouped.setdefault(microcycle.phase, []).extend(microcycle.sessions)
    return {phase: tuple(sessions) for phase, sessions in grouped.items()}


def _phase_sessions(phase: Phase) -> list[SessionBlueprint]:
    """Every session the whole sweep prescribes in `phase`, pooled over all 24 plans."""
    return [session for climber in _SWEEP for session in _sessions_by_phase(climber).get(phase, ())]


def _first_block_counts(phase: Phase) -> Counter[str]:
    """Which aspect OPENS a session, counted over the pooled sweep."""
    return Counter(
        session.blocks[0].aspect_key for session in _phase_sessions(phase) if session.blocks
    )


def _climber_aspect_seconds(climber: _Climber, phase: Phase) -> Counter[str]:
    """Prescribed seconds per aspect inside ONE climber's plan, where a per-profile claim lives."""
    seconds: Counter[str] = Counter()
    for session in _sessions_by_phase(climber).get(phase, ()):
        for block in session.blocks:
            seconds[block.aspect_key] += _block_seconds(block)
    return seconds


def _aspect_seconds(phase: Phase, *, wall_only: bool = False) -> Counter[str]:
    """Prescribed seconds per aspect over the pooled sweep, optionally on-the-wall only."""
    seconds: Counter[str] = Counter()
    for session in _phase_sessions(phase):
        for block in session.blocks:
            if wall_only and not _on_wall(block):
                continue
            seconds[block.aspect_key] += _block_seconds(block)
    return seconds


def _phases_with_unusable_links(guides: tuple[PhaseGuide, ...]) -> set[Phase]:
    """Every phase whose links fail the contract: outside 2-3, or a blank half."""
    broken: set[Phase] = set()
    for guide in guides:
        if not MIN_LINKS <= len(guide.links) <= MAX_LINKS:
            broken.add(guide.phase)
        for link in guide.links:
            if not link.url.startswith("https://") or not link.label.strip():
                broken.add(guide.phase)
    return broken


def test_every_phase_has_copy_and_no_entry_is_stale() -> None:
    """Set equality, so a missing phase and an orphaned entry both fail."""
    assert set(_KEYS) == {member.value for member in Phase}


def test_the_order_is_the_ENUM_declaration_order() -> None:
    """It is sent as an array and read as one, so its order is display order."""
    assert _KEYS == tuple(member.value for member in Phase)


def test_no_phase_appears_twice() -> None:
    """A duplicate would pass the set comparison above while shadowing one of the two."""
    assert len(_KEYS) == len(set(_KEYS))


def test_the_copys_LEAD_claims_name_the_MODAL_FIRST_BLOCK_of_a_generated_plan() -> None:
    """⚠️ GUARD. Pooled over the sweep, because `PHASE_GUIDE` is UNIVERSAL copy — keyed by phase
    and shown to every climber — so a population-level claim is the matching granularity.

    ⚠️ Measured slack: none of these holds on every profile. An advanced climber's power and
    performance blocks open with fingers, and a 7x intermediate's base opens with anaerobic
    capacity. It proves the copy, not any one plan.
    """
    for phase, claimed in COPY_CLAIMS_LEAD.items():
        counts = _first_block_counts(phase)
        assert counts, f"no {phase.value} sessions in the sweep; the parametrisation is wrong."
        ranked = tuple(aspect for aspect, _n in counts.most_common(len(claimed)))
        lowest_claimed = min(counts[aspect] for aspect in claimed)
        rest = [count for aspect, count in counts.items() if aspect not in claimed]
        assert ranked == claimed and all(count < lowest_claimed for count in rest), (
            f"PHASE_GUIDE[{phase.value}] tells the reader {claimed} lead its sessions, but over "
            f"{sum(counts.values())} generated sessions the generator opens them "
            f"{counts.most_common(4)}. Reword the sentence or change the generator — never the "
            f"table alone."
        )


def test_the_copys_DELOAD_claim_is_TWO_aspects_leading_a_MAJORITY_between_them() -> None:
    """⚠️ GUARD. "technique and mobility lead at low load" is not a modal claim about either of
    them: mobility opens a tenth of these sessions, and the pair is what carries the sentence."""
    counts = _first_block_counts(Phase.DELOAD)
    total = sum(counts.values())
    led = sum(counts[aspect] for aspect in COPY_CLAIMS_DELOAD_PAIR)
    assert led * 2 > total, (
        f"PHASE_GUIDE[deload] says {' and '.join(COPY_CLAIMS_DELOAD_PAIR)} lead at low load, but "
        f"they open {led} of {total} generated deload sessions ({100 * led / total:.1f}%), which "
        f"is not a majority. The generator opens them {counts.most_common(4)}."
    )
    assert counts.most_common(1)[0][0] == COPY_CLAIMS_DELOAD_PAIR[0], (
        f"the pair leads, but {counts.most_common(1)[0][0]} is now the single most common opener "
        f"of a deload session rather than {COPY_CLAIMS_DELOAD_PAIR[0]}."
    )


def test_the_copys_STRENGTH_claim_is_ORDER_and_not_FREQUENCY() -> None:
    """⚠️ GUARD. Fingers can never be the modal first block — one or two hangboard sessions in a
    five-session week — so the checkable claim is what may sit in front of one."""
    phase, aspect = COPY_CLAIMS_GOES_FIRST
    for session in _phase_sessions(phase):
        hangs = [block for block in session.blocks if block.protocol_kind in _HANGBOARD_PROTOCOLS]
        if not hangs:
            continue
        ahead = [
            block
            for block in session.blocks
            if block.order_index < hangs[0].order_index
            and block.protocol_kind not in _MAY_PRECEDE_A_HANG
        ]
        assert not ahead, (
            f"PHASE_GUIDE[{phase.value}] says a hangboard session opens with the hangboard, "
            f"ahead of any volume climbing, but {hangs[0].exercise_key} sits behind "
            f"{[block.exercise_key for block in ahead]} in a generated {phase.value} session."
        )
    # The anti-vacuity arm: if fingers ever DID open most strength sessions the copy would owe
    # the stronger claim, and this shape would be the weaker one nobody had noticed.
    counts = _first_block_counts(phase)
    assert counts.most_common(1)[0][0] != aspect, (
        f"{aspect} is now the modal opener of a {phase.value} session ({counts.most_common(3)}), "
        f"so the copy may make the stronger lead claim and this arm has stopped being the truth."
    )


def test_the_copys_POWER_ENDURANCE_claim_KEEPS_THE_AEROBIC_WORK_UNDER_IT() -> None:
    """⚠️ GUARD, per climber as the performance arm is. Pooled, PE topped its block on 13 of 24
    profiles; PE > endurance on 24 of 24 — thinnest 17.8% vs 13.7%, and 17 profiles take zero."""
    for phase, (aspect, under) in COPY_CLAIMS_OUT_MINUTES.items():
        for climber in _SWEEP:
            seconds = _climber_aspect_seconds(climber, phase)
            total = sum(seconds.values())
            assert total, f"no {phase.value} minutes for {climber}; the parametrisation is wrong."
            assert seconds[aspect] > seconds[under], (
                f"PHASE_GUIDE[{phase.value}] tells the reader the {under} work underneath is kept "
                f"small enough never to out-train {aspect}, but a {climber.grade} "
                f"{climber.discipline.value} climber training {climber.sessions}x a week gets "
                f"{100 * seconds[under] / total:.1f}% {under} against "
                f"{100 * seconds[aspect] / total:.1f}% {aspect}."
            )


def test_the_copys_LAST_claim_is_measured_against_the_qualities_the_block_is_FOR() -> None:
    """⚠️ GUARD. "power sits last on purpose": measured 2.1-7.3% of a base block's WALL minutes,
    under each quality the same sentence prioritises. The tail ceiling elsewhere is its twin."""
    for phase, (last, ahead) in COPY_CLAIMS_LAST.items():
        wall = _aspect_seconds(phase, wall_only=True)
        total = sum(wall.values())
        assert total, f"no {phase.value} wall minutes in the sweep; the parametrisation is wrong."
        assert all(wall[last] < wall[key] for key in ahead), (
            f"PHASE_GUIDE[{phase.value}] says {last} sits last on purpose, but it takes "
            f"{100 * wall[last] / total:.1f}% of the block's wall minutes against "
            f"{[(key, f'{100 * wall[key] / total:.1f}%') for key in ahead]}."
        )


def test_the_copys_PERFORMANCE_claim_keeps_power_endurance_IN_the_block() -> None:
    """The reworded half, per climber rather than pooled: "power endurance keeps a share of it
    throughout". Measured 4.7-30.0% of the block's minutes and never zero on any profile."""
    for climber in _SWEEP:
        sessions = _sessions_by_phase(climber).get(Phase.PERFORMANCE, ())
        seconds = sum(
            _block_seconds(block)
            for session in sessions
            for block in session.blocks
            if block.aspect_key == "power_endurance"
        )
        assert seconds, (
            f"PHASE_GUIDE[performance] says power endurance keeps a share of the block, but a "
            f"{climber.grade} {climber.discipline.value} climber training {climber.sessions}x a "
            f"week gets none of it in {len(sessions)} performance sessions."
        )


def test_the_copys_ABSENCE_CLAIMS_match_the_library() -> None:
    """⚠️ GUARD, the other half. Copy naming a quality as deliberately absent is a claim about
    `DELIBERATELY_UNPRESCRIBED`, and filling one of those cells would make it a lie."""
    unprescribed = {(cell.phase, cell.aspect_key) for cell in DELIBERATELY_UNPRESCRIBED}
    for phase, absent in COPY_CLAIMS_ABSENT.items():
        for aspect in absent:
            assert (phase, aspect) in unprescribed, (
                f"PHASE_GUIDE[{phase.value}] tells the reader {aspect} is deliberately absent, "
                f"but the library prescribes it there."
            )


def test_no_field_the_screen_renders_is_blank() -> None:
    """An empty string is a blank disclosure on the plan screen, not an absent one."""
    assert PLAN_GOAL.strip()
    for guide in PHASE_GUIDE:
        assert guide.label.strip()
        assert guide.summary.strip()
        assert guide.how_to_train.strip()


def test_every_phase_has_TWO_OR_THREE_usable_links() -> None:
    """The shipped copy, through the same predicate the controls below cripple."""
    assert _phases_with_unusable_links(PHASE_GUIDE) == set()


def test_a_phase_with_ZERO_links_fails() -> None:
    """Positive control for the likeliest accident: the list left empty and nothing complains."""
    stripped = tuple(
        replace(guide, links=()) if guide.phase is Phase.TAPER else guide for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(stripped) == {Phase.TAPER}


def test_a_phase_with_ONE_link_fails() -> None:
    """The lower bound, shown failing: a single link is what the placeholder round shipped."""
    thinned = tuple(
        replace(guide, links=guide.links[:1]) if guide.phase is Phase.DELOAD else guide
        for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(thinned) == {Phase.DELOAD}


def test_a_LABELLESS_or_INSECURE_link_fails() -> None:
    """The other two halves of the same predicate, shown failing rather than assumed. Both
    plants keep TWO links, so what fails is the label or the scheme, not the count arm."""
    labelless = tuple(
        replace(guide, links=(GuideLink(guide.links[0].url, "   "), guide.links[1]))
        if guide.phase is Phase.BASE
        else guide
        for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(labelless) == {Phase.BASE}

    insecure = tuple(
        replace(guide, links=(GuideLink("http://example.com", "Fine words"), guide.links[0]))
        if guide.phase is Phase.POWER
        else guide
        for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(insecure) == {Phase.POWER}


def test_the_comparison_would_notice_a_phase_with_no_copy() -> None:
    """Positive control: a detector that cannot see its own violation is worse than none."""
    crippled = {member.value for member in Phase if member is not Phase.TAPER}
    assert crippled != {member.value for member in Phase}
    assert set(_KEYS) != crippled


def test_the_comparison_would_notice_a_STALE_entry() -> None:
    """The other direction, which a `>=` containment check would have missed."""
    stale = set(_KEYS) | {"anaerobic_capacity"}
    assert stale != {member.value for member in Phase}
