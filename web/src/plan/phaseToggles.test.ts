import { beforeEach, describe, expect, it } from 'vitest';

import type { Phase, PlanMesocycle, PlanSession, PlanTree } from '../api/types';

import {
  PHASE_STORAGE_KEY,
  PHASE_VERSION,
  allPhases,
  defaultOpenPhases,
  parsePhases,
  planKey,
  readOpenPhases,
  samePhases,
  serialisePhases,
  writeOpenPhases,
} from './phaseToggles';

/* Which phases open by default, and what survives a reload (#92). Both are logic with edges —
   a finished plan has no current block, and a stored set can belong to another plan. */

function session(scheduledOn: string, weekday: number, id: number): PlanSession {
  return {
    id,
    weekday,
    scheduled_on: scheduledOn,
    activity_kind: 'climbing',
    status: 'planned',
    title: 'Session',
    estimated_minutes: 45,
    blocks: [],
    shortfalls: [],
  };
}

function mesocycle(
  phase: Phase,
  startWeek: number,
  weeks: readonly { readonly weekNo: number; readonly day: string }[],
): PlanMesocycle {
  return {
    id: startWeek,
    phase,
    start_week: startWeek,
    end_week: startWeek + weeks.length - 1,
    microcycles: weeks.map((week) => ({
      id: week.weekNo,
      week_no: week.weekNo,
      start_date: week.day,
      is_deload: phase === 'deload',
      phase,
      sessions: [session(week.day, 0, week.weekNo * 10)],
    })),
  };
}

/** Three blocks, one session each: 2026-09-07, 2026-09-14 and 2026-09-21, all Mondays. */
function plan(overrides: Partial<PlanTree> = {}): PlanTree {
  return {
    id: 7,
    name: 'Road to 7b',
    start_date: '2026-09-07',
    week_count: 3,
    discipline: 'sport',
    target_grade_id: 16,
    current_grade_id: 11,
    grade_gap: 5,
    generator_version: '1.0.0',
    generator_input: {},
    activated_at: '2026-09-01T10:00:00Z',
    climbing_band: null,
    notes: [],
    shortfalls: [],
    mesocycles: [
      mesocycle('base', 1, [{ weekNo: 1, day: '2026-09-07' }]),
      mesocycle('strength', 2, [{ weekNo: 2, day: '2026-09-14' }]),
      mesocycle('taper', 3, [{ weekNo: 3, day: '2026-09-21' }]),
    ],
    ...overrides,
  };
}

describe('the phases that open by default', () => {
  it('opens the block the climber is standing in, and only that one', () => {
    expect(defaultOpenPhases(plan(), '2026-09-14')).toEqual([2]);
  });

  it('opens the block of the NEXT session on a rest day', () => {
    expect(defaultOpenPhases(plan(), '2026-09-16')).toEqual([3]);
  });

  it('falls back to the LAST block once every session is in the past', () => {
    expect(defaultOpenPhases(plan(), '2026-10-01')).toEqual([3]);
  });

  it('opens the first block before the plan has started', () => {
    expect(defaultOpenPhases(plan(), '2026-08-30')).toEqual([1]);
  });

  it('opens nothing at all for a plan with no phases', () => {
    expect(defaultOpenPhases(plan({ mesocycles: [] }), '2026-09-14')).toEqual([]);
  });

  it('names every phase for expand-all, in plan order', () => {
    expect(allPhases(plan())).toEqual([1, 2, 3]);
  });

  it('recognises the same set whatever its order, so a no-op toggle changes nothing', () => {
    expect(samePhases([1, 3], [3, 1])).toBe(true);
    expect(samePhases([1, 3], [1])).toBe(false);
    expect(samePhases([], [])).toBe(true);
  });
});

describe('the stored set', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('survives a round trip under the ct: namespace', () => {
    const key = planKey(plan());
    writeOpenPhases(key, [1, 3]);

    expect(window.localStorage.getItem(PHASE_STORAGE_KEY)).not.toBeNull();
    expect(readOpenPhases(key)).toEqual([1, 3]);
  });

  it('is discarded when it belongs to a DIFFERENT plan', () => {
    writeOpenPhases(planKey(plan()), [1, 3]);

    expect(readOpenPhases(planKey(plan({ id: 8 })))).toBeNull();
  });

  it('tells a preview apart from a persisted plan', () => {
    expect(planKey(plan({ id: null }))).toBe('preview:2026-09-07');
    expect(planKey(plan())).toBe('plan:7');
  });

  it('is discarded on a version bump rather than migrated', () => {
    const stored = serialisePhases('plan:7', [1]).replace(
      `"v":${String(PHASE_VERSION)}`,
      `"v":${String(PHASE_VERSION + 1)}`,
    );

    expect(parsePhases(stored, 'plan:7')).toBeNull();
  });

  it('reads unparseable or wrongly-shaped storage as no preference', () => {
    expect(parsePhases('not json', 'plan:7')).toBeNull();
    expect(parsePhases('[1,2]', 'plan:7')).toBeNull();
    expect(parsePhases(JSON.stringify({ v: PHASE_VERSION, plan: 'plan:7' }), 'plan:7')).toBeNull();
    expect(
      parsePhases(JSON.stringify({ v: PHASE_VERSION, plan: 'plan:7', open: ['1'] }), 'plan:7'),
    ).toBeNull();
  });
});
