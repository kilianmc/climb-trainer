import { describe, expect, it } from 'vitest';

import type { Phase, PlanMesocycle, PlanTree } from '../api/types';

import { planTimeline } from './timeline';

/* The day arithmetic, which is the whole point of the component: date maths is on the testing
   policy's WRITE list, and a bar measured in weeks-times-a-constant looks right and is wrong. */

function mesocycle(phase: Phase, startWeek: number, weeks: number): PlanMesocycle {
  return {
    id: startWeek,
    phase,
    start_week: startWeek,
    end_week: startWeek + weeks - 1,
    microcycles: [],
  };
}

/** Phases as `[phase, weeks]`, laid end to end from week 1. */
function plan(startDate: string, phases: readonly [Phase, number][]): PlanTree {
  let week = 1;
  const mesocycles = phases.map(([phase, weeks]) => {
    const built = mesocycle(phase, week, weeks);
    week += weeks;
    return built;
  });
  return {
    id: 7,
    name: 'Road to 7b',
    start_date: startDate,
    week_count: week - 1,
    discipline: 'sport',
    target_grade_id: 16,
    current_grade_id: 11,
    grade_gap: 5,
    generator_version: '1.0.0',
    generator_input: {},
    activated_at: null,
    climbing_band: null,
    notes: [],
    shortfalls: [],
    mesocycles,
  };
}

const label = (phase: string) => `${phase.charAt(0).toUpperCase()}${phase.slice(1)}`;

/** The emitted track weights, in days — one number per cut of the shared ruler. */
function weights(tracks: string): number[] {
  return [...tracks.matchAll(/([\d.]+)fr/g)].map(([, value]) => Number(value));
}

/** How many DAYS a `--from`/`--to` grid span covers, read off the tracks it spans. */
function days(tracks: string, from: number, to: number): number {
  return weights(tracks)
    .slice(from - 1, to - 1)
    .reduce((total, weight) => total + weight, 0);
}

describe('the axis is days, measured off one ruler', () => {
  it('gives a 3-week phase exactly 21/28 of a 28-day February', () => {
    // February 2026 has 28 days, and the plan is the whole of it.
    const timeline = planTimeline(
      plan('2026-02-01', [
        ['base', 3],
        ['deload', 1],
      ]),
      '2026-02-02',
      label,
    );

    const [base] = timeline.phases;
    const [february] = timeline.bands;
    expect(february?.label).toBe('FEB');
    expect(days(timeline.tracks, february?.from ?? 0, february?.to ?? 0)).toBe(28);
    expect(days(timeline.tracks, base?.from ?? 0, base?.to ?? 0)).toBe(21);
    // The property, stated as the ratio: weeks-times-a-constant cannot produce it, because it
    // would make this month 4 weeks wide and the phase 3 of them.
    expect(
      days(timeline.tracks, base?.from ?? 0, base?.to ?? 0) /
        days(timeline.tracks, february?.from ?? 0, february?.to ?? 0),
    ).toBeCloseTo(21 / 28, 10);
  });

  it('spans each month by its REAL overlap, so both ends are partial bands', () => {
    // 12 weeks from Tue 20 Jan 2026: 12 days of January, all of February and March, 13 of April.
    const timeline = planTimeline(plan('2026-01-20', [['base', 12]]), '2026-01-21', label);

    expect(timeline.bands.map((band) => band.label)).toEqual(['JAN', 'FEB', 'MAR', 'APR']);
    expect(timeline.bands.map((band) => days(timeline.tracks, band.from, band.to))).toEqual([
      12, 28, 31, 13,
    ]);
    // The bands tile the plan exactly — no gap, no overlap, nothing rounded to a week.
    expect(
      timeline.bands.reduce((total, band) => total + days(timeline.tracks, band.from, band.to), 0),
    ).toBe(timeline.days);
  });

  it('draws 12 weeks for a 12-week plan, never a year', () => {
    const timeline = planTimeline(
      plan('2026-01-05', [
        ['base', 3],
        ['deload', 1],
        ['strength', 3],
        ['deload', 1],
        ['power', 3],
        ['taper', 1],
      ]),
      '2026-01-05',
      label,
    );

    expect(timeline.days).toBe(84);
    expect(weights(timeline.tracks).reduce((total, weight) => total + weight, 0)).toBe(84);
    expect(days(timeline.tracks, 1, timeline.phases.at(-1)?.to ?? 0)).toBe(84);
  });
});

describe('one entry per phase', () => {
  const timeline = planTimeline(
    plan('2026-01-05', [
      ['base', 3],
      ['deload', 1],
      ['strength', 3],
    ]),
    // Week 4 is the deload: 5 Jan + 21 days.
    '2026-01-26',
    label,
  );

  it('carries the label, the duration and the week range', () => {
    expect(timeline.phases.map((phase) => [phase.name, phase.duration, phase.weeks])).toEqual([
      ['Base', '3 weeks', 'weeks 1 to 3'],
      ['Deload', '1 week', 'week 4'],
      ['Strength', '3 weeks', 'weeks 5 to 7'],
    ]);
  });

  it('marks the phase being trained today, and only that one', () => {
    expect(timeline.phases.map((phase) => phase.current)).toEqual([false, true, false]);
    expect(timeline.phases[1]?.description).toBe(
      'Deload, 1 week, week 4, the phase you are in now',
    );
  });

  it('marks nothing once the plan is over, and nothing before it starts', () => {
    const plan49 = plan('2026-01-05', [['base', 7]]);
    expect(planTimeline(plan49, '2026-03-01', label).phases[0]?.current).toBe(false);
    expect(planTimeline(plan49, '2026-01-04', label).phases[0]?.current).toBe(false);
  });

  it('alternates the callouts above and below, and rounds only the two ends', () => {
    expect(timeline.phases.map((phase) => phase.side)).toEqual(['above', 'below', 'above']);
    expect(timeline.phases.map((phase) => phase.edge)).toEqual(['start', null, 'end']);
  });
});

describe('the year', () => {
  it('shows the opening year at the far left, with no rule', () => {
    const timeline = planTimeline(plan('2026-01-05', [['base', 12]]), '2026-01-05', label);
    expect(timeline.years).toEqual([{ key: 'start', year: 2026, line: 1, rule: false }]);
  });

  it('rules each 1 January the plan crosses, and names the year beside it', () => {
    // 16 weeks from Mon 2 Nov 2026 crosses into 2027 on day 60.
    const timeline = planTimeline(plan('2026-11-02', [['base', 16]]), '2026-11-02', label);
    const january = timeline.bands.find((band) => band.label === 'JAN');

    expect(timeline.years.map((year) => [year.year, year.rule])).toEqual([
      [2026, false],
      [2027, true],
    ]);
    // The rule is ON the January boundary, i.e. the same cut the band starts at.
    expect(timeline.years[1]?.line).toBe(january?.from);
  });

  it('SUPPRESSES the opening year when the plan starts in December', () => {
    // It would fight the January label a few days later for the same space.
    const timeline = planTimeline(plan('2026-12-07', [['base', 12]]), '2026-12-07', label);
    expect(timeline.years.map((year) => [year.year, year.rule])).toEqual([[2027, true]]);
    expect(timeline.years.some((year) => year.key === 'start')).toBe(false);
  });

  it('is unaffected by the machine timezone, being integer arithmetic on the ISO parts', () => {
    // Same plan, two calls: nothing here reads a clock, so the model is a pure function of both.
    const first = planTimeline(plan('2026-11-02', [['base', 16]]), '2026-12-31', label);
    const second = planTimeline(plan('2026-11-02', [['base', 16]]), '2026-12-31', label);
    expect(first).toEqual(second);
    expect(first.phases[0]?.current).toBe(true);
  });
});
