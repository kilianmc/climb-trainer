"""`generate()` — a `PlannerInput` in, a whole `PlanBlueprint` out, and nothing else.

Pure: no DB, no clock, no RNG, no I/O. Every varying quantity is a function of
`(week_no, session_index)`, which is the promise `server/models.py::Plan` makes and the reason
`generator_input` folds `library_digest()` in beside the version.

Five invariants, in priority order. (1) **Nothing non-deterministic reaches the output** — no
`random`, no `secrets`, no `hash()`, no set iteration; `server/domain/.ruff.toml` bans the
imports and `tests/test_planner_reproducibility.py` is the check. (2) **A contraindicated
exercise is never prescribed** — `prescribable()` never relaxes the injury filter, which is why
(5) exists. (3) **Climbing is allocated before anything else** — wall blocks in a first pass over
the week, supplementary work in a second and only while the week still meets its level's climbing
floor, so accessory work cannot crowd it out (issue #84). (4) **Never an *unexplained* empty
session** — an unfillable slot is displaced to the next aspect in `ASPECT_EMPHASIS`, carrying a
`Shortfall` naming what would open the original. (5) The one honest exception: nothing available
and every injury area open leaves no aspect in `power_endurance` or `performance`, so the session
becomes `activity_kind=other`, "Recovery", with a shortfall per empty slot. Explained, allowed.

⚠️ Every string built here is user facing and two hard rules bind all of them: **never suggest
losing weight** (there is no bodyweight figure in this module, which is also why
`target_load_kg` stays `None`) and **never suggest improvising finger loading** (a shortfall
names equipment rows; `substitution_hint` is deliberately not read here).
`tests/test_planner_safety.py` asserts both against every string a plan can produce.

`estimated_minutes` is arithmetic, not a guess: prescribed seconds over 60, ceiled, plus
`WARMUP_MINUTES` — not a block, because a block would make warming up skippable.
"""

import math
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Final, Literal

from server.domain.exercises import ExerciseSpec, PrescriptionSpec
from server.domain.planner.blueprint import (
    BlockBlueprint,
    MesocycleBlueprint,
    MicrocycleBlueprint,
    PlanBlueprint,
    ScheduleNote,
    SessionBlueprint,
    SetBlueprint,
    Shortfall,
)
from server.domain.planner.climbing import (
    ANAEROBIC_ASPECT,
    DELOAD_LEAD_ASPECTS,
    ENERGY_SYSTEM_ASPECTS,
    FINGER_ASPECT,
    FINGER_PROTOCOLS,
    INTENSITY_TIERS,
    LENGTH_FILL_MINUTES,
    MAX_EXPANSION_FACTOR,
    UNLOADING_PHASES,
    WALL_LED_ASPECTS,
    anaerobic_sessions_ceiling,
    climbing_block_budget,
    climbing_target_band,
    content_protocols_for,
    finger_sessions_for,
    hard_energy_day_ceiling,
    intensity_tier,
    is_expandable,
    is_priority,
    meets_floor,
    requires_wall,
    session_floor_pct,
    session_minutes_target,
    session_window_across,
    week_ceiling_governs,
    week_climbing_floor_pct,
)
from server.domain.planner.contract import PlannerInput
from server.domain.planner.periodisation import (
    beyond_one_plan_note,
    block_count_for,
    mesocycle_spans,
    week_count_for,
)
from server.domain.planner.progression import progressed
from server.domain.planner.schedule import (
    DAYS_PER_WEEK,
    choose_weekdays,
    fewer_sessions_note,
    microcycle_start,
    session_date,
)
from server.domain.planner.selection import (
    ASPECT_EMPHASIS,
    ASPECT_NAMES,
    BLOCKS_PER_SESSION,
    SUPPORT_ASPECTS,
    WEAKNESS_YIELDS_SLOT_ONE_EVERY,
    candidates,
    no_climbing_message,
    off_the_wall,
    on_the_wall,
    open_climbing_fill,
    ordinary,
    prescribable,
    shortfall_message,
    unlock_options,
    wall_aspect_turns,
    wall_led_aspects,
    wall_unlock_options,
    with_protocols,
)
from server.domain.vocabulary import ActivityKind, Phase, ProtocolKind

# Three blocks, two more ONLY to reach the type's window floor, and ruling 27's ONE length-fill
# block on top of both — never extra prescription, which is what `MAX_EXPANSION_FACTOR` stops.
MAX_BLOCKS_PER_SESSION: Final = BLOCKS_PER_SESSION + 2

# Flat, every session, every level (Kilian, 2026-09-05 — ruling 26; was 15). Inside his stated
# 10-30 range. ⚠️ DECLARED DIVERGENCE, not a fixed defect: at ruling 25's 90-minute beginner
# session this is 22% of the session against Dylan's 5-10% budget, falling to 13% at 150 min.
# Per-session-type warm-up was considered and refused — it reads a session's type, which ruling 3
# put off-limits. It sits OUTSIDE `_Draft.seconds` because it is not a block: `_session_floor`
# subtracts it from ruling 25's target instead, and it is excluded from every unload ratio.
WARMUP_MINUTES: Final = 20
SECONDS_PER_REP: Final = 4

_RECOVERY_TITLE: Final = "Recovery"

# `planned_session.title` is `String(80)` and the domain may not import the model, so the width
# is mirrored here; `tests/test_planner_safety.py` pins the two together.
TITLE_MAX_CHARS: Final = 80

# How much more climbing a session can take, in the order it wants a slot's candidates offered.
WallPref = Literal["never", "last", "first"]


@dataclass(slots=True)
class _Draft:
    """One session mid-allocation. Mutable, week-local, and never leaves this module."""

    weekday: int
    session_index: int
    # Ruling 25's per-level session length, warm-up already subtracted. Required rather than
    # defaulted: a zero here silently restores the protocol-window-only length it replaces.
    level_target_seconds: int
    blocks: list[BlockBlueprint] = field(default_factory=list)
    used: list[str] = field(default_factory=list)
    shortfalls: list[Shortfall] = field(default_factory=list)
    wall_seconds: int = 0
    climbing_blocks: int = 0
    supplementary: int = 0
    supplementary_used: list[str] = field(default_factory=list)

    @property
    def seconds(self) -> int:
        """Prescribed seconds in the session so far, warm-up excluded — it is not a block."""
        return sum(_block_seconds(block) for block in self.blocks)

    @property
    def other_seconds(self) -> int:
        """Prescribed seconds that are not climbing — the half the band reserves."""
        return self.seconds - self.wall_seconds


def generate(planner_input: PlannerInput) -> PlanBlueprint:
    """Build the whole plan. Raises `CannotPlanError` only for an empty weekday mask."""
    gap = planner_input.grade_gap
    week_count = week_count_for(gap)
    weekdays = choose_weekdays(planner_input.available_weekdays, planner_input.sessions_per_week)

    mesocycles = tuple(
        MesocycleBlueprint(
            phase=span.phase,
            start_week=span.start_week,
            end_week=span.end_week,
            microcycles=tuple(
                _microcycle(planner_input, span.phase, week_no, weekdays)
                for week_no in range(span.start_week, span.end_week + 1)
            ),
        )
        for span in mesocycle_spans(block_count_for(gap))
    )

    return PlanBlueprint(
        name=f"{week_count}-week {planner_input.discipline.value} plan",
        discipline=planner_input.discipline,
        target_grade_id=None,
        current_grade_id=None,
        start_date=planner_input.start_date,
        week_count=week_count,
        grade_gap=gap,
        mesocycles=mesocycles,
        shortfalls=_rolled_up(mesocycles),
        notes=_notes(planner_input, scheduled=len(weekdays), gap=gap),
    )


def _notes(planner_input: PlannerInput, *, scheduled: int, gap: int) -> tuple[ScheduleNote, ...]:
    """Everything the plan says about itself. Never a gate — the plan is complete either way."""
    possible = (
        fewer_sessions_note(requested=planner_input.sessions_per_week, scheduled=scheduled),
        beyond_one_plan_note(gap),
    )
    return tuple(note for note in possible if note is not None)


def _microcycle(
    planner_input: PlannerInput, phase: Phase, week_no: int, weekdays: tuple[int, ...]
) -> MicrocycleBlueprint:
    """One week, climbing-first and to the band's TARGET rather than to exhaustion, so the
    remainder is genuinely left for the supplementary work the band reserves it for."""
    week_start = microcycle_start(planner_input.start_date, week_no)
    level_target_seconds = (
        session_minutes_target(planner_input.discipline, planner_input.current_ordinal)
        - WARMUP_MINUTES
    ) * 60
    drafts = [
        _Draft(weekday=weekday, session_index=index, level_target_seconds=level_target_seconds)
        for index, weekday in enumerate(weekdays)
    ]
    # A one-session week is climbing and nothing else, so it aims at 100% (issue #84).
    solo = len(drafts) == 1
    # Both edges of the band do work: climbing fills to the TOP and supplementary is allowed
    # back down to the BOTTOM. At one target the two constraints meet exactly and rounding loses.
    low_pct, high_pct = (
        (100, 100)
        if solo
        else climbing_target_band(planner_input.discipline, planner_input.current_ordinal)
    )
    budget = (
        BLOCKS_PER_SESSION
        if solo
        else climbing_block_budget(planner_input.discipline, planner_input.current_ordinal)
    )
    for draft in drafts:
        _fill_climbing(
            drafts,
            draft,
            planner_input,
            phase,
            week_no,
            fill_pct=high_pct,
            floor_pct=low_pct,
            budget=budget,
        )
    if not solo:
        _fill_finger_strength(drafts, planner_input, phase, week_no, band=(low_pct, high_pct))
    _fill_supplementary(drafts, planner_input, phase, week_no, band=(low_pct, high_pct))
    _fill_session_length(drafts, planner_input, phase, week_no)
    _descend_by_intensity(drafts)
    return MicrocycleBlueprint(
        week_no=week_no,
        start_date=week_start,
        is_deload=phase is Phase.DELOAD,
        phase=phase,
        sessions=tuple(
            _session(draft, week_start, phase)
            for draft in sorted(drafts, key=lambda draft: draft.weekday)
        ),
    )


def _day_intensity(draft: _Draft) -> int:
    """How hard the DAY is: its hardest block on §3.4's chain, because the source's second half
    is about the day. A block-less Recovery session sinks to the end of its run."""
    tiers = (intensity_tier(block.aspect_key) for block in draft.blocks)
    return min(tiers, default=len(INTENSITY_TIERS))


def _descend_by_intensity(drafts: list[_Draft]) -> None:
    """§3.4 across the week: inside a run of BACK-TO-BACK training days the harder day comes
    first. A week with no such run — Mon/Wed/Fri — is left exactly as it was, content included.

    ⚠️ This reassigns `weekday` VALUES and must never reorder `drafts` or renumber
    `session_index`, which keys `_spread`, every candidate pool and `_intended_aspect`'s
    rotation; re-keying it is the monotonicity regression `_spread`'s own docstring records.
    A run never wraps Sunday to Monday: the next Monday is a different microcycle, possibly a
    different phase, which is why this only walks forward through one week's ascending days.
    """
    start = 0
    for index in range(1, len(drafts) + 1):
        if index < len(drafts) and drafts[index].weekday == drafts[index - 1].weekday + 1:
            continue
        run = drafts[start:index]
        slots = [draft.weekday for draft in run]
        for draft, weekday in zip(sorted(run, key=_day_intensity), slots, strict=True):
            draft.weekday = weekday
        start = index


def _hard_energy_days(drafts: list[_Draft]) -> int:
    """Sessions of this week that already carry hard energy-system work — An Cap, An Pow or
    Aero Pow. A day COUNTS by containing such a block, never by what its slot-1 aspect is."""
    return sum(1 for draft in drafts if _carries_energy_system(draft))


def _carries_energy_system(draft: _Draft) -> bool:
    """Whether this session already holds a hard energy-system block."""
    return any(block.aspect_key in ENERGY_SYSTEM_ASPECTS for block in draft.blocks)


def _holds(draft: _Draft, aspect_key: str) -> bool:
    """Whether this session already holds a block of one aspect."""
    return any(block.aspect_key == aspect_key for block in draft.blocks)


def _week_ceiling_allows(
    drafts: list[_Draft], draft: _Draft, aspect_key: str, phase: Phase
) -> bool:
    """Barrows' two WEEKLY frequency ceilings, as one predicate every placement pass consults.

    ⚠️ Read off `drafts` rather than off a counter, so it binds all three passes that can place
    a hard block — the rotated wall ring in `_fill_climbing`, `_length_pick`'s top-up and the
    supplementary fill — and cannot drift out of step with what the week actually holds. A block
    landing in a session that ALREADY carries the quality changes no weekly count, so it passes:
    the ceilings count sessions and days, never blocks.
    """
    if not week_ceiling_governs(aspect_key):
        return True
    if aspect_key == ANAEROBIC_ASPECT and not _holds(draft, ANAEROBIC_ASPECT):
        already = sum(1 for other in drafts if _holds(other, ANAEROBIC_ASPECT))
        if already >= anaerobic_sessions_ceiling(phase):
            return False
    ceiling = hard_energy_day_ceiling(phase)
    if ceiling is None or _carries_energy_system(draft):
        return True
    return _hard_energy_days(drafts) < ceiling


def _fill_climbing(
    drafts: list[_Draft],
    draft: _Draft,
    planner_input: PlannerInput,
    phase: Phase,
    week_no: int,
    *,
    fill_pct: int,
    floor_pct: int,
    budget: int,
) -> None:
    """Wall blocks up to the band's share of the session type's window floor and no further — to
    a TARGET, never to exhaustion, so the remainder is reserved for supplementary work."""
    spread = _spread(week_no, draft.session_index)
    refused = False
    for spec in _wall_picks(planner_input, phase, spread):
        if len(draft.blocks) >= BLOCKS_PER_SESSION:
            break
        if not _week_ceiling_allows(drafts, draft, spec.aspect_key, phase):
            # A day the week's ceiling takes hard work OFF spends its whole climbing allowance
            # instead: ruling 9 removes hard WORK and ruling 4 forbids removing CLIMBING, so an
            # easy day is still a climbing day and takes a full session's worth of wall blocks.
            refused = True
            continue
        spent = draft.seconds >= _share_of_window_floor(draft, None, fill_pct, phase) or len(
            draft.blocks
        ) >= (BLOCKS_PER_SESSION if refused else budget)
        if (
            draft.blocks
            and spent
            and draft.seconds >= _share_of_window_floor(draft, None, floor_pct, phase)
        ):
            break
        # Both thresholds are read off the session this block WOULD make, never off the first
        # block placed: a priority block landing second moves the whole session's window.
        target_seconds = _share_of_window_floor(draft, spec, fill_pct, phase)
        needed_seconds = _share_of_window_floor(draft, spec, floor_pct, phase)
        if draft.blocks and (
            not _fits(draft, spec, phase, week_no)
            or not (
                draft.seconds < needed_seconds
                or _nearer_target(draft, spec, phase, week_no, target_seconds=target_seconds)
            )
        ):
            continue
        _place(
            draft,
            spec,
            phase=phase,
            week_no=week_no,
            target_seconds=target_seconds,
            climbing=True,
        )
    if not draft.blocks:
        draft.shortfalls.append(_no_climbing_shortfall(planner_input, phase))


def _wall_picks(planner_input: PlannerInput, phase: Phase, spread: int) -> tuple[ExerciseSpec, ...]:
    """This session's wall exercises, best first: the phase's ring of aspect turns, started at
    its own offset, a fresh exercise per turn — so `ASPECT_EMPHASIS` governs climbing and not
    only the supplementary pass, and a `strength` block keeps the second bite that measured ten
    minutes short without it. Indexed by `_spread` for the reason recorded there.

    ⚠️ **"Rank-weighted" is what this said, and F11 measured it FALSE in the phases where
    `MAX_WALL_TURNS` binds** — `strength` and `taper` are flat rings, 21 of 30 phase/aspect
    pairs sit on the cap, and `wall_aspect_turns`' docstring carries the seven readings that
    were measured to lift it and the shipped ruling each one breaks. The ring is rank-weighted
    only in its TAIL, and only in the five phases with a tail.
    ⚠️ The offset matters as much as the weights and is the fact that decided F11: a 2-session
    week's `spread` takes six values, so it visits **6 of a 16-long ring's rotations**. Which
    qualities such a week gets at all is which aspects sit at those six positions.
    """
    pools = {
        aspect_key: ordered
        for aspect_key in wall_led_aspects(phase)
        if (
            ordered := prescribable(
                on_the_wall(ordinary(candidates(phase, aspect_key))),
                discipline=planner_input.discipline,
                equipment_keys=planner_input.equipment_keys,
                open_injury_keys=planner_input.open_injury_keys,
            )
        )
    }
    picked: list[ExerciseSpec] = []
    seen: list[str] = []
    taken: dict[str, int] = {}
    for aspect_key in _rotated_pool(wall_aspect_turns(phase), spread):
        pool = pools.get(aspect_key)
        if pool is None:
            continue
        depth = taken.get(aspect_key, 0)
        taken[aspect_key] = depth + 1
        spec = pool[_pool_index(spread, len(pool), depth)]
        if spec.key not in seen:
            seen.append(spec.key)
            picked.append(spec)
    return tuple(picked)


def _fill_finger_strength(
    drafts: list[_Draft],
    planner_input: PlannerInput,
    phase: Phase,
    week_no: int,
    *,
    band: tuple[int, int],
) -> None:
    """The band's hangboard floor. Finger strength is the strongest single predictor of climbing
    performance and matters MORE as level rises, so it is prescribed, not left to a spare slot."""
    wanted = finger_sessions_for(planner_input.discipline, planner_input.current_ordinal, phase)
    ordered = prescribable(
        with_protocols(candidates(phase, FINGER_ASPECT), FINGER_PROTOCOLS),
        discipline=planner_input.discipline,
        equipment_keys=planner_input.equipment_keys,
        open_injury_keys=planner_input.open_injury_keys,
    )
    if wanted <= 0 or not ordered:
        return
    floor_pct = week_climbing_floor_pct(
        planner_input.discipline, planner_input.current_ordinal, phase
    )
    wall_seconds = sum(draft.wall_seconds for draft in drafts)
    other_seconds = sum(draft.other_seconds for draft in drafts)
    placed = 0
    for step in range(len(drafts)):
        if placed >= wanted:
            return
        draft = drafts[(week_no - 1 + step) % len(drafts)]
        if FINGER_ASPECT in draft.used or len(draft.blocks) >= _block_ceiling(
            draft, phase, band=band, week=(wall_seconds, other_seconds)
        ):
            continue
        # Every authored protocol is tried, because a hang has to fit inside its OWN window: a
        # long endurance day cannot become a hangboard session, which is the point, not a gap.
        for turn in range(len(ordered)):
            spec = ordered[(week_no - 1 + placed + turn) % len(ordered)]
            added = _spec_seconds(spec, phase, week_no)
            if not _fits(draft, spec, phase, week_no) or not meets_floor(
                wall_seconds=wall_seconds, other_seconds=other_seconds + added, floor_pct=floor_pct
            ):
                continue
            _place(draft, spec, phase=phase, week_no=week_no, target_seconds=0, climbing=False)
            draft.supplementary_used.append(spec.aspect_key)
            other_seconds += added
            placed += 1
            break


def _window_rank(aspect_key: str, protocol_kind: ProtocolKind, index: int) -> tuple[int, int, int]:
    """Quality first, then §3.4's intensity chain, then placement: `_ordered_blocks`' own rank
    without its DELOAD key, which moves what LEADS and never what sets the window."""
    return (0 if is_priority(protocol_kind) else 1, _session_tier(aspect_key), index)


def _session_tier(aspect_key: str) -> int:
    """§3.4's tier, except that an aspect outside `WALL_LED_ASPECTS` may not NAME a session, so
    it neither leads one nor sets its window — `WALL_LED_ASPECTS`' own comment is where that
    distinction already lives. Measured: promoting one, a gearless base session led by a
    `hold` finger isometric took HOLD's 45-minute ceiling against 43 minutes already placed and
    came back two blocks thin. Hard finger work still leads, by `PRIORITY_PROTOCOLS`."""
    return intensity_tier(aspect_key) if aspect_key in WALL_LED_ASPECTS else len(INTENSITY_TIERS)


def _kinds(draft: _Draft, spec: ExerciseSpec | None = None) -> list[ProtocolKind]:
    """The protocol kinds this session would carry, in the order `_ordered_blocks` emits them."""
    rows = [(block.aspect_key, block.protocol_kind) for block in draft.blocks]
    if spec is not None:
        rows.append((spec.aspect_key, spec.protocol_kind))
    order = sorted(
        range(len(rows)), key=lambda index: _window_rank(rows[index][0], rows[index][1], index)
    )
    return [rows[index][1] for index in order]


def _session_ceiling(draft: _Draft, spec: ExerciseSpec | None = None) -> int:
    """The seconds a session may not exceed: the widest ceiling any of its blocks brings, or its
    level's target length if that is longer. Ruling 3 forbids LOWERING a window and every term
    here only raises one — the leading block's ceiling was 45 minutes on a max-hang session, so
    no advanced session could reach the 150 ruling 25 asks for however many blocks it spent."""
    return max(
        session_window_across(_kinds(draft, spec))[1] * 60,
        draft.level_target_seconds,
    )


def _fits(draft: _Draft, spec: ExerciseSpec, phase: Phase, week_no: int) -> bool:
    """Whether this block fits under the ceiling of the session type it would produce."""
    return draft.seconds + _spec_seconds(spec, phase, week_no) <= _session_ceiling(draft, spec)


def _window_floor(draft: _Draft, phase: Phase) -> int:
    """Ruling 3's floor: the seconds the PROTOCOLS in this session owe, and the only one topped
    up with ordinary climbing. Zero before the session has a type."""
    if not draft.blocks:
        return 0
    return session_window_across(_kinds(draft))[0] * 60 * session_floor_pct(phase) // 100


def _session_floor(draft: _Draft, phase: Phase) -> int:
    """The seconds a session owes: ruling 25's length for its level scaled by its PHASE's volume
    factor, or its protocols' window floor where that is longer. Zero before it has a type.
    ⚠️ `_fill_session_length` reads this and nothing else does. Wiring it into the discretionary
    passes instead put every band 30 points over its target range, left `_fill_finger_strength`
    no session with a free slot, and made twelve off-the-wall library rows unreachable."""
    if not draft.blocks:
        return 0
    return max(
        _window_floor(draft, phase), draft.level_target_seconds * session_floor_pct(phase) // 100
    )


def _short_of_its_window(draft: _Draft, phase: Phase) -> bool:
    """Whether this session is still under the share of its own type's PROTOCOL window floor its
    phase owes — all of it while loading, half of it in an unload week (Kilian, 2026-09-04)."""
    return draft.seconds < _window_floor(draft, phase)


def _block_ceiling(
    draft: _Draft, phase: Phase, *, band: tuple[int, int], week: tuple[int, int]
) -> int:
    """Three blocks, and more only where a session needs them: to reach its own type's window
    floor, or to bring it back inside the top edge of its band. Neither is a fixed budget —
    three chunky wall blocks leave a limit-bouldering session ten minutes short of its floor,
    and with two sessions a week there is nowhere else to put the supplementary work.
    ⚠️ Both are read off the SESSION, never off the week. A week aggregate makes an existing
    session's budget depend on how many OTHER sessions the week has, and the measured cost was
    the monotonicity invariant: 5 sessions to 6 dropped a deload week's climbing by 10.5 min
    (intermediate boulder, week 8). The band's non-climbing allowance is proportional to wall
    time and therefore additive, so the per-session test sums to the week the band is stated
    over.
    ⚠️ Ruling 32's THIRD condition — "the week's hangboard floor is owed" — was written and
    measured BYTE-IDENTICAL over 1176 weeks, because a session that owes a hang carries no
    off-the-wall work yet and the band arm above already admits it. What ruling 32 needed was
    `_fill_finger_strength` READING this ceiling instead of restating three. Do not add it back."""
    del week
    if _short_of_its_window(draft, phase) or meets_floor(
        wall_seconds=draft.wall_seconds, other_seconds=draft.other_seconds, floor_pct=band[1]
    ):
        return MAX_BLOCKS_PER_SESSION
    return BLOCKS_PER_SESSION


def _ordered_blocks(blocks: list[BlockBlueprint], phase: Phase) -> tuple[BlockBlueprint, ...]:
    """Hardest first on §3.4's chain, and a fixed-volume protocol never behind volume work —
    except in a DELOAD, where `DELOAD_LEAD_ASPECTS` leads, because low load is the week's point."""
    lead_first = phase is Phase.DELOAD

    def rank(index: int) -> tuple[int, int, int, int]:
        block = blocks[index]
        quality, tier, placement = _window_rank(block.aspect_key, block.protocol_kind, index)
        return (
            0 if lead_first and block.aspect_key in DELOAD_LEAD_ASPECTS else 1,
            quality,
            tier,
            placement,
        )

    order = sorted(range(len(blocks)), key=rank)
    return tuple(replace(blocks[old], order_index=new) for new, old in enumerate(order, start=1))


def _fill_supplementary(
    drafts: list[_Draft],
    planner_input: PlannerInput,
    phase: Phase,
    week_no: int,
    *,
    band: tuple[int, int],
) -> None:
    """Supplementary blocks, breadth-first across the week, gated by the hard climbing floor and
    by the band's target share. A one-session week is climbing only, so it never gets here."""
    if len(drafts) == 1 and drafts[0].blocks:
        # A solo week has no supplementary pass at all, and still owes its type's length.
        _top_up_with_climbing(drafts, planner_input, phase, week_no, band=band)
        return
    floor_pct = week_climbing_floor_pct(
        planner_input.discipline, planner_input.current_ordinal, phase
    )
    # LENGTH FIRST. The hard floor caps a week's supplementary minutes, so a discretionary block
    # placed early spends what a session under its type's window floor needs.
    _supplementary_rounds(
        drafts,
        planner_input,
        phase,
        week_no,
        band=band,
        floor_pct=floor_pct,
        short_only=True,
        cap=BLOCKS_PER_SESSION,
    )
    _top_up_with_climbing(drafts, planner_input, phase, week_no, band=band)
    _supplementary_rounds(
        drafts,
        planner_input,
        phase,
        week_no,
        band=band,
        floor_pct=floor_pct,
        short_only=False,
        cap=MAX_BLOCKS_PER_SESSION,
    )


def _supplementary_rounds(
    drafts: list[_Draft],
    planner_input: PlannerInput,
    phase: Phase,
    week_no: int,
    *,
    band: tuple[int, int],
    floor_pct: int,
    short_only: bool,
    cap: int,
) -> None:
    """One sweep of supplementary attempts, breadth-first, one block per draft per round.

    `cap` is what reserves the two spare blocks for `_top_up_with_climbing`: the length-first
    sweep runs to three, so a session that needs a fourth block for its length gets climbing in
    it rather than the accessory the aspect rotation offered (which is what the constant's own
    comment has always said those two blocks are for).
    """
    for _round in range(MAX_BLOCKS_PER_SESSION):
        for draft in drafts:
            week = (
                sum(other.wall_seconds for other in drafts),
                sum(other.other_seconds for other in drafts),
            )
            if short_only and not _short_of_its_window(draft, phase):
                continue
            if len(draft.blocks) >= min(cap, _block_ceiling(draft, phase, band=band, week=week)):
                continue
            _try_supplementary(
                drafts,
                draft,
                planner_input,
                phase,
                week_no,
                band=band,
                floor_pct=floor_pct,
                wall_seconds=week[0],
                other_seconds=week[1],
            )


def _top_up_with_climbing(
    drafts: list[_Draft],
    planner_input: PlannerInput,
    phase: Phase,
    week_no: int,
    *,
    band: tuple[int, int],
) -> None:
    """A session still under its own type's window floor is topped up with ORDINARY CLIMBING,
    and with nothing else (Kilian, 2026-09-04): length belongs to the type, and the seconds that
    buy it come off the wall rather than out of whatever accessory the aspect rotation happened
    to offer. Runs before the discretionary rounds, so the two spare blocks
    `MAX_BLOCKS_PER_SESSION` reserves for exactly this are still there to spend — a 9-minute
    alactic interval block led five-block sessions that stopped 3-7 minutes short of a 40-minute
    floor because blocks four and five had gone to a 2.7-minute accessory (measured, beginner
    boulder, week 17). Reads only its own draft, so a week's session count cannot change it.
    """
    for draft in drafts:
        for _round in range(MAX_BLOCKS_PER_SESSION):
            if len(draft.blocks) >= MAX_BLOCKS_PER_SESSION or not _short_of_its_window(
                draft, phase
            ):
                break
            spec = _length_pick(
                drafts,
                draft,
                planner_input,
                phase,
                spread=_spread(week_no, draft.session_index),
                week_no=week_no,
                band=band,
            )
            if spec is None:
                break
            _place(draft, spec, phase=phase, week_no=week_no, target_seconds=0, climbing=True)


def _fill_session_length(
    drafts: list[_Draft], planner_input: PlannerInput, phase: Phase, week_no: int
) -> None:
    """Ruling 27: a session short of ruling 25's length takes ONE block of ordinary climbing,
    sized to the gap and never shorter than `LENGTH_FILL_MINUTES`.

    Runs LAST, after the hangboard floor and every supplementary round, so it can never take a
    slot a floor is owed — the failure that returned ruling 15's finger loss when the length was
    chased earlier. One block, which is why neither `MAX_BLOCKS_PER_SESSION` nor the library's
    doses had to rise to reach the target. A session with no blocks is a Recovery day and stays
    one, and a session already at its length is left alone rather than padded.
    """
    for draft in drafts:
        gap = _session_floor(draft, phase) - draft.seconds
        if gap <= 0:
            continue
        spec = _length_pick(
            drafts,
            draft,
            planner_input,
            phase,
            spread=_spread(week_no, draft.session_index),
            week_no=week_no,
            band=None,
        )
        if spec is None:
            continue
        _place(
            draft,
            spec,
            phase=phase,
            week_no=week_no,
            target_seconds=0,
            climbing=True,
            fill_seconds=max(gap, LENGTH_FILL_MINUTES * 60),
        )


def _band_top_allows(draft: _Draft, added: int, band: tuple[int, int]) -> bool:
    """Whether one more WALL block keeps this session at or under its band's top share.
    Two exemptions, both measured: a session under ruling 3's window floor is topped up on the
    wall whatever the band says (that floor is the one the band never overrides), and a SOLO
    week's band is 100/100, so gating it would leave a one-session week at its window floor and
    cost ruling 4 the climbing a second day is supposed to add."""
    if band[1] >= 100:
        return True
    wall = draft.wall_seconds + added
    return wall * 100 <= band[1] * (wall + draft.other_seconds)


def _length_pick(
    drafts: list[_Draft],
    draft: _Draft,
    planner_input: PlannerInput,
    phase: Phase,
    *,
    spread: int,
    week_no: int,
    band: tuple[int, int] | None,
) -> ExerciseSpec | None:
    """The on-wall block that closes the gap, from the qualities the phase leads on a wall.

    ⚠️ `band=None` is ruling 27's length fill, and it is a different question answered by a
    different pool: ruling 29's filler family, one authored row per intention, so the fill
    FILTERS where it used to rank the whole wall library. The band does not gate it (that
    ceiling is what the ruling spends), the authored length cannot rank it, and neither can the
    session ceiling, because a gap wider than any window is the whole point.

    Rotation among the candidates that close the gap, then the longest that fits — `_pick`'s
    rule, for `_pick`'s reason: padding with sets is what `MAX_EXPANSION_FACTOR` forbids, and
    the shortest sufficient block measured worse on per-plan breadth on every profile.
    ⚠️ `wall_led_aspects()` and not every aspect with an on-wall candidate. A top-up is
    ordinary climbing, and this set is exactly the qualities a session may be ABOUT; widening it
    to the wall core and prehab drills bought a beginner plan four exercises of breadth and cost
    the advanced band 2.6 points, breaching its 62% ceiling at 63.2% (gap 0, 2 sessions).
    ⚠️ A PRIORITY protocol is excluded. That work has to LEAD its session rather than sit
    behind volume, and appending one would re-type the session and move the floor being chased.
    """
    if band is None:
        # Ruling 29 made this a FILTER. The filler family is ordered by the phase's own
        # `ASPECT_EMPHASIS`, so the first row a week can still take is the one attributed to the
        # quality the block is most named after — ruling 30's cue and its no-out-training
        # invariant are the same single choice. The ceilings still bind: a day ruling 9 has made
        # easy walks on to the next row rather than being handed the block's hard quality again.
        for spec in prescribable(
            open_climbing_fill(phase),
            discipline=planner_input.discipline,
            equipment_keys=planner_input.equipment_keys,
            open_injury_keys=planner_input.open_injury_keys,
        ):
            if _week_ceiling_allows(drafts, draft, spec.aspect_key, phase):
                return spec
        return None
    seen = [block.exercise_key for block in draft.blocks]

    def offered(aspects: tuple[str, ...]) -> list[ExerciseSpec]:
        return [
            spec
            for aspect_key in aspects
            for spec in prescribable(
                on_the_wall(ordinary(candidates(phase, aspect_key))),
                discipline=planner_input.discipline,
                equipment_keys=planner_input.equipment_keys,
                open_injury_keys=planner_input.open_injury_keys,
            )
            if spec.key not in seen
            and not is_priority(spec.protocol_kind)
            and _fits(draft, spec, phase, week_no)
            and _week_ceiling_allows(drafts, draft, spec.aspect_key, phase)
            and (
                draft.seconds < _window_floor(draft, phase)
                or _band_top_allows(draft, _spec_seconds(spec, phase, week_no), band)
            )
        ]

    pool = offered(wall_led_aspects(phase))
    if not pool:
        return None
    need = _session_floor(draft, phase) - draft.seconds
    enough = [spec for spec in pool if _spec_seconds(spec, phase, week_no) >= need]
    if enough:
        return enough[_pool_index(spread, len(enough))]
    return max(pool, key=lambda spec: _spec_seconds(spec, phase, week_no))


def _try_supplementary(
    drafts: list[_Draft],
    draft: _Draft,
    planner_input: PlannerInput,
    phase: Phase,
    week_no: int,
    *,
    band: tuple[int, int],
    floor_pct: int,
    wall_seconds: int,
    other_seconds: int,
) -> None:
    """Add one supplementary block if the window and the floor allow. A floor rejection is a
    decision, not a limitation, so it carries no shortfall; only an unfillable slot does.

    ⚠️ The ledger it reads is `supplementary_used`, NOT every aspect in the session: an aspect
    the climbing pass took on a wall may still host one off-the-wall block, because a wall
    exercise and a gym exercise for the same quality are different training. Reading `used`
    here made every off-the-wall `power`, `endurance` and `power_endurance` exercise in the
    library structurally unreachable — six exercises no plan could prescribe.
    """
    # The week's ceilings bind by REMOVING the refused aspect from this draft's emphasis row,
    # rather than by rejecting the block afterwards: a slot that walked past `intended` carries
    # a `Shortfall` naming the equipment that would open it, and an overtraining ceiling is not
    # a gap in the climber's gym. The row cannot filter down to nothing:
    # `selection.py::_validate_aspect_emphasis` holds the floor at import.
    emphasis = tuple(
        key for key in ASPECT_EMPHASIS[phase] if _week_ceiling_allows(drafts, draft, key, phase)
    )
    slot = draft.supplementary + (1 if draft.climbing_blocks else 0)
    intended = _intended_aspect(
        slot,
        emphasis,
        planner_input,
        phase=phase,
        week_no=week_no,
        session_index=draft.session_index,
        used=draft.supplementary_used,
    )
    if intended is None:
        return
    draft.supplementary += 1
    pref = _wall_pref(
        draft, phase, band=band, wall_seconds=wall_seconds, other_seconds=other_seconds
    )
    need = max(_window_floor(draft, phase) - draft.seconds, 0)
    room = _session_ceiling(draft) - draft.seconds if draft.blocks else 0
    filled = _fill_slot(
        intended,
        emphasis,
        planner_input,
        phase=phase,
        week_no=week_no,
        session_index=draft.session_index,
        used=draft.supplementary_used,
        spread=_spread(week_no, draft.session_index),
        wall_pref=pref,
        need=need,
        room=room,
    )
    shortfall = (
        None
        if filled is not None and filled[0] == intended
        else _shortfall(planner_input, phase, intended)
    )
    if filled is None:
        # A slot attempted only to top a session up to its window floor is not a promise the
        # plan made, so an unfillable one is length the session lacks and not a shortfall.
        if len(draft.blocks) < BLOCKS_PER_SESSION:
            draft.shortfalls.append(_require(shortfall))
        return
    _aspect_key, spec = filled
    added = _spec_seconds(spec, phase, week_no)
    on_wall = requires_wall(spec.equipment_keys)
    if draft.blocks and not _fits(draft, spec, phase, week_no):
        return
    if not _share_allows(
        draft,
        phase,
        added=added,
        on_wall=on_wall,
        band=band,
        week=(wall_seconds, other_seconds),
    ):
        return
    if not on_wall and not _floor_allows(wall_seconds, other_seconds, added, floor_pct):
        return
    _place(
        draft,
        spec,
        phase=phase,
        week_no=week_no,
        target_seconds=0,
        climbing=on_wall,
        shortfall=shortfall,
    )
    draft.supplementary_used.append(spec.aspect_key)


def _floor_allows(wall_seconds: int, other_seconds: int, added: int, floor_pct: int) -> bool:
    """Whether the week can afford `added` seconds of NON-climbing under its hard floor. A week
    with no wall time yet can: refusing there would leave a gearless session empty."""
    return not wall_seconds or meets_floor(
        wall_seconds=wall_seconds, other_seconds=other_seconds + added, floor_pct=floor_pct
    )


def _place(
    draft: _Draft,
    spec: ExerciseSpec,
    *,
    phase: Phase,
    week_no: int,
    target_seconds: int,
    climbing: bool,
    shortfall: Shortfall | None = None,
    fill_seconds: int | None = None,
) -> None:
    """Append one block, expanding its sets only where extra volume is real training.
    `fill_seconds` is ruling 27's length fill and the ONE dose the generator sizes itself:
    chunk-sized timed sets of plain climbing, on the open-climbing family's own authored shape
    (`sets=1, work_seconds=1800`). Sets are never padded to buy it — that is what
    `MAX_EXPANSION_FACTOR` forbids — and the row's authored intensity and RPE are kept."""
    prescription = _prescription_for(spec, phase, week_no)
    if fill_seconds is not None:
        # One chunk per set, so the longest set a fill can produce is `LENGTH_FILL_MINUTES` and a
        # 100-minute gap reads as four laps rather than as one 100-minute lap. Rounded UP, so the
        # session lands on its length rather than a few seconds under it.
        chunk = LENGTH_FILL_MINUTES * 60
        sets = -(-fill_seconds // chunk)
        prescription = replace(
            prescription,
            sets=sets,
            reps=None,
            work_seconds=-(-fill_seconds // sets),
            rest_seconds=None,
            rest_between_sets_seconds=None,
        )
    sets = prescription.sets
    if fill_seconds is None and is_expandable(spec.aspect_key, spec.protocol_kind, phase):
        sets = _expanded_sets(
            prescription,
            target_seconds=target_seconds - draft.seconds,
            cap_seconds=_session_ceiling(draft, spec) - draft.seconds,
        )
    draft.blocks.append(
        _block(
            len(draft.blocks) + 1,
            spec,
            phase=phase,
            shortfall=shortfall,
            sets=sets,
            prescription=prescription,
        )
    )
    draft.used.append(spec.aspect_key)
    draft.climbing_blocks += 1 if climbing else 0
    draft.wall_seconds += _block_seconds(draft.blocks[-1]) if climbing else 0


def _expanded_sets(prescription: PrescriptionSpec, *, target_seconds: int, cap_seconds: int) -> int:
    """Sets of an expandable protocol: enough to be a real session, never past the window."""
    sets = prescription.sets
    ceiling = prescription.sets * MAX_EXPANSION_FACTOR
    while (
        sets < ceiling
        and _prescribed_seconds(prescription, sets) < target_seconds
        and _prescribed_seconds(prescription, sets + 1) <= cap_seconds
    ):
        sets += 1
    return sets


def _spec_seconds(spec: ExerciseSpec, phase: Phase, week_no: int) -> int:
    """What this exercise costs in time in this phase and week, at its prescribed set count."""
    prescription = _prescription_for(spec, phase, week_no)
    return _prescribed_seconds(prescription, prescription.sets)


def _nearer_target(
    draft: _Draft, spec: ExerciseSpec, phase: Phase, week_no: int, *, target_seconds: int
) -> bool:
    """Whether one more wall block lands the session CLOSER to its target than stopping does.
    Rounding down broke monotonicity; free overshoot put the advanced band at 71% against 62."""
    return _spec_seconds(spec, phase, week_no) < 2 * (target_seconds - draft.seconds)


def _share_of_window_floor(draft: _Draft, spec: ExerciseSpec | None, pct: int, phase: Phase) -> int:
    """A percentage of the window floor of the session type these blocks make: the band's top
    share is what climbing fills to, its bottom share is what the session's length needs."""
    kinds = _kinds(draft, spec)
    if not kinds:
        return 0
    floor = session_window_across(kinds)[0] * 60
    return floor * session_floor_pct(phase) * pct // 10_000


def _share_allows(
    draft: _Draft,
    phase: Phase,
    *,
    added: int,
    on_wall: bool,
    band: tuple[int, int],
    week: tuple[int, int],
) -> bool:
    """Whether one more supplementary block keeps this session near its band's target share.

    Four reasons to say yes regardless, and each one is a measured failure of saying no. An
    unloading phase pursues half a floor and reserves nothing against the band: an allowance
    derived from its own small prescriptions produced a three-minute session. A session with no
    climbing at all has no share to reserve, and refusing there emptied every gearless session.
    A session still short of its type's window floor is topped up: length belongs to the type.
    And a SESSION already above the band's top edge wants supplementary work by definition —
    that arm is what closes the last three points.
    ⚠️ That last arm read the whole WEEK until 2026-09-04, which made it depend on the week's
    session count and broke the monotonicity invariant; `_block_ceiling` records the measurement.
    """
    low_pct, top_pct = band
    wall_seconds, other_seconds = week
    if phase in UNLOADING_PHASES or on_wall or not draft.wall_seconds:
        return True
    if _short_of_its_window(draft, phase):
        return True
    if meets_floor(
        wall_seconds=draft.wall_seconds, other_seconds=draft.other_seconds, floor_pct=top_pct
    ):
        return True
    allowance = draft.wall_seconds * (100 - low_pct) // max(low_pct, 1)
    return draft.other_seconds + added <= allowance


def _wall_pref(
    draft: _Draft,
    phase: Phase,
    *,
    band: tuple[int, int],
    wall_seconds: int,
    other_seconds: int,
) -> WallPref:
    """How much more climbing this SESSION can take, which orders a slot's candidate pool.

    `never` when the session is already at its band's top edge — more climbing is the one thing
    it does not need, and reading the WEEK there let a sixth session withhold a 16-minute wall
    block from a session that already existed. `first` when a session is short of its own
    window floor and the seconds that
    would close it cannot come off the wall without breaching the band's HARD floor: without
    this the preferred off-the-wall pick was chosen, rejected by that floor, and the slot spent
    for nothing, leaving a 37-minute limit-bouldering session against a 40-minute floor
    (measured, advanced boulder, week 18). `last` otherwise: prefer supplementary work, but
    never let the preference become the filter that made six exercises unreachable.
    """
    del wall_seconds, other_seconds
    if meets_floor(
        wall_seconds=draft.wall_seconds, other_seconds=draft.other_seconds, floor_pct=band[1]
    ):
        return "never"
    if draft.seconds < _window_floor(draft, phase):
        return "first"
    return "last"


def _prescribed_seconds(prescription: PrescriptionSpec, sets: int) -> int:
    """What `sets` sets of this prescription cost in time. The same arithmetic as a block's."""
    per_set = (prescription.work_seconds or (prescription.reps or 0) * SECONDS_PER_REP) + (
        prescription.rest_seconds or 0
    )
    return sets * per_set + max(sets - 1, 0) * (prescription.rest_between_sets_seconds or 0)


def _spread(week_no: int, session_index: int) -> int:
    """This session's ordinal in the plan's WEEKDAY grid, which is what indexes a CANDIDATE pool.

    Deliberately not `week_no - 1 + session_index`, which is what the ASPECT rotations use: a
    sum takes only ~5 distinct values inside a three-week phase, so every candidate pool longer
    than that lost its tail and one plan drew on 58 of 85 exercises where `dev` drew on 68.
    ⚠️ The stride is `DAYS_PER_WEEK` and **must not be the week's actual session count**: with
    that, adding a session re-keys every existing session's pool, and the measured cost was the
    monotonicity invariant — going from 5 sessions to 6 dropped week 2 from 159 to 152 climbing
    minutes. A fixed stride leaves sessions 0..n-1 on the offsets they already had.
    """
    return (week_no - 1) * DAYS_PER_WEEK + session_index


# `_spread`'s two terms, SWAPPED — which is the whole of issue #117's mechanical half. Read raw,
# `spread % len(pool)` loses the week for any pool whose length divides the stride.
#
# Measured: the base on-wall `endurance` pool is exactly 7, the stride is 7, and a session slot
# drew the identical endurance list in all three loading weeks. Here the WEEK's stride is 1, which
# no pool length can divide, and the SESSION takes the wide stride `_spread` needs for pool reach.
#
# ⚠️ Apply it at EVERY pool-index site, not only the wall pass: at `_wall_picks` alone the
# supplementary and top-up passes keep the aliasing, and that measured two FURTHER guards red
# (a declared weakness's own minutes, and one library row becoming unreachable).
def _pool_index(spread: int, size: int, depth: int = 0) -> int:
    """One candidate pool's index, keyed so the WEEK term can never cancel out of it."""
    week, session_index = divmod(spread, DAYS_PER_WEEK)
    return (week + session_index * DAYS_PER_WEEK + depth) % size


def _rotated_pool(pool: tuple[str, ...], offset: int) -> tuple[str, ...]:
    """The pool starting at a deterministic offset, so which quality leads moves week to week."""
    if not pool:
        return ()
    start = offset % len(pool)
    return pool[start:] + pool[:start]


def _no_climbing_shortfall(planner_input: PlannerInput, phase: Phase) -> Shortfall:
    """A session with no wall time names what climbing would need — #61's naming half. Never a
    gate: the plan is complete and this tells the climber something, not demands an inventory."""
    options = wall_unlock_options(
        phase, discipline=planner_input.discipline, open_injury_keys=planner_input.open_injury_keys
    )
    led = wall_led_aspects(phase)
    return Shortfall(
        phase=phase,
        aspect_key=led[0] if led else ASPECT_EMPHASIS[phase][0],
        options=options,
        message=no_climbing_message(options),
    )


def _session(draft: _Draft, week_start: date, phase: Phase) -> SessionBlueprint:
    """One draft, ordered quality-first and frozen into the output tree."""
    blocks = _ordered_blocks(draft.blocks, phase)
    return SessionBlueprint(
        weekday=draft.weekday,
        scheduled_on=session_date(week_start, draft.weekday),
        # A slot-less session is the terminal all-injuries case. `other`, so adherence does
        # not read it as a climbing session nobody did.
        activity_kind=ActivityKind.CLIMBING if draft.blocks else ActivityKind.OTHER,
        title=_title(blocks),
        estimated_minutes=_estimated_minutes(blocks) if blocks else None,
        blocks=blocks,
        shortfalls=tuple(draft.shortfalls),
    )


def _intended_aspect(
    slot: int,
    emphasis: tuple[str, ...],
    planner_input: PlannerInput,
    *,
    phase: Phase,
    week_no: int,
    session_index: int,
    used: list[str],
) -> str | None:
    """What this slot is *for*, before the climber's gear and injuries are consulted.

    Slot 0 is the phase's defining quality — a quality leads its own block, and where a
    climbing core exists the core IS that block, so the supplementary pass starts at slot 1.
    Slot 1 is the **weakness bias**: your weakness takes it in every session of every phase
    where it can be trained, except one turn in `WEAKNESS_YIELDS_SLOT_ONE_EVERY`. "Where it can
    be trained" is the library's judgement (the phase prescribes that aspect at all),
    deliberately not the climber's gear — a weakness that needs a hangboard should surface as
    "here is what you would need", not vanish. Slot 2 on rotate.

    ⚠️ The yield is ruling 21 and it is not a tiebreak: `general_strength` has no on-wall row in
    any phase, so this slot is its only route into a plan, and a weakness that never gave the
    slot back DELETED it from the base block on 23 of 24 profiles. A declared weakness stays the
    organising principle both sources make it — it may not delete another quality to be one.

    `UserAspectRating`'s per-aspect scores are never read: since issue #54 they sit behind a
    disclosure and may be untouched defaults, while `weakness_aspect_id` is the answer to a
    direct question.
    """
    if slot == 0:
        return emphasis[0]
    if slot == 1:
        weakness = planner_input.weakness_aspect_key
        turn = week_no - 1 + session_index
        pool = _secondary_pool(emphasis, planner_input, used)
        if weakness is None:
            return _rotated(pool, turn)
        if weakness in emphasis and weakness not in used and turn % WEAKNESS_YIELDS_SLOT_ONE_EVERY:
            return weakness
        # A yielded turn takes its own offset, `turn // N` rather than `turn`, so consecutive
        # yields step the pool by one instead of sampling it at one residue class.
        return _rotated(
            _no_other_route(pool, phase) or pool, turn // WEAKNESS_YIELDS_SLOT_ONE_EVERY
        )
    return _rotated(
        tuple(key for key in SUPPORT_ASPECTS if key not in used) or SUPPORT_ASPECTS,
        week_no + session_index + slot,
    )


def _no_other_route(pool: tuple[str, ...], phase: Phase) -> tuple[str, ...]:
    """The pool members whose ONLY route into a plan is this slot, in the phase's own order.

    `wall_led_aspects` is what the climbing pass rotates and `SUPPORT_ASPECTS` owns slot 2, so
    what is left here is the work no other pass can place. Ruling 21's yield rotates over THESE
    rather than over the whole pool because a base block is three weeks: at two sessions a week
    a yield every third turn comes round twice, and a nine-long pool needs nine turns to reach
    `general_strength` — measured, the plain pool still deleted it from 8 of 24 profiles.
    """
    wall = wall_led_aspects(phase)
    return tuple(key for key in pool if key not in wall and key not in SUPPORT_ASPECTS)


def _secondary_pool(
    emphasis: tuple[str, ...], planner_input: PlannerInput, used: list[str]
) -> tuple[str, ...]:
    """The rotation slot 1 falls back to, with the declared strength last.

    A strength is **maintained, never dropped** — it stays in the rotation and goes to the
    end of it, so it comes round less often than everything the climber is worse at.
    """
    pool = [key for key in emphasis if key not in used and key != planner_input.weakness_aspect_key]
    strength = planner_input.strength_aspect_key
    if strength in pool:
        pool.remove(strength)
        pool.append(strength)
    return tuple(pool)


def _rotated(pool: tuple[str, ...], offset: int) -> str | None:
    """Pick one, deterministically, by an offset that moves week to week and slot to slot."""
    if not pool:
        return None
    return pool[offset % len(pool)]


def _fill_slot(
    intended: str,
    emphasis: tuple[str, ...],
    planner_input: PlannerInput,
    *,
    phase: Phase,
    week_no: int,
    session_index: int,
    used: list[str],
    spread: int,
    wall_pref: WallPref,
    need: int,
    room: int,
) -> tuple[str, ExerciseSpec] | None:
    """Try `intended`, then walk the emphasis order for the next aspect that can be filled.

    The walk starts at `intended`'s own position and wraps, so displacement moves *down* the
    phase's priority order first — the nearest thing to what the slot was for.

    ⚠️ **ELIGIBILITY is `prescribable()`; on-the-wall versus off-the-wall is a PREFERENCE.**
    Round 2 made the off-the-wall pool a *filter*, so anything between it and the climbing
    pass's on-the-wall filter was unreachable by any profile — three wall `core_tension` drills,
    75 minutes a plan before and 0 after. The pool is off-the-wall first, on-the-wall behind it,
    and only `wall_pref` withholds the wall half: a week at its band's TOP edge cannot
    afford more climbing, the same arithmetic `_share_allows` applies to the other half.
    """
    start = emphasis.index(intended) if intended in emphasis else 0
    fallback: tuple[str, ExerciseSpec] | None = None
    for step in range(len(emphasis)):
        aspect_key = emphasis[(start + step) % len(emphasis)]
        if aspect_key in used:
            continue
        ordered = prescribable(
            ordinary(candidates(phase, aspect_key)),
            discipline=planner_input.discipline,
            equipment_keys=planner_input.equipment_keys,
            open_injury_keys=planner_input.open_injury_keys,
        )
        # Ruling 35: the band scales what an aspect is trained WITH, not how often. A filter and
        # not a rank, because `_pick` takes the LONGEST candidate whenever the session is short
        # of its window floor, and a rank is invisible on that branch.
        kinds = content_protocols_for(
            aspect_key, planner_input.discipline, planner_input.current_ordinal, phase
        )
        if kinds is not None:
            ordered = with_protocols(ordered, kinds)
        if not ordered:
            continue
        off, on = off_the_wall(ordered), on_the_wall(ordered)
        first, second = (on, off) if wall_pref == "first" else (off, on)
        pool = first if wall_pref == "never" else (*first, *second)
        if pool:
            return aspect_key, _pick(
                pool, phase, spread=spread, week_no=week_no, need=need, room=room
            )
        if fallback is None:
            fallback = (
                aspect_key,
                _pick(ordered, phase, spread=spread, week_no=week_no, need=need, room=room),
            )
    return fallback


def _pick(
    pool: tuple[ExerciseSpec, ...],
    phase: Phase,
    *,
    spread: int,
    week_no: int,
    need: int,
    room: int,
) -> ExerciseSpec:
    """The rotation pick, EXCEPT while the session is short of its own window floor.

    Rotating there picked a two-minute accessory block four times over and left a 37-minute
    limit-bouldering session against a 40-minute floor (measured, advanced boulder week 18):
    `MAX_BLOCKS_PER_SESSION` ran out before the length did. So a slot that exists to add length
    takes the longest candidate that still fits under the ceiling, authored order breaking ties.
    Padding it with sets instead is what `MAX_EXPANSION_FACTOR` exists to forbid.
    """
    if not need:
        return pool[_pool_index(spread, len(pool))]
    fitting = [spec for spec in pool if _spec_seconds(spec, phase, week_no) <= room] or list(pool)
    enough = tuple(spec for spec in fitting if _spec_seconds(spec, phase, week_no) >= need)
    if enough:
        return enough[_pool_index(spread, len(enough))]
    return max(fitting, key=lambda spec: _spec_seconds(spec, phase, week_no))


def _shortfall(planner_input: PlannerInput, phase: Phase, aspect_key: str) -> Shortfall:
    """What the slot was for, and what would have let us prescribe it."""
    options = unlock_options(
        phase,
        aspect_key,
        discipline=planner_input.discipline,
        open_injury_keys=planner_input.open_injury_keys,
    )
    return Shortfall(
        phase=phase,
        aspect_key=aspect_key,
        options=options,
        message=shortfall_message(
            phase, aspect_key, options, open_injury_keys=planner_input.open_injury_keys
        ),
    )


def _block(
    order_index: int,
    spec: ExerciseSpec,
    *,
    phase: Phase,
    shortfall: Shortfall | None,
    sets: int,
    prescription: PrescriptionSpec,
) -> BlockBlueprint:
    """One exercise, with its prescription snapshotted the way `session_block` snapshots it."""
    return BlockBlueprint(
        order_index=order_index,
        exercise_key=spec.key,
        aspect_key=spec.aspect_key,
        protocol_kind=spec.protocol_kind,
        sets=tuple(
            SetBlueprint(
                set_index=index,
                target_reps=prescription.reps,
                target_work_seconds=prescription.work_seconds,
                target_rest_seconds=prescription.rest_seconds,
                target_intensity_pct=prescription.intensity_pct,
                target_rpe=prescription.target_rpe,
            )
            for index in range(1, sets + 1)
        ),
        # No source: `prescription_template` authors no rest between BLOCKS, so v1.0.0
        # leaves it NULL rather than inventing a number, exactly as it does for
        # `target_load_kg`. Departure 4 in `blueprint.py` is the other half of this.
        rest_after_seconds=None,
        rest_between_sets_seconds=prescription.rest_between_sets_seconds,
        shortfall=shortfall,
    )


def _prescription_for(spec: ExerciseSpec, phase: Phase, week_no: int) -> PrescriptionSpec:
    """The authored row for this phase, moved on by this week's own progression (#117)."""
    for prescription in spec.prescriptions:
        if prescription.phase is phase:
            return progressed(
                prescription,
                exercise_key=spec.key,
                aspect_key=spec.aspect_key,
                protocol_kind=spec.protocol_kind,
                phase=phase,
                week_no=week_no,
            )
    raise ValueError(
        f"{spec.key!r} has no prescription for {phase.value}, so selection should never "
        f"have offered it. This is a bug in server/domain/planner/selection.py."
    )


def _title(blocks: tuple[BlockBlueprint, ...]) -> str:
    """The session's aspects, in prescribed order, as many of them as `TITLE_MAX_CHARS` holds.

    Deliberately not "Strength week 3": the microcycle already carries `phase` and
    `week_no`, and inventing display labels for `Phase` would be a second vocabulary for the
    client to disagree with. Comma-joined rather than "x, y and z" because two of the aspect
    names contain "and" themselves ("Core and tension"), and the list then reads as four.
    ⚠️ The width is a BOUND, not a measurement: five blocks of the five longest aspect names
    are 94 characters, and a session reached 83 the day a length top-up gave it a fifth
    distinct aspect — a `DataError` on insert, with `test_planner_safety.py` green because its
    arms did not sample that profile. Dropping the tail keeps the title honest as a summary;
    lengthening the column is a migration and is Kilian's call, not this function's.
    """
    if not blocks:
        return _RECOVERY_TITLE
    names = [ASPECT_NAMES[block.aspect_key] for block in blocks]
    listed = [names[0], *(name.lower() for name in names[1:])]
    title = listed[0][:TITLE_MAX_CHARS]
    for name in listed[1:]:
        if len(candidate := f"{title}, {name}") > TITLE_MAX_CHARS:
            break
        title = candidate
    return title


def _estimated_minutes(blocks: tuple[BlockBlueprint, ...]) -> int:
    """Prescribed seconds, rounded up, plus the warm-up nobody gets to skip."""
    seconds = sum(_block_seconds(block) for block in blocks)
    return math.ceil(seconds / 60) + WARMUP_MINUTES


def _block_seconds(block: BlockBlueprint) -> int:
    """Work plus rest, for every set and between them, plus any rest after the block."""
    per_set = sum(
        (item.target_work_seconds or (item.target_reps or 0) * SECONDS_PER_REP)
        + (item.target_rest_seconds or 0)
        for item in block.sets
    )
    between = max(len(block.sets) - 1, 0) * (block.rest_between_sets_seconds or 0)
    return per_set + between + (block.rest_after_seconds or 0)


def _rolled_up(mesocycles: tuple[MesocycleBlueprint, ...]) -> tuple[Shortfall, ...]:
    """Every shortfall in the tree, deduped by `(phase, aspect_key)`, first occurrence kept.

    Derived from the blocks rather than accumulated alongside them, so the plan-level list
    and the per-block notices cannot disagree.
    """
    seen: dict[tuple[Phase, str], Shortfall] = {}
    for mesocycle in mesocycles:
        for microcycle in mesocycle.microcycles:
            for session in microcycle.sessions:
                found = [
                    *(block.shortfall for block in session.blocks if block.shortfall is not None),
                    *session.shortfalls,
                ]
                for shortfall in found:
                    seen.setdefault((shortfall.phase, shortfall.aspect_key), shortfall)
    return tuple(seen.values())


def _require(shortfall: Shortfall | None) -> Shortfall:
    """An unfilled slot always has a shortfall — this makes that a type, not a comment."""
    if shortfall is None:
        raise ValueError("an unfilled slot must carry a shortfall; never an unexplained gap.")
    return shortfall
