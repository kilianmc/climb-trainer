import { describe, expect, it } from 'vitest';

import type {
  ClimbingBand,
  Phase,
  PlanMesocycle,
  PlanMicrocycle,
  PlanSession,
  PlanTree,
  Vocabulary,
} from '../api/types';
import { selectSession } from '../session/today';

import type { PlanFact } from './explain';
import { phaseInPlan, planGoalFacts, sessionBlock, sessionBlockFacts } from './explain';

/* Derived-fact logic over grades, ordinals and week ranges — what the testing policy in
   `CLAUDE.md` names explicitly. The placeholder prose is deliberately not tested. */

/* ⚠️ The edges are real, not hypothetical: a phase RECURS (six deloads in 28 weeks),
   `sessions_per_week` can be 1, and the beginner band owes ZERO finger sessions. */

/* Nothing here restates a training constant: every band figure enters through a fixture standing
   in for `PlanOut.climbing_band`, because the server owns those numbers. */

const SPORT_SYSTEM = 1;

function vocabulary(): Vocabulary {
  return {
    grade_systems: [{ id: SPORT_SYSTEM, key: 'french', name: 'French', discipline: 'sport' }],
    grades: [
      { id: 11, grade_system_id: SPORT_SYSTEM, label: '6c', ordinal: 2010 },
      { id: 16, grade_system_id: SPORT_SYSTEM, label: '7b', ordinal: 2015 },
    ],
    climbing_aspects: [],
    equipment: [],
    injury_areas: [],
    plan_goal: '',
    phase_guide: [],
    enums: {
      disciplines: ['sport'],
      activity_kinds: ['climbing'],
      ascent_styles: ['redpoint'],
      protocol_kinds: ['max_hang'],
      phases: ['base'],
      session_statuses: ['planned'],
    },
  };
}

/** Whatever the server derives for an intermediate sport climber. Figures are the fixture's. */
const INTERMEDIATE: ClimbingBand = {
  level: 'intermediate',
  climbing_floor_pct: 75,
  climbing_target_pct_low: 75,
  climbing_target_pct_high: 82,
  finger_sessions_per_week: 1,
  finger_phases: ['strength', 'power'],
};

const BEGINNER: ClimbingBand = {
  level: 'beginner',
  climbing_floor_pct: 85,
  climbing_target_pct_low: 85,
  climbing_target_pct_high: 90,
  finger_sessions_per_week: 0,
  finger_phases: ['strength', 'power'],
};

function mesocycle(phase: Phase, startWeek: number, endWeek: number): PlanMesocycle {
  return { id: null, phase, start_week: startWeek, end_week: endWeek, microcycles: [] };
}

/* ⚠️ The 14 mesocycles below are the REAL ones `generate()` produces for this input (sport,
   2010 → 2015, four sessions, every weekday, full equipment), not an invented shape. */
const REAL_MESOCYCLES: readonly [Phase, number, number][] = [
  ['base', 1, 3],
  ['deload', 4, 4],
  ['strength', 5, 7],
  ['deload', 8, 8],
  ['power', 9, 11],
  ['deload', 12, 12],
  ['power_endurance', 13, 15],
  ['deload', 16, 16],
  ['strength', 17, 19],
  ['deload', 20, 20],
  ['power', 21, 23],
  ['deload', 24, 24],
  ['performance', 25, 27],
  ['taper', 28, 28],
];

/** The owner's real plan: 28 weeks, sport, four sessions, 6c → 7b, power strong, mobility weak. */
function plan(overrides: Partial<PlanTree> = {}): PlanTree {
  const mesocycles: PlanMesocycle[] = REAL_MESOCYCLES.map(([phase, start, end]) =>
    mesocycle(phase, start, end),
  );

  return {
    id: 7,
    name: 'Road to 7b',
    start_date: '2026-09-07',
    week_count: 28,
    discipline: 'sport',
    target_grade_id: 16,
    current_grade_id: 11,
    grade_gap: 5,
    generator_version: '1.0.0',
    generator_input: {
      sessions_per_week: 4,
      current_ordinal: 2010,
      target_ordinal: 2015,
      strength_aspect_key: 'power',
      weakness_aspect_key: 'mobility',
      open_injury_keys: [],
    },
    activated_at: '2026-09-01T10:00:00Z',
    climbing_band: INTERMEDIATE,
    notes: [],
    shortfalls: [],
    mesocycles,
    ...overrides,
  };
}

const valueOf = (facts: readonly PlanFact[], label: string) =>
  facts.filter((fact) => fact.label === label).map((fact) => fact.value);

/** Exactly what the badges on `/plan` read, so these expectations ARE the rendered text. */
const rendered = (facts: readonly PlanFact[]) =>
  facts.map((fact) => `${fact.label}: ${fact.value}`);

describe('the plan-level goal', () => {
  it('is composed from THIS plan, not from a phrase every plan shares', () => {
    expect(rendered(planGoalFacts(plan(), vocabulary()))).toEqual([
      'Goal: 6c → 7b',
      'Length: 28 weeks in 14 blocks',
      'Discipline: Sport',
      'Sessions: 4 sessions a week',
      'Your strong point: Power',
      'Your weak point: Mobility',
      'Your band: Intermediate',
      'On the wall: 75–82% of each week, never under 75%',
    ]);
  });

  it('says "1 session a week", which the generator makes 100% climbing', () => {
    const one = plan({ generator_input: { sessions_per_week: 1 } });
    expect(valueOf(planGoalFacts(one, vocabulary()), 'Sessions')).toEqual(['1 session a week']);
  });

  it('names the gap when a grade label cannot be resolved, rather than printing nothing', () => {
    const facts = planGoalFacts(plan({ current_grade_id: null }), vocabulary());
    expect(valueOf(facts, 'Goal')).toEqual(['5 rungs harder']);
  });

  it('omits every band figure when the server could not derive one', () => {
    const facts = planGoalFacts(plan({ climbing_band: null }), vocabulary());
    expect(valueOf(facts, 'Your band')).toEqual([]);
    expect(valueOf(facts, 'On the wall')).toEqual([]);
  });
});

describe('a phase in this plan', () => {
  it('carries EVERY occurrence, because a phase recurs', () => {
    const strength = phaseInPlan(plan(), 'strength');
    expect(strength?.weeks).toBe('Weeks 5–7 and 17–19');
    expect(rendered(strength?.facts ?? [])).toEqual([
      'Blocks: 2 blocks · 6 of 28 weeks',
      'Hangboard: 1 session a week',
    ]);
  });

  it('lists all six deloads without claiming to be one block', () => {
    const deload = phaseInPlan(plan(), 'deload');
    expect(deload?.weeks).toBe('Weeks 4, 8, 12, 16, 20 and 24');
    expect(rendered(deload?.facts ?? [])).toEqual(['Blocks: 6 blocks · 6 of 28 weeks']);
  });

  it('says "Week 28", not "Weeks 28–28", for a single-week mesocycle', () => {
    expect(phaseInPlan(plan(), 'taper')?.weeks).toBe('Week 28');
  });

  it('is null for a phase this plan never runs', () => {
    expect(phaseInPlan(plan({ mesocycles: [mesocycle('base', 1, 3)] }), 'taper')).toBeNull();
  });

  it('places the hangboard figure only in the phases the SERVER says owe one', () => {
    expect(valueOf(phaseInPlan(plan(), 'strength')?.facts ?? [], 'Hangboard')).toEqual([
      '1 session a week',
    ]);
    expect(valueOf(phaseInPlan(plan(), 'base')?.facts ?? [], 'Hangboard')).toEqual([]);
  });

  it('OMITS the hangboard line for the beginner band, rather than printing "0 sessions"', () => {
    const beginner = plan({ climbing_band: BEGINNER });
    const facts = phaseInPlan(beginner, 'strength')?.facts ?? [];
    expect(valueOf(facts, 'Hangboard')).toEqual([]);
    expect(facts.map((fact) => fact.value).join(' ')).not.toContain('0 session');
  });

  it('flags a declared strength or weakness only where the key IS the phase', () => {
    const power = phaseInPlan(plan(), 'power');
    expect(valueOf(power?.facts ?? [], 'You called this')).toEqual(['a strong point']);
    // `mobility` names no phase, so it is said once at plan level and nowhere per-phase.
    const everyPhase: Phase[] = ['base', 'strength', 'power', 'power_endurance', 'performance'];
    const flagged = everyPhase.flatMap((phase) =>
      valueOf(phaseInPlan(plan(), phase)?.facts ?? [], 'You called this'),
    );
    expect(flagged).toEqual(['a strong point']);
  });
});

/* Week one starts on Monday 7 September 2026. UTC arithmetic only: these are plan dates being
   compared as strings, and `localIsoDate` is what owns the browser's timezone. */
const MONDAY_WEEK_ONE = Date.UTC(2026, 8, 7);
const DAY_MS = 86_400_000;

const dayOf = (weekNo: number, weekday: number) =>
  new Date(MONDAY_WEEK_ONE + ((weekNo - 1) * 7 + weekday) * DAY_MS).toISOString().slice(0, 10);

/** One session, on the Tuesday of its week. `id` is the week number, so a test can name one. */
function sessionInWeek(weekNo: number): PlanSession {
  return {
    activity_kind: 'climbing',
    blocks: [],
    estimated_minutes: 90,
    id: weekNo,
    scheduled_on: dayOf(weekNo, 1),
    shortfalls: [],
    status: 'planned',
    title: `Week ${String(weekNo)}`,
    weekday: 1,
  };
}

function weeksOf(phase: Phase, start: number, end: number): PlanMicrocycle[] {
  const weeks: PlanMicrocycle[] = [];
  for (let weekNo = start; weekNo <= end; weekNo += 1) {
    weeks.push({
      id: weekNo,
      is_deload: phase === 'deload',
      phase,
      sessions: [sessionInWeek(weekNo)],
      start_date: dayOf(weekNo, 0),
      week_no: weekNo,
    });
  }
  return weeks;
}

/** The same 14 real blocks, weeked in: one microcycle per week, one session in each. */
function weekedPlan(): PlanTree {
  return plan({
    mesocycles: REAL_MESOCYCLES.map(([phase, start, end]) => ({
      ...mesocycle(phase, start, end),
      microcycles: weeksOf(phase, start, end),
    })),
  });
}

function blockOf(tree: PlanTree, session: PlanSession | null) {
  const block = sessionBlock(tree, session);
  if (block === null) throw new Error('the fixture session is not in the fixture plan');
  return block;
}

describe('the block one session belongs to', () => {
  it('walks back the week and the mesocycle `selectSession` flattened away', () => {
    const tree = weekedPlan();
    const choice = selectSession(tree, dayOf(6, 1));
    expect(choice.reason).toBe('today');

    const block = blockOf(tree, choice.session);
    expect(block).toEqual({ weekNo: 6, phase: 'strength', startWeek: 5, endWeek: 7 });
    expect(rendered(sessionBlockFacts(tree, block, 'Max strength'))).toEqual([
      'Week: 6 of 28',
      'Block: Max strength · wk 5–7',
    ]);
  });

  it('says "wk 4", not "wk 4–4", for a one-week deload — and the same for the taper', () => {
    const tree = weekedPlan();
    const deload = blockOf(tree, selectSession(tree, dayOf(4, 1)).session);
    expect(rendered(sessionBlockFacts(tree, deload, 'Deload'))).toEqual([
      'Week: 4 of 28',
      'Block: Deload · wk 4',
    ]);
    const taper = blockOf(tree, selectSession(tree, dayOf(28, 1)).session);
    expect(rendered(sessionBlockFacts(tree, taper, 'Taper'))).toEqual([
      'Week: 28 of 28',
      'Block: Taper · wk 28',
    ]);
  });

  it('⚠️ on a REST DAY describes the session on screen, not the block today sits in', () => {
    const tree = weekedPlan();
    // The Sunday at the end of week 4, a deload week: nothing is scheduled, so the brief offers
    // week 5's session — which is in the NEXT mesocycle, a strength block.
    const choice = selectSession(tree, dayOf(4, 6));
    expect(choice.reason).toBe('rest_day');

    const block = blockOf(tree, choice.session);
    const facts = rendered(sessionBlockFacts(tree, block, 'Max strength'));
    expect(facts).toEqual(['Week: 5 of 28', 'Block: Max strength · wk 5–7']);
    expect(facts.join(' ')).not.toContain('Deload');
    expect(facts.join(' ')).not.toContain('4 of 28');
  });

  it('finds a session by id after a refetch, and is null for one this plan never had', () => {
    const tree = weekedPlan();
    // A fresh object with the same id: what a re-fetched plan hands back.
    expect(blockOf(tree, { ...sessionInWeek(6) }).weekNo).toBe(6);
    expect(sessionBlock(tree, sessionInWeek(99))).toBeNull();
    expect(sessionBlock(tree, { ...sessionInWeek(6), id: null })).toBeNull();
    expect(sessionBlock(null, sessionInWeek(6))).toBeNull();
    expect(sessionBlock(tree, null)).toBeNull();
  });
});
