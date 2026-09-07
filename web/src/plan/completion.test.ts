import { describe, expect, it } from 'vitest';

import type { PlanMesocycle, PlanTree, SessionCompletion } from '../api/types';

import {
  AMBER_FLOOR_PERCENT,
  BLOCK_MARK_LABEL,
  blockOutcome,
  completionBadge,
  completionBand,
  doneBlocks,
  phaseCompletionBadge,
  planWindow,
} from './completion';

/* What a past session carries in WORDS, and the window the read asks for. Colour alone must
   never be the carrier, so a missing label is a real defect rather than a style choice. */

/* Two block ids from the same session: one the climber did, one they did not. Literals, because
   the join key is `session_block.id` and a derived id would assert the fixture's arithmetic. */
const DONE_BLOCK = 21;
const MISSED_BLOCK = 23;

function row(overrides: Partial<SessionCompletion> = {}): SessionCompletion {
  return {
    planned_session_id: 10,
    scheduled_on: '2026-09-07',
    status: 'completed',
    state: 'completed',
    block_count: 3,
    blocks_done: 2,
    done_block_ids: [DONE_BLOCK, 22],
    percent: 67,
    ...overrides,
  };
}

/* One row per colour band, and the boundary cases either side of 50. The label is the ONLY
   thing a screenreader gets, so it is asserted with the band rather than instead of it. */
const BADGES = [
  { percent: 0, label: 'Skipped', band: 'low' },
  { percent: 1, label: '1% done', band: 'low' },
  { percent: 33, label: '33% done', band: 'low' },
  { percent: 49, label: '49% done', band: 'low' },
  { percent: 50, label: '50% done', band: 'partial' },
  { percent: 67, label: '67% done', band: 'partial' },
  { percent: 99, label: '99% done', band: 'partial' },
  { percent: 100, label: 'Completed', band: 'full' },
];

describe('what a past session shows', () => {
  it.each(BADGES)('shows $percent% as $label, in the $band band', ({ percent, label, band }) => {
    expect(completionBadge(row({ percent }))).toEqual({ label, band });
  });

  it('puts the boundary at 50, and 50 itself is amber rather than red', () => {
    expect(AMBER_FLOOR_PERCENT).toBe(50);
    expect(completionBand(AMBER_FLOOR_PERCENT - 1)).toBe('low');
    expect(completionBand(AMBER_FLOOR_PERCENT)).toBe('partial');
    expect(completionBand(99)).toBe('partial');
    expect(completionBand(100)).toBe('full');
    expect(completionBand(0)).toBe('low');
  });

  it('says the SAME thing whether Finish was pressed or not — the result is the same', () => {
    const finished = row({ status: 'completed', state: 'completed', blocks_done: 1, percent: 33 });
    const abandoned = row({ status: 'in_progress', state: 'skipped', blocks_done: 1, percent: 33 });
    const nobodyStarted = row({ status: 'planned', state: 'skipped', blocks_done: 1, percent: 33 });

    expect(completionBadge(finished)).toEqual({ label: '33% done', band: 'low' });
    expect(completionBadge(abandoned)).toEqual(completionBadge(finished));
    expect(completionBadge(nobodyStarted)).toEqual(completionBadge(finished));
  });

  it('colours a pressed-Finish session with nothing logged red, and calls it Skipped', () => {
    const claimed = row({ status: 'completed', state: 'completed', blocks_done: 0, percent: 0 });

    expect(completionBadge(claimed)).toEqual({ label: 'Skipped', band: 'low' });
  });

  it('says nothing at all about a session still to come', () => {
    const pending = row({ status: 'planned', state: 'pending', blocks_done: 0, percent: 0 });

    expect(completionBadge(pending)).toBeNull();
    expect(completionBadge(undefined)).toBeNull();
  });

  it('says nothing about a session with no blocks, whose percentage is null not 0', () => {
    const empty = { block_count: 0, blocks_done: 0, percent: null } as const;

    expect(completionBadge(row({ ...empty, state: 'completed' }))).toBeNull();
    expect(completionBadge(row({ ...empty, state: 'skipped' }))).toBeNull();
  });
});

describe('what a day still IN REACH may report — the scope split', () => {
  /* ⚠️ `state` decides nothing in the `progress` reading: `completed` means Finish was pressed,
     and #82 was that reading as a result — "what says it is completed is the inside items". */

  it('reports what has been LOGGED, in the same words as a settled day', () => {
    expect(completionBadge(row({ state: 'pending' }), 'progress')).toEqual({
      label: '67% done',
      band: 'partial',
    });
    expect(
      completionBadge(row({ state: 'pending', blocks_done: 3, percent: 100 }), 'progress'),
    ).toEqual({ label: 'Completed', band: 'full' });
  });

  it('⚠️ reports NOTHING while nothing has been logged, Finish pressed or not', () => {
    const untouched = { blocks_done: 0, done_block_ids: [], percent: 0 };

    for (const state of ['pending', 'completed'] as const) {
      expect(completionBadge(row({ ...untouched, state }), 'progress')).toBeNull();
      expect(doneBlocks(row({ ...untouched, state }), 'progress')).toBeNull();
    }
    // …and the same row on a day that is OVER is a real 0%, which is the whole distinction.
    expect(completionBadge(row({ ...untouched, state: 'skipped' }))).toEqual({
      label: 'Skipped',
      band: 'low',
    });
  });

  it('⚠️ marks its logged blocks done and leaves the rest UNMARKED, never missed', () => {
    const marks = doneBlocks(row({ state: 'pending', done_block_ids: [DONE_BLOCK] }), 'progress');

    expect(blockOutcome(marks, DONE_BLOCK)).toBe('done');
    expect(blockOutcome(marks, MISSED_BLOCK)).toBeNull();
  });
});

describe('which PART of a past session got done', () => {
  it('marks a logged block done and every other block of the same session missed', () => {
    const marks = doneBlocks(row({ done_block_ids: [DONE_BLOCK] }));

    expect(blockOutcome(marks, DONE_BLOCK)).toBe('done');
    expect(blockOutcome(marks, MISSED_BLOCK)).toBe('missed');
    // The WORD comes from the same decision as the tint, so colour is never the only channel.
    expect(BLOCK_MARK_LABEL).toEqual({ done: 'Done', missed: 'Missed' });
  });

  it('marks NOTHING on a session still to come — an unreached block is not a missed one', () => {
    expect(doneBlocks(row({ state: 'pending', done_block_ids: [], percent: 0 }))).toBeNull();
    expect(doneBlocks(undefined)).toBeNull();
    expect(blockOutcome(null, DONE_BLOCK)).toBeNull();
  });

  it('marks nothing on a PREVIEW block, which has no id to join on yet', () => {
    expect(blockOutcome(doneBlocks(row()), null)).toBeNull();
    expect(blockOutcome(doneBlocks(row()), undefined)).toBeNull();
  });

  it('marks a 0% past session entirely missed and a 100% one entirely done', () => {
    const skipped = doneBlocks(row({ state: 'skipped', done_block_ids: [], percent: 0 }));
    const whole = doneBlocks(
      row({ state: 'completed', done_block_ids: [DONE_BLOCK, MISSED_BLOCK], percent: 100 }),
    );

    expect([blockOutcome(skipped, DONE_BLOCK), blockOutcome(skipped, MISSED_BLOCK)]).toEqual([
      'missed',
      'missed',
    ]);
    expect([blockOutcome(whole, DONE_BLOCK), blockOutcome(whole, MISSED_BLOCK)]).toEqual([
      'done',
      'done',
    ]);
  });
});

describe('the window the read asks for', () => {
  const plan = (): PlanTree =>
    ({
      id: 7,
      start_date: '2026-09-07',
      mesocycles: [
        {
          id: 1,
          phase: 'base',
          start_week: 1,
          end_week: 1,
          microcycles: [
            {
              id: 1,
              week_no: 1,
              start_date: '2026-09-07',
              is_deload: false,
              phase: 'base',
              sessions: [
                {
                  id: 10,
                  weekday: 0,
                  scheduled_on: '2026-09-07',
                  activity_kind: 'climbing',
                  status: 'planned',
                  title: 'A',
                  estimated_minutes: 45,
                  blocks: [],
                  shortfalls: [],
                },
                {
                  id: 11,
                  weekday: 2,
                  scheduled_on: '2026-09-09',
                  activity_kind: 'climbing',
                  status: 'planned',
                  title: 'B',
                  estimated_minutes: 45,
                  blocks: [],
                  shortfalls: [],
                },
              ],
            },
          ],
        },
      ],
    }) as unknown as PlanTree;

  it('spans the plan from its start to its LAST session, not to its first', () => {
    expect(planWindow(plan())).toEqual({ from: '2026-09-07', to: '2026-09-09' });
  });

  it('is null for a plan with no sessions, so nothing is fetched', () => {
    expect(planWindow({ ...plan(), mesocycles: [] })).toBeNull();
  });
});

/* The PHASE aggregate: Kilian's own arithmetic — "12 = 100, skipped = 0, add the other % and
   come up with the total finished amount" — i.e. the mean, one twelfth per session. */

const TODAY = '2026-08-30';
const PAST = '2026-08-01';
const FUTURE = '2026-09-15';

/** One phase, one inner array per week. `number` is a row with that percentage, `null` a row with
 *  NO percentage (no blocks), `undefined` no row at all — a preview, or a read still in flight. */
function phase(
  weeks: readonly (readonly (number | null | undefined)[])[],
  dates: readonly string[] = weeks.map(() => PAST),
) {
  let id = 100;
  const rows: SessionCompletion[] = [];
  const microcycles = weeks.map((week, weekIndex) => {
    const scheduledOn = dates[weekIndex] ?? PAST;
    return {
      id: weekIndex + 1,
      week_no: weekIndex + 1,
      start_date: scheduledOn,
      is_deload: false,
      phase: 'base',
      sessions: week.map((percent, dayIndex) => {
        id += 1;
        if (percent !== undefined) {
          rows.push(
            row({
              planned_session_id: id,
              percent,
              scheduled_on: scheduledOn,
              block_count: percent === null ? 0 : 3,
            }),
          );
        }
        return { id, weekday: dayIndex, scheduled_on: scheduledOn };
      }),
    };
  });

  return {
    mesocycle: {
      id: 1,
      phase: 'base',
      start_week: 1,
      end_week: weeks.length,
      microcycles,
    } as unknown as PlanMesocycle,
    completion: new Map(rows.map((entry) => [entry.planned_session_id, entry] as const)),
  };
}

/** The badge for one week of percentages, all of them in the past. */
function badgeFor(
  percents: readonly (number | null | undefined)[],
  dates?: readonly string[],
  today = TODAY,
) {
  const { mesocycle, completion } = phase([percents], dates);
  return phaseCompletionBadge(mesocycle, completion, today);
}

describe('what a finished PHASE shows once it is collapsed', () => {
  it('is 0 and red when every session in it was skipped', () => {
    const { mesocycle, completion } = phase([
      [0, 0, 0, 0],
      [0, 0, 0, 0],
      [0, 0, 0, 0],
    ]);

    expect(phaseCompletionBadge(mesocycle, completion, TODAY)).toEqual({
      label: '0% done',
      percent: 0,
      band: 'low',
    });
  });

  it('is 100 and green only when every session in it was fully done', () => {
    const { mesocycle, completion } = phase([
      [100, 100, 100, 100],
      [100, 100, 100, 100],
      [100, 100, 100, 100],
    ]);

    expect(phaseCompletionBadge(mesocycle, completion, TODAY)).toEqual({
      label: 'Completed',
      percent: 100,
      band: 'full',
    });
  });

  it('weights every session EQUALLY: twelve sessions summing 650 read 54, not 100', () => {
    // 300 + 225 + 125 = 650 over twelve sessions = 54.16…, so 54. A blocks-over-blocks figure
    // would weight the four-block sessions above the two-block ones; this deliberately does not.
    const { mesocycle, completion } = phase([
      [100, 100, 100, 0],
      [50, 75, 100, 0],
      [100, 25, 0, 0],
    ]);

    expect(phaseCompletionBadge(mesocycle, completion, TODAY)).toEqual({
      label: '54% done',
      percent: 54,
      band: 'partial',
    });
  });

  it('is just that session for a one-session phase', () => {
    expect(badgeFor([67])).toEqual({ label: '67% done', percent: 67, band: 'partial' });
  });

  it('puts the phase boundary at 50 too, and 50 itself is amber rather than red', () => {
    expect(badgeFor([100, 0])?.percent).toBe(50);
    expect(badgeFor([100, 0])?.band).toBe('partial');
    expect(badgeFor([98, 0])?.band).toBe('low');
  });

  it('rounds half-UP, like the server, so 49.5 is 50 and lands amber', () => {
    expect(badgeFor([49, 50])).toEqual({ label: '50% done', percent: 50, band: 'partial' });
    expect(badgeFor([67, 68])?.percent).toBe(68);
  });

  it('excludes a session with NO blocks, whose percentage is null, from the mean', () => {
    // Two 100s and a null is 100, not 67: a session with no blocks has no result to average.
    expect(badgeFor([100, 100, null])?.percent).toBe(100);
    expect(badgeFor([100, 0, null])?.percent).toBe(50);
  });

  it('says nothing about a phase with no scored session at all — a preview has none', () => {
    expect(badgeFor([undefined, undefined])).toBeNull();
    expect(badgeFor([null, null])).toBeNull();
    expect(badgeFor([])).toBeNull();
  });

  it('says nothing about a phase still to come, however alarming 0% would look', () => {
    expect(badgeFor([100, 100], [FUTURE])).toBeNull();
    expect(badgeFor([0, 0], [FUTURE])).toBeNull();
  });

  it('says nothing about the phase being TRAINED — its figure is still moving', () => {
    // Week 1 is over, week 2 is not, so the phase is not entirely in the past.
    const { mesocycle, completion } = phase(
      [
        [100, 100],
        [0, 0],
      ],
      [PAST, FUTURE],
    );

    expect(phaseCompletionBadge(mesocycle, completion, TODAY)).toBeNull();
  });

  it('does not count TODAY as past, matching the server calling that session pending', () => {
    expect(badgeFor([100], [TODAY])).toBeNull();
    expect(badgeFor([100], ['2026-08-29'])).not.toBeNull();
  });

  it('takes its bands from the SHARED session decision point, never a second copy of 50', () => {
    // Symbolic on purpose: hard-coding 50 in the aggregate passes today and fails the moment
    // `AMBER_FLOOR_PERCENT` moves, which is the drift this guard exists to catch.
    expect(badgeFor([AMBER_FLOOR_PERCENT])?.band).toBe(completionBand(AMBER_FLOOR_PERCENT));
    expect(badgeFor([AMBER_FLOOR_PERCENT - 1])?.band).toBe(completionBand(AMBER_FLOOR_PERCENT - 1));
    expect(badgeFor([100])?.band).toBe(completionBand(100));
    expect(badgeFor([0])?.band).toBe(completionBand(0));
  });
});
