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

# "at three days or fewer ... some weeks hold none of it at all, and from four days up every
# week carries some": the day count the re-authored sentence names as its boundary.
COPY_CLAIMS_AEROBIC_FROM_DAYS: int = 4

# "At five days a week and under, power endurance is still the biggest thing in the block; at
# six or seven days that ordinary climbing is": one boundary, and the aspect on each side of it.
COPY_CLAIMS_BIGGEST_UNTIL_DAYS: int = 5
COPY_CLAIMS_BIGGEST_BY_DAYS: tuple[str, str] = ("power_endurance", "technique")

# Ruling 29's filler family, RESTATED and never imported: "ordinary climbing" in the copy means
# these rows, and an arm that asked `selection.py` which rows it treats as a fill would borrow
# its expectation from the code it checks — round 5 shipped exactly that mistake once.
_OPEN_CLIMBING_KEYS: frozenset[str] = frozenset(
    {
        "open_climbing_easy_mileage",
        "open_climbing_power_endurance",
        "open_climbing_hard_moves",
        "open_climbing_for_fun",
    }
)

# "power sits last on purpose", `PHASE_GUIDE[base]`, measured against the three qualities the
# same sentence says base is for. The share ceiling in test_planner_climbing_floor.py is its twin.
COPY_CLAIMS_LAST: dict[Phase, tuple[str, tuple[str, ...]]] = {
    Phase.BASE: ("power", ("endurance", "technique", "anaerobic_capacity"))
}

# The defect this arm was written to register, kept as the number it is measured against: 23 of
# the 24 swept profiles lost general strength from a base block at BOTH weakness values.
_WEAKNESS_STARVED_BASE_PROFILES_BEFORE_RULING_21 = 23
_A_WEAKNESS_YIELDS_SLOT_ONE = (
    "Nothing measured this before: every plan-shape test in the repo passed "
    "`weakness_aspect_key=None`, and at None the claim held on 24 of 24. Ruling 21 changed the "
    "GENERATOR and kept the copy: slot 1 yields the declared weakness one turn in "
    "`WEAKNESS_YIELDS_SLOT_ONE_EVERY`, and a yielded turn rotates over the aspects with no "
    "other route into a plan (`generate.py::_no_other_route`) rather than over the whole "
    "secondary pool, which a three-week base block is too short to walk. A weakness is still "
    "the organising principle both sources make it; it may not delete a quality to be one."
)

# The other two claims of `PHASE_GUIDE[base]`'s closing sentence. "Endurance takes more of these
# weeks' time on the wall than any other quality" is a WALL claim; "general strength and
# anaerobic capacity both start here" is a presence claim over all base minutes.
COPY_CLAIMS_BASE_LEAD: str = "endurance"
COPY_CLAIMS_BASE_START: tuple[str, ...] = ("general_strength", "anaerobic_capacity")

# Every aspect a phase's copy tells the reader is NOT prescribed there.
COPY_CLAIMS_ABSENT: dict[Phase, tuple[str, ...]] = {
    Phase.POWER: ("power_endurance",),
    Phase.POWER_ENDURANCE: ("general_strength",),
    Phase.PERFORMANCE: ("anaerobic_capacity",),
    Phase.TAPER: ("finger_strength", "anaerobic_capacity", "endurance"),
}

# 2-3 per phase is the authored range: one source cannot show a contested claim from both
# sides, and more than three is a reading list rather than a pointer.
MIN_LINKS = 2
MAX_LINKS = 3

# Six climbers x four session counts at the file's default gap of 3, `weakness_aspect_key=None`
# as every plan-shape test runs: 24 plans, about a second, cached across every arm below.
_SESSION_COUNTS: tuple[int, ...] = (2, 3, 5, 7)

# Ruling 31 made the DAY COUNT the subject of the power-endurance block's copy and of PLAN_GOAL's
# weekly-volume sentence, so those two arms sweep all seven counts rather than these four.
_EVERY_SESSION_COUNT: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)

# "every day you tell us you can train gets a whole session" — the share of a solo plan's minutes
# each extra day must buy. Measured 1.00-1.02x of it at every count, so 90% is honest slack.
PLAN_GOAL_DAY_SHARE_PCT: int = 90


@dataclass(frozen=True, slots=True)
class _Climber:
    """One generated plan's inputs, frozen so `@cache` can key generation on it.

    ⚠️ `weakness` is a FIELD and therefore part of that key. A weakness dimension left out of it
    would hand every arm below the `None` plan and call the difference measured."""

    discipline: Discipline
    system: GradeSystemKey
    grade: str
    sessions: int
    weakness: str | None = None


_SWEEP: tuple[_Climber, ...] = tuple(
    _Climber(discipline, system, grade, sessions)
    for _level, discipline, system, grade in _CLIMBERS
    for sessions in _SESSION_COUNTS
)


# The sweep the per-climber copy arms read, with the DECLARED WEAKNESS as a third dimension:
# `PHASE_GUIDE` is the same copy whatever the climber declared, so a claim it makes has to hold
# at every value of the largest categorical lever in the generator. 72 plans, cached.
_WEAKNESS_SWEEP: tuple[_Climber, ...] = tuple(
    replace(climber, weakness=weakness)
    for climber in _SWEEP
    for weakness in (None, "power", "power_endurance")
)


_PE_SWEEP: tuple[_Climber, ...] = tuple(
    _Climber(discipline, system, grade, sessions)
    for _level, discipline, system, grade in _CLIMBERS
    for sessions in _EVERY_SESSION_COUNT
)


@cache
def _weeks_by_phase(climber: _Climber) -> Mapping[Phase, tuple[tuple[SessionBlueprint, ...], ...]]:
    """One generated plan grouped by phase with the WEEKS inside it kept SEPARATE.

    ⚠️ `_sessions_by_phase` pools these and a claim about "every week" cannot be read off the
    pool: at four days a week and up every profile holds aerobic work SOMEWHERE in the
    power-endurance block (18 of 18) while 12 of those same 72 weeks hold none."""
    plan = generate(
        _input(
            climber.discipline,
            climber.system,
            climber.grade,
            climber.sessions,
            0b111_1111,
            weakness=climber.weakness,
        )
    )
    grouped: dict[Phase, list[tuple[SessionBlueprint, ...]]] = {}
    for mesocycle in plan.mesocycles:
        for microcycle in mesocycle.microcycles:
            grouped.setdefault(microcycle.phase, []).append(microcycle.sessions)
    return {phase: tuple(weeks) for phase, weeks in grouped.items()}


def _sessions_by_phase(climber: _Climber) -> Mapping[Phase, tuple[SessionBlueprint, ...]]:
    """Every session of one generated plan, grouped by the phase of the week it sits in."""
    return {
        phase: tuple(session for week in weeks for session in week)
        for phase, weeks in _weeks_by_phase(climber).items()
    }


def _weeks_holding(climber: _Climber, phase: Phase, aspect_key: str) -> tuple[bool, ...]:
    """Whether each WEEK of `phase` carries any block of `aspect_key`, in plan order."""
    return tuple(
        any(block.aspect_key == aspect_key for session in week for block in session.blocks)
        for week in _weeks_by_phase(climber).get(phase, ())
    )


def _label(climber: _Climber) -> str:
    """One climber of a sweep, as a failure message names it."""
    return f"{climber.grade} {climber.discipline.value} {climber.sessions}x"


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


def _climber_plan_seconds(climber: _Climber) -> int:
    """Every prescribed second of one climber's WHOLE plan — what "a longer week" is measured in.
    Recomputed off the blueprint rather than read off `estimated_minutes`, which adds warm-up."""
    return sum(
        _block_seconds(block)
        for sessions in _sessions_by_phase(climber).values()
        for session in sessions
        for block in session.blocks
    )


def _climber_wall_seconds(climber: _Climber, phase: Phase) -> Counter[str]:
    """`_climber_aspect_seconds`' wall-only twin, for the half of the sentence that says wall."""
    seconds: Counter[str] = Counter()
    for session in _sessions_by_phase(climber).get(phase, ()):
        for block in session.blocks:
            if _on_wall(block):
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


def test_the_copys_POWER_ENDURANCE_AEROBIC_claim_is_a_DAY_COUNT_claim() -> None:
    """⚠️ GUARD, per WEEK and per climber over every session count. Ruling 24's aerobic floor was
    REVOKED, so there is no mechanism behind this sentence and this guard is the only thing
    between the ruling and a published lie. Three arms, one per clause of the sentence.

    ⚠️ THE GRANULARITY IS THE CLAIM. Read per profile the block-level arm is green — every
    profile at four days up holds aerobic work SOMEWHERE (18 of 18) — while 12 of those same 72
    weeks hold none, which is why the copy says "not always in every week". No day count repairs
    it: zero weeks are 6 of 18 at four days and 2 of 18 at five, six and seven, all in week 14
    or 15. Below the boundary: 18 of 18 weeks at one day, 10 of 18 at two, 9 of 18 at three.
    """
    above = [c for c in _PE_SWEEP if c.sessions >= COPY_CLAIMS_AEROBIC_FROM_DAYS]
    below = [c for c in _PE_SWEEP if c.sessions < COPY_CLAIMS_AEROBIC_FROM_DAYS]
    weeks = {c: _weeks_holding(c, Phase.POWER_ENDURANCE, "endurance") for c in _PE_SWEEP}
    # "from four days up you always get some of it" — per CLIMBER, because "you" is one climber.
    barren = sorted(_label(c) for c in above if not any(weeks[c]))
    assert not barren, (
        f"PHASE_GUIDE[power_endurance] tells the reader that from "
        f"{COPY_CLAIMS_AEROBIC_FROM_DAYS} days a week up they always get some aerobic work, but "
        f"{barren} get none of it in the whole block. Reword the sentence or change the "
        f"generator — never the table alone."
    )
    # "though not always in every week" — the copy's own hedge, and the arm that keeps it honest
    # if the generator ever starts delivering one every week and the copy owes the stronger claim.
    hedged = sorted(_label(c) for c in above if not all(weeks[c]))
    assert hedged, (
        f"PHASE_GUIDE[power_endurance] hedges that from {COPY_CLAIMS_AEROBIC_FROM_DAYS} days a "
        f"week up the aerobic work is not always in EVERY week, and now every one of "
        f"{len(above)} profiles above that boundary carries it in all of theirs. The copy owes "
        f"the stronger claim — reword the sentence, never the table alone."
    )
    # "at three days or fewer ... some weeks hold none of it at all" — an admission goes stale
    # in silence, so it is asserted rather than assumed.
    lean = sorted(_label(c) for c in below if not all(weeks[c]))
    assert lean, (
        f"PHASE_GUIDE[power_endurance] admits that below {COPY_CLAIMS_AEROBIC_FROM_DAYS} days a "
        f"week some weeks of this block hold no aerobic work at all, and now every one of "
        f"{len(below)} profiles below that boundary carries it every week. The copy owes the "
        f"stronger claim — reword the sentence, never the table alone."
    )


def test_the_copys_POWER_ENDURANCE_claim_about_WHAT_IS_BIGGEST_FLIPS_WITH_THE_DAYS() -> None:
    """⚠️ GUARD, per climber over EVERY session count. Ruling 31 accepted that `technique` is
    the majority quality of this block at high day counts and ordered the copy to ADMIT it, so
    this asserts the admission in BOTH regimes rather than asserting the block's own quality
    leads everywhere — which is false above five days and was the open red for five rounds.

    Measured, all minutes of the block: power endurance is the largest quality on 30 of 30
    profiles at one to five sessions a week (69.8–82.5% at one day, 32.9–47.9% at five), and
    `technique` is the largest on 12 of 12 at six and seven (37.5–50.8% against power
    endurance's 23.0–34.2%). Cause, structural: ruling 9 allows three hard days however many
    days there are, so the remaining fills go to ruling 30's non-governed fallback.
    ⚠️ The second arm is what earns the copy the words ORDINARY CLIMBING rather than "movement
    drills": 53–90% of those technique minutes are ruling 29's open-climbing filler.
    """
    under, over = COPY_CLAIMS_BIGGEST_BY_DAYS
    for climber in _PE_SWEEP:
        seconds = _climber_aspect_seconds(climber, Phase.POWER_ENDURANCE)
        total = sum(seconds.values())
        assert total, f"no power_endurance minutes for {climber}; the parametrisation is wrong."
        claimed = under if climber.sessions <= COPY_CLAIMS_BIGGEST_UNTIL_DAYS else over
        assert seconds.most_common(1)[0][0] == claimed, (
            f"PHASE_GUIDE[power_endurance] says {claimed} is the biggest thing in the block at "
            f"{climber.sessions} days a week, but a {climber.grade} {climber.discipline.value} "
            f"climber gets {seconds.most_common(3)} — {100 * seconds[claimed] / total:.1f}% "
            f"{claimed}. Reword the sentence or change the generator — never the table alone."
        )
    for climber in _PE_SWEEP:
        if climber.sessions <= COPY_CLAIMS_BIGGEST_UNTIL_DAYS:
            continue
        blocks = [
            block
            for session in _sessions_by_phase(climber).get(Phase.POWER_ENDURANCE, ())
            for block in session.blocks
            if block.aspect_key == over
        ]
        led = sum(_block_seconds(block) for block in blocks)
        fill = sum(
            _block_seconds(block) for block in blocks if block.exercise_key in _OPEN_CLIMBING_KEYS
        )
        assert led and fill * 2 > led, (
            f"the copy calls what is biggest in this block at {climber.sessions} days a week "
            f"ORDINARY CLIMBING, but only {100 * fill / (led or 1):.1f}% of a {climber.grade} "
            f"{climber.discipline.value} climber's {over} minutes there come from the "
            f"open-climbing rows — the rest are drills, which is a different promise."
        )


def test_PLAN_GOALs_claim_that_MORE_DAYS_IS_A_LONGER_WEEK() -> None:
    """⚠️ GUARD on the executable half of ruling 31's declaration in `PLAN_GOAL`: "a week with
    more days on it is a longer week rather than the same hours spread thinner". Every day the
    climber offers buys a whole session at ruling 25's floor, so plan minutes rise with the day
    count instead of being divided by it.

    ⚠️ The OTHER half of that sentence — that this lands 2–4× above every band Lattice measured,
    and that it is KILIAN'S choice and not the sources' — is a DECLARATION, stated in the copy on
    ruling 17's precedent and carrying its numbers in `climbing.py`'s SESSION_MINUTES_TARGET
    comment. Nothing in the app can measure Lattice's population, so it is not asserted here.
    """
    for _level, discipline, system, grade in _CLIMBERS:
        by_days = [
            _climber_plan_seconds(_Climber(discipline, system, grade, sessions))
            for sessions in _EVERY_SESSION_COUNT
        ]
        assert by_days == sorted(by_days) and by_days[-1] > by_days[0], (
            f"PLAN_GOAL tells a {grade} {discipline.value} climber that a week with more days "
            f"on it is a longer week, but their whole-plan minutes by day count "
            f"{_EVERY_SESSION_COUNT} are {[seconds // 60 for seconds in by_days]}."
        )
        # ⚠️ The arm that actually bites. Rising totals are already ruling 3's window floor and
        # ruling 4's rule; only PROPORTIONALITY says the hours were not divided by the days.
        for days, seconds in zip(_EVERY_SESSION_COUNT, by_days, strict=True):
            assert seconds * 100 >= days * by_days[0] * PLAN_GOAL_DAY_SHARE_PCT, (
                f"PLAN_GOAL tells a {grade} {discipline.value} climber that every day they "
                f"offer buys a whole session rather than the same hours spread thinner, but "
                f"{days} days give {seconds // 60} min against {days} x "
                f"{by_days[0] // 60} min for the one-day plan."
            )


def test_the_copys_LAST_claim_is_measured_against_the_qualities_the_block_is_FOR() -> None:
    """⚠️ GUARD, PER CLIMBER and no longer pooled, and the whole closing sentence rather than
    half of it. `PHASE_GUIDE` is rendered to every climber on two screens
    (`web/src/routes/_authed/plan.lazy.tsx`, `web/src/session/SessionBrief.tsx`), so a claim it
    makes is a per-profile claim and a sweep pooled over 24 plans can read green while the
    sentence is false for a real one. `_climber_aspect_seconds` exists for this granularity.

    ⚠️ ONE DENOMINATOR, chosen and not averaged: the sentence's own words are "these weeks' time
    on the wall", so it is measured on WALL minutes. The all-minutes tail ceiling in
    `test_planner_climbing_floor.py` is a stricter test constant over a different denominator,
    not a second reading of this sentence — which is why the two numbers never agreed.

    The sentence carries THREE executable claims, all asserted: endurance takes the most wall
    time, general strength and anaerobic capacity both START here, and power sits last.
    """
    for phase, (last, ahead) in COPY_CLAIMS_LAST.items():
        for climber in _WEAKNESS_SWEEP:
            wall = _climber_wall_seconds(climber, phase)
            total = sum(wall.values())
            assert total, f"no {phase.value} wall minutes for {climber}; parametrisation wrong."
            assert all(wall[last] < wall[key] for key in ahead), (
                f"PHASE_GUIDE[{phase.value}] says {last} sits last on purpose, but for a "
                f"{climber.grade} {climber.discipline.value} climber training "
                f"{climber.sessions}x a week with weakness={climber.weakness} it takes "
                f"{100 * wall[last] / total:.1f}% of the block's wall minutes against "
                f"{[(key, f'{100 * wall[key] / total:.1f}%') for key in ahead]}."
            )
            assert all(wall[COPY_CLAIMS_BASE_LEAD] >= wall[key] for key in wall), (
                f"PHASE_GUIDE[{phase.value}] says {COPY_CLAIMS_BASE_LEAD} takes more of these "
                f"weeks' time on the wall than any other quality, but a {climber.grade} "
                f"{climber.discipline.value} climber at {climber.sessions}x with "
                f"weakness={climber.weakness} gets {wall.most_common(3)}."
            )
    for climber in _WEAKNESS_SWEEP:
        started = _climber_aspect_seconds(climber, Phase.BASE)
        absent = [aspect for aspect in COPY_CLAIMS_BASE_START if not started[aspect]]
        assert not absent, (
            f"PHASE_GUIDE[base] says {' and '.join(COPY_CLAIMS_BASE_START)} both START here, "
            f"but a {climber.grade} {climber.discipline.value} climber at {climber.sessions}x "
            f"gets no {absent} in a base block at all. ⚠️ Measured on ALL base minutes, not wall "
            f"minutes: since the three on-wall general strength rows were re-filed to `power` "
            f"there is no on-wall general strength exercise in any phase, so a wall-only "
            f"reading of this claim would be vacuous."
        )


def test_a_DECLARED_WEAKNESS_LEAVES_the_base_blocks_general_strength_A_TURN() -> None:
    """⚠️ GUARD, re-pointed from the defect it registered: 23 starved profiles of 24 at both
    weakness values, now none. Slot 1 is `general_strength`'s only route into a plan, so a
    weakness that took the slot in every session deleted the quality rather than outranking it.

    ⚠️ WHY `WEAKNESS_YIELDS_SLOT_ONE_EVERY` IS 3, measured here at both weakness values. A base
    block is three weeks, so a 2x-a-week climber's `week_no - 1 + session_index` runs 0-3: N=2
    yields three of those six sessions, N=3 yields two, and every N of 4 or more yields exactly
    ONCE in the whole block — one session between the published claim and nothing. 4 buys
    nothing for that risk (worst-case plan-wide weakness multiplier 1.14x at both 3 and 4,
    against 1.26x unyielded) and 2 costs the most of the bias, 1.08x. At 3 the multiplier runs
    1.14x-2.67x where unyielded ran 1.26x-3.42x, and general strength holds 1.0-4.1% of a base
    block on every profile.
    """
    for weakness in ("power", "power_endurance"):
        starved = sorted(
            f"{climber.grade} {climber.discipline.value} {climber.sessions}x"
            for climber in _SWEEP
            if not _climber_aspect_seconds(replace(climber, weakness=weakness), Phase.BASE)[
                "general_strength"
            ]
        )
        assert not starved, (
            f"declaring {weakness} a weakness leaves {len(starved)} of {len(_SWEEP)} profiles "
            f"with no general strength in a base block, where ruling 21 left "
            f"0 and the defect it replaced left "
            f"{_WEAKNESS_STARVED_BASE_PROFILES_BEFORE_RULING_21}: {starved}. "
            f"{_A_WEAKNESS_YIELDS_SLOT_ONE}"
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
