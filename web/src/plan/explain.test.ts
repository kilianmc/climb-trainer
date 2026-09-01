import { describe, expect, it } from 'vitest';

import type {
  ClimbingBand,
  Phase,
  PlanMesocycle,
  PlanMicrocycle,
  PlanSession,
  PlanTree,
} from '../api/types';
import { selectSession } from '../session/today';

import type { PlanFact } from './explain';
import { phaseInPlan, sessionBlock, sessionBlockFacts } from './explain';

/* Week-range logic — what the testing policy in `CLAUDE.md` names explicitly. ⚠️ The edges are
   real: a phase RECURS, and on a REST DAY the brief describes the NEXT session's block. */

/** Whatever the server derives for an intermediate sport climber. Figures are the fixture's. */
const INTERMEDIATE: ClimbingBand = {
  level: 'intermediate',
  climbing_floor_pct: 75,
  climbing_target_pct_low: 75,
  climbing_target_pct_high: 82,
  finger_sessions_per_week: 1,
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

/** Exactly what the session brief's badges read, so these expectations ARE the rendered text. */
const rendered = (facts: readonly PlanFact[]) =>
  facts.map((fact) => `${fact.label}: ${fact.value}`);

describe('a phase in this plan', () => {
  it('carries EVERY occurrence, because a phase recurs', () => {
    expect(phaseInPlan(plan(), 'strength')?.weeks).toBe('Weeks 5–7 and 17–19');
  });

  it('lists all six deloads without claiming to be one block', () => {
    expect(phaseInPlan(plan(), 'deload')?.weeks).toBe('Weeks 4, 8, 12, 16, 20 and 24');
  });

  it('says "Week 28", not "Weeks 28–28", for a single-week mesocycle', () => {
    expect(phaseInPlan(plan(), 'taper')?.weeks).toBe('Week 28');
  });

  it('is null for a phase this plan never runs', () => {
    expect(phaseInPlan(plan({ mesocycles: [mesocycle('base', 1, 3)] }), 'taper')).toBeNull();
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
