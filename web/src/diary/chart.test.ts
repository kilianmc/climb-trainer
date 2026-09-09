import { describe, expect, it } from 'vitest';

import type { JournalEntry, JournalPlan } from '../api/types';

import type { PlanWeek } from './chart';
import {
  ALL_SERIES_KEYS,
  CHART_VIEW,
  LABEL_GAP_MIN,
  PLOT,
  diaryChart,
  formatDayNumeric,
  formatKg,
  groupSpan,
  journalPlanWeeks,
  scoreRows,
  toggleSeries,
} from './chart';

/** The chart's geometry, with no DOM. ⚠️ Nothing here smooths anything: a 1-5 score IS the datum,
 *  and averaging it is what shortened the line the old screen drew. */

let nextId = 0;

function entry(entry_date: string, overrides: Partial<JournalEntry> = {}): JournalEntry {
  nextId += 1;
  return {
    id: nextId,
    client_uuid: `uuid-${String(nextId)}`,
    entry_date,
    body: null,
    feel: null,
    sleep_quality: null,
    skin: null,
    body_weight_kg: null,
    logged_session_id: null,
    plan: null,
    ...overrides,
  };
}

const PLAN_START = '2026-01-05';
const TODAY = '2026-02-16';

/** The plan's OWN week starts, exactly as `/api/plans/active` sends them: a FIXTURE, because
 *  where a week begins is the server's fact and this module must never derive one. */
function weekStarts(count: number): PlanWeek[] {
  const first = Date.UTC(2026, 0, 5);
  return Array.from({ length: count }, (_unused, index) => ({
    weekNo: index + 1,
    startIso: new Date(first + index * 7 * 86_400_000).toISOString().slice(0, 10),
  }));
}

/** The day whole weeks after the plan started, so a span can be stated in weeks. */
function weeksIn(count: number): string {
  return weekStarts(count + 1).at(-1)?.startIso ?? PLAN_START;
}

describe('the x axis is the PLAN, not the readings', () => {
  it('spans the plan’s start to today even when every reading is bunched in one week', () => {
    const chart = diaryChart(
      [entry('2026-02-09', { feel: 3 }), entry('2026-02-10', { feel: 4 })],
      PLAN_START,
      TODAY,
    );

    expect(chart?.fromIso).toBe(PLAN_START);
    expect(chart?.toIso).toBe(TODAY);
    // The readings' OWN extent would have pinned these two to the far edges. They must not be.
    const marks = chart?.series[0]?.marks ?? [];
    expect(marks[0]?.x).toBeGreaterThan(PLOT.start);
    expect(marks[1]?.x).toBeLessThan(PLOT.end);
  });

  it('puts week 1 at the far left and week 6 at the far right, with the middle empty', () => {
    const chart = diaryChart(
      [entry('2026-01-05', { feel: 2 }), entry('2026-02-16', { feel: 5 })],
      PLAN_START,
      TODAY,
    );

    const marks = chart?.series[0]?.marks ?? [];
    expect(marks[0]?.x).toBeCloseTo(PLOT.start, 5);
    expect(marks[1]?.x).toBeCloseTo(PLOT.end, 5);
  });

  it('takes the earliest entry as the anchor for the whole-history view', () => {
    const chart = diaryChart(
      [entry('2025-11-02', { skin: 3 }), entry('2026-02-09', { skin: 4 })],
      null,
      TODAY,
    );

    expect(chart?.fromIso).toBe('2025-11-02');
    expect(chart?.toIso).toBe(TODAY);
  });

  it('widens rather than clips a reading dated before the plan started', () => {
    const chart = diaryChart([entry('2025-12-20', { feel: 3 })], PLAN_START, TODAY);

    expect(chart?.fromIso).toBe('2025-12-20');
    expect(chart?.series[0]?.marks[0]?.x).toBeCloseTo(PLOT.start, 5);
  });

  it('ends at the newest reading when it is somehow later than today', () => {
    const chart = diaryChart([entry('2026-03-01', { feel: 3 })], PLAN_START, TODAY);

    expect(chart?.toIso).toBe('2026-03-01');
  });

  it('spaces marks by DATE, not by index, so a gap stays a gap', () => {
    const chart = diaryChart(
      [
        entry('2026-01-05', { feel: 3 }),
        entry('2026-01-06', { feel: 3 }),
        entry('2026-02-16', { feel: 3 }),
      ],
      PLAN_START,
      TODAY,
    );

    const [first, second, third] = chart?.series[0]?.marks ?? [];
    const together = (second?.x ?? 0) - (first?.x ?? 0);
    const apart = (third?.x ?? 0) - (second?.x ?? 0);
    expect(apart).toBeGreaterThan(together * 20);
  });
});

describe('a lone reading is still something on the screen', () => {
  it('draws one mark and a one-point path', () => {
    const chart = diaryChart([entry('2026-01-19', { sleep_quality: 2 })], PLAN_START, TODAY);
    const series = chart?.series[1];

    expect(series?.key).toBe('sleep_quality');
    expect(series?.marks).toHaveLength(1);
    expect(series?.path).toMatch(/^M/);
  });

  it('is a SENTENCE, not an empty frame, when nothing was ever scored', () => {
    expect(diaryChart([], PLAN_START, TODAY)).toBeNull();
    expect(diaryChart([entry('2026-01-19', { body_weight_kg: '71.4' })], PLAN_START, TODAY)).toBe(
      null,
    );
  });

  it('leaves a metric’s line undrawn without dropping the other two', () => {
    const chart = diaryChart([entry('2026-01-19', { feel: 4 })], PLAN_START, TODAY);

    expect(chart?.series.map((one) => one.marks.length)).toEqual([1, 0, 0]);
    expect(chart?.series[2]?.path).toBe('');
    expect(chart?.readings).toBe(1);
  });
});

describe('the y axis is the column’s own 1-5 CHECK', () => {
  it('does not stretch a run of 4s and 5s to fill the frame', () => {
    const chart = diaryChart(
      [entry('2026-01-05', { feel: 4 }), entry('2026-02-16', { feel: 5 })],
      PLAN_START,
      TODAY,
    );
    const levels = chart?.levels ?? [];
    const [low, high] = chart?.series[0]?.marks ?? [];

    expect(levels.map((level) => level.value)).toEqual([1, 2, 3, 4, 5]);
    expect(low?.y).toBeCloseTo(levels[3]?.y ?? 0, 5);
    expect(high?.y).toBeCloseTo(levels[4]?.y ?? 0, 5);
  });

  it('puts a higher score HIGHER on the screen, which is a smaller y', () => {
    const levels = diaryChart([entry('2026-01-05', { skin: 1 })], PLAN_START, TODAY)?.levels ?? [];
    const ys = levels.map((level) => level.y);

    expect(ys).toEqual([...ys].sort((left, right) => right - left));
  });

  it('keeps every mark inside the viewBox', () => {
    const chart = diaryChart(
      [entry('2026-01-05', { feel: 1, sleep_quality: 5, skin: 3 })],
      PLAN_START,
      TODAY,
    );

    for (const series of chart?.series ?? []) {
      for (const mark of series.marks) {
        expect(mark.x).toBeGreaterThanOrEqual(0);
        expect(mark.x).toBeLessThanOrEqual(CHART_VIEW.width);
        expect(mark.y).toBeGreaterThanOrEqual(0);
        expect(mark.y).toBeLessThanOrEqual(CHART_VIEW.height);
      }
    }
  });
});

describe('draw order is fixed, so the solid line is never on top', () => {
  it('is feel, then sleep, then skin — solid under dashed under dotted', () => {
    const chart = diaryChart(
      [entry('2026-01-05', { feel: 4, sleep_quality: 4, skin: 4 })],
      PLAN_START,
      TODAY,
    );

    expect(chart?.series.map((one) => one.key)).toEqual(['feel', 'sleep_quality', 'skin']);
  });

  it('stacks three identical readings on ONE point rather than offsetting any of them', () => {
    const chart = diaryChart(
      [entry('2026-01-19', { feel: 4, sleep_quality: 4, skin: 4 })],
      PLAN_START,
      TODAY,
    );
    const points = chart?.series.map((one) => one.marks[0]) ?? [];

    expect(new Set(points.map((mark) => mark?.y))).toHaveLength(1);
    expect(new Set(points.map((mark) => mark?.x))).toHaveLength(1);
  });
});

describe('⚠️ a reading with no neighbour, now that there are no markers', () => {
  it('hands back the ONE reading a polyline cannot draw, so it is not lost', () => {
    const chart = diaryChart([entry('2026-01-19', { sleep_quality: 2 })], PLAN_START, TODAY);
    const series = chart?.series[1];

    // ⚠️ THE GUARD. `M x y` on its own paints nothing, so without this the climber's only
    // reading is blank canvas — and "just keep the lines" was never "lose the data".
    expect(series?.marks).toHaveLength(1);
    expect(series?.orphans).toEqual(series?.marks);
  });

  it('marks NOTHING once the readings are joined, so no marker returns by the side door', () => {
    const chart = diaryChart(
      [
        entry('2026-01-19', { feel: 2 }),
        entry('2026-02-09', { feel: 5 }),
        entry('2026-02-10', { feel: 4 }),
      ],
      PLAN_START,
      TODAY,
    );

    expect(chart?.series[0]?.marks).toHaveLength(3);
    expect(chart?.series[0]?.orphans).toEqual([]);
  });

  it('gives a series that was never scored no orphan of its own', () => {
    const chart = diaryChart([entry('2026-01-19', { feel: 4 })], PLAN_START, TODAY);

    expect(chart?.series.map((one) => one.orphans.length)).toEqual([1, 0, 0]);
  });
});

describe('the time axis is ruled in the PLAN’s own weeks', () => {
  it('ticks the week starts the plan sent, and drops the ones today has not reached', () => {
    const chart = diaryChart(
      [entry('2026-01-19', { feel: 3 })],
      PLAN_START,
      weeksIn(8),
      weekStarts(12),
    );

    // Nine boundaries inside the span; weeks 10-12 have not started, so they are not drawn.
    expect(chart?.weeks.map((week) => week.weekNo)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
  });

  it('writes down only a SUBSET of an eight-week span, never every week (Kilian)', () => {
    const chart = diaryChart(
      [entry('2026-01-19', { feel: 3 })],
      PLAN_START,
      weeksIn(8),
      weekStarts(9),
    );
    const labelled = chart?.weeks.filter((week) => week.labelled) ?? [];

    expect(labelled.map((week) => week.weekNo)).toEqual([1, 3, 5, 7, 9]);
  });

  it('thins them further over forty weeks, rather than hard-coding one stride', () => {
    const chart = diaryChart(
      [entry('2026-01-19', { feel: 3 })],
      PLAN_START,
      weeksIn(39),
      weekStarts(40),
    );
    const labelled = chart?.weeks.filter((week) => week.labelled) ?? [];

    // ⚠️ Every week is still a TICK; it is the labels that thin out.
    expect(chart?.weeks).toHaveLength(40);
    expect(labelled.map((week) => week.weekNo)).toEqual([1, 9, 17, 25, 33]);
  });

  it('keeps every pair of labels a label’s width apart at every span', () => {
    for (const count of [2, 6, 8, 13, 20, 40, 60]) {
      const chart = diaryChart(
        [entry('2026-01-19', { feel: 3 })],
        PLAN_START,
        weeksIn(count - 1),
        weekStarts(count),
      );
      const xs = (chart?.weeks ?? []).filter((week) => week.labelled).map((week) => week.x);

      for (let index = 1; index < xs.length; index += 1) {
        expect((xs[index] ?? 0) - (xs[index - 1] ?? 0)).toBeGreaterThanOrEqual(LABEL_GAP_MIN);
      }
    }
  });

  it('anchors the end labels inwards, so neither is clipped', () => {
    const chart = diaryChart(
      [entry('2026-01-19', { feel: 3 })],
      PLAN_START,
      weeksIn(8),
      weekStarts(9),
    );
    const labelled = chart?.weeks.filter((week) => week.labelled) ?? [];

    expect(labelled.at(0)?.anchor).toBe('start');
    expect(labelled.at(-1)?.anchor).toBe('end');
    expect(labelled.at(1)?.anchor).toBe('middle');
  });

  it('has no ruler at all when the caller has no plan weeks to give it', () => {
    // ⚠️ The whole-history view. Only the ACTIVE plan's weeks are on the wire, and dividing the
    // span by seven would draw boundaries this climber's older plans never had.
    expect(diaryChart([entry('2025-11-02', { skin: 3 })], null, TODAY)?.weeks).toEqual([]);
  });
});

describe('the readings are also numbers', () => {
  it('lists every scored entry oldest first, with a hole where a metric was skipped', () => {
    const rows = scoreRows([
      entry('2026-02-09', { feel: 3, skin: 2 }),
      entry('2026-01-19', { sleep_quality: 5 }),
      entry('2026-01-20', { body_weight_kg: '70.0' }),
    ]);

    // No weigh-in column, so a weigh-in is not a reading and that entry owes no row.
    expect(rows.map((row) => row.entryDate)).toEqual(['2026-01-19', '2026-02-09']);
    expect(rows[0]?.values).toEqual([null, 5, null]);
    expect(rows[1]?.values).toEqual([3, null, 2]);
  });

  /** ⚠️ THE GUARD. This table is the only place every weigh-in is listed now, so filtering the
   *  row set on the 1-5 readings alone would drop the days that carry nothing else. */
  it('keeps an entry that scored NOTHING but was weighed, once the column is shown', () => {
    const rows = scoreRows(
      [
        entry('2026-02-09', { feel: 3, body_weight_kg: '71.4' }),
        entry('2026-01-20', { body_weight_kg: '70.0' }),
        entry('2026-01-19', { sleep_quality: 5 }),
      ],
      true,
    );

    expect(rows.map((row) => [row.entryDate, row.kg])).toEqual([
      ['2026-01-19', null],
      ['2026-01-20', '70.0'],
      ['2026-02-09', '71.4'],
    ]);
    // The scored cells of a weigh-in-only day are empty, which is what the table draws as '—'.
    expect(rows[1]?.values).toEqual([null, null, null]);
  });
});

describe('the weigh-in string is SHOWN, never re-parsed into a float', () => {
  it('reads one decimal, and hands back anything it cannot parse untouched', () => {
    expect(formatKg('71.40')).toBe('71.4');
    expect(formatKg(71.649)).toBe('71.6');
    expect(formatKg('about seventy')).toBe('about seventy');
  });
});

describe('the table day is dd/mm/yy, off the string parts', () => {
  it('zero-pads and cuts the century, and hands back anything it cannot parse untouched', () => {
    expect(formatDayNumeric('2026-06-04')).toBe('04/06/26');
    expect(formatDayNumeric('2026-12-31')).toBe('31/12/26');
    expect(formatDayNumeric('2026-6-4')).toBe('2026-6-4');
    expect(formatDayNumeric('not a date')).toBe('not a date');
  });
});

describe('each plan brings its OWN ruler, off the journal wire', () => {
  it('maps the stored week starts and puts them in week order', () => {
    const plan: JournalPlan = {
      plan_id: 2,
      name: 'Winter base',
      weeks: [
        { week_no: 2, start_date: '2025-11-09' },
        { week_no: 1, start_date: '2025-11-02' },
      ],
    };

    expect(journalPlanWeeks(plan)).toEqual([
      { weekNo: 1, startIso: '2025-11-02' },
      { weekNo: 2, startIso: '2025-11-09' },
    ]);
    expect(journalPlanWeeks(null)).toEqual([]);
  });

  it('rules a chart in the weeks it was HANDED and in no others', () => {
    const own = diaryChart(
      [entry('2026-01-19', { feel: 3 })],
      PLAN_START,
      weeksIn(3),
      weekStarts(4),
    );
    expect(own?.weeks.map((week) => week.weekNo)).toEqual([1, 2, 3, 4]);

    // ⚠️ Another plan's weeks are dated elsewhere, so not one of them lands on this axis —
    // which is what stops one plan's chart borrowing the ruler of the plan beside it.
    const other = diaryChart([entry('2026-01-19', { feel: 3 })], PLAN_START, weeksIn(3), [
      { weekNo: 1, startIso: '2024-03-04' },
    ]);
    expect(other?.weeks).toEqual([]);
  });
});

describe('a group’s axis is its own plan’s, and a group no plan claims has none', () => {
  it('runs from the plan’s first stored week to its last', () => {
    expect(groupSpan(weekStarts(6), [entry('2026-01-19', { feel: 3 })], TODAY)).toEqual({
      anchorIso: '2026-01-05',
      endIso: '2026-02-09',
    });
  });

  it('stops at today for a plan whose later weeks have not happened yet', () => {
    expect(groupSpan(weekStarts(20), [entry('2026-01-19', { feel: 3 })], TODAY).endIso).toBe(TODAY);
  });

  it('⚠️ gives an UNCLAIMED group its readings’ own extent and invents no ruler', () => {
    const entries = [entry('2025-01-01', { feel: 3 }), entry('2025-03-02', { skin: 4 })];
    const span = groupSpan([], entries, TODAY);

    // No weeks in, no ruler out — and the axis ends at the last reading rather than running on
    // to today, which would draw months this group does not cover.
    expect(span).toEqual({ anchorIso: null, endIso: '2025-03-02' });
    const chart = diaryChart(entries, span.anchorIso, span.endIso, []);
    expect(chart?.weeks).toEqual([]);
    expect(chart?.fromIso).toBe('2025-01-01');
    expect(chart?.toIso).toBe('2025-03-02');
  });
});

describe('the legend’s checkboxes are what decide the plot’s lines', () => {
  it('starts with every line and takes one off when it is unticked', () => {
    expect(ALL_SERIES_KEYS).toEqual(['feel', 'sleep_quality', 'skin']);
    expect(toggleSeries(ALL_SERIES_KEYS, 'sleep_quality')).toEqual(['feel', 'skin']);
  });

  it('re-ticks in DRAW ORDER, so the solid line never lands on top', () => {
    const shown = toggleSeries(toggleSeries(ALL_SERIES_KEYS, 'feel'), 'sleep_quality');

    expect(shown).toEqual(['skin']);
    expect(toggleSeries(shown, 'feel')).toEqual(['feel', 'skin']);
  });

  it('⚠️ REFUSES to untick the last one, so there is no way to reach a blank frame', () => {
    expect(toggleSeries(['skin'], 'skin')).toEqual(['skin']);
  });
});
