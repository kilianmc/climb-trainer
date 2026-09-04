import { describe, expect, it } from 'vitest';

import type { PlanBlock, PlanMesocycle, PlanSession } from '../api/types';

import { ASPECT_KEYS, aspectCode, aspectOfCode, phaseWeeks } from './phaseWeek';

/* The week table's model: a transform with edges (an empty weekday, a day with several blocks)
   and a code map the legend and the cells both read. */

function block(aspectKey: string, orderIndex: number): PlanBlock {
  return {
    id: orderIndex + 1,
    order_index: orderIndex,
    exercise_key: 'weighted_max_hangs',
    exercise_id: 3,
    aspect_key: aspectKey,
    protocol_kind: 'max_hang',
    rest_after_seconds: 180,
    rest_between_sets_seconds: 120,
    shortfall: null,
    sets: [],
  };
}

/** Blocks given OUT of `order_index` order, so a pass cannot come from the input order. */
function session(weekday: number, blocks: readonly PlanBlock[]): PlanSession {
  return {
    id: weekday + 1,
    weekday,
    scheduled_on: '2026-01-05',
    title: 'Session',
    activity_kind: 'climbing',
    estimated_minutes: 60,
    status: 'planned',
    shortfalls: [],
    blocks: [...blocks].reverse(),
  };
}

const MESOCYCLE: PlanMesocycle = {
  id: 1,
  phase: 'strength',
  start_week: 5,
  end_week: 6,
  microcycles: [
    {
      id: 1,
      week_no: 5,
      phase: 'strength',
      is_deload: false,
      start_date: '2026-02-02',
      sessions: [
        session(0, [block('finger_strength', 0), block('power', 1)]),
        session(4, [block('power_endurance', 0), block('core_tension', 1)]),
      ],
    },
    {
      id: 2,
      week_no: 6,
      phase: 'strength',
      is_deload: false,
      start_date: '2026-02-09',
      sessions: [session(6, [block('mobility', 0)])],
    },
  ],
};

describe('one row per week, seven slots per row', () => {
  const model = phaseWeeks(MESOCYCLE);

  it('renders a row per microcycle and a slot per weekday', () => {
    expect(model.rows.map((row) => row.weekNo)).toEqual([5, 6]);
    for (const row of model.rows) {
      expect(row.days).toHaveLength(7);
      expect(row.days.map((day) => day.weekday)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    }
  });

  it('leaves a day with no session BLANK, which is what renders as rest', () => {
    const [week5] = model.rows;
    expect(week5?.days.filter((day) => day.aspects.length === 0).map((day) => day.weekday)).toEqual(
      [1, 2, 3, 5, 6],
    );
  });

  it('puts every block of a day in the block, once, in `order_index` order', () => {
    const monday = model.rows[0]?.days[0];
    expect(monday?.aspects.map((entry) => entry.key)).toEqual(['finger_strength', 'power']);
    expect(monday?.aspects.map((entry) => entry.code)).toEqual(['FS', 'P']);
    // Every block in the mesocycle appears exactly once across the whole table.
    const blocks = MESOCYCLE.microcycles.flatMap((microcycle) =>
      microcycle.sessions.flatMap((one) => one.blocks),
    );
    const rendered = model.rows.flatMap((row) => row.days.flatMap((day) => day.aspects));
    expect(rendered).toHaveLength(blocks.length);
  });

  it('names the aspect in full as well as in code, for the accessible name', () => {
    expect(model.rows[1]?.days[6]?.aspects).toEqual([
      { key: 'mobility', name: 'Mobility', code: 'M' },
    ]);
  });
});

describe('the aspect codes', () => {
  it('maps every seeded aspect to a 1-to-3-character code, both directions', () => {
    // Written out independently of `ASPECT_CODES`, so the map is checked rather than echoed.
    const expected = {
      finger_strength: 'FS',
      general_strength: 'GS',
      power: 'P',
      anaerobic_capacity: 'AC',
      power_endurance: 'PE',
      endurance: 'E',
      technique: 'T',
      core_tension: 'C&T',
      antagonist_prehab: 'A&P',
      mobility: 'M',
    };
    expect(ASPECT_KEYS).toEqual(Object.keys(expected));
    expect(new Set(Object.values(expected)).size).toBe(Object.keys(expected).length);
    for (const [key, code] of Object.entries(expected)) {
      expect(aspectCode(key)).toBe(code);
      expect(code.length).toBeLessThanOrEqual(3);
      expect(aspectOfCode(code)).toBe(key);
    }
  });

  it('has a legend covering every aspect, in the same order', () => {
    expect(phaseWeeks(MESOCYCLE).legend.map((entry) => entry.key)).toEqual(ASPECT_KEYS);
  });

  it('gives an aspect with no code yet its initials rather than nothing', () => {
    // An aspect seeded after this table renders short rather than unrenderable.
    expect(aspectCode('lock_off_strength')).toBe('LOS');
    expect(aspectOfCode('LOS')).toBeNull();
  });
});
