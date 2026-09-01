import type { PlanTree } from '../api/types';

import { MONTH_NAMES } from './blueprint';

/* The plan's own calendar as ONE grid measured in DAYS, so a phase segment and a month band are
   cut from the same ruler. `styles/_plan.scss` carries why weeks-times-a-constant cannot work. */

/* ⚠️ Pure and deterministic: today arrives as an ISO string, exactly as `phaseToggles.ts` takes
   it, and every date is arithmetic on integers — no `new Date()`, no local timezone. */

const DAYS_PER_WEEK = 7;
const MS_PER_DAY = 86_400_000;

/** A month's real overlap with the plan. `from`/`to` are GRID LINES, not days. */
export interface TimelineBand {
  readonly key: string;
  readonly label: string;
  readonly from: number;
  readonly to: number;
}

/** One mesocycle: the callout's words, its segment's grid lines, and its side of the bar. */
export interface TimelinePhase {
  readonly startWeek: number;
  readonly name: string;
  readonly duration: string;
  readonly weeks: string;
  readonly description: string;
  readonly current: boolean;
  readonly side: 'above' | 'below';
  readonly edge: 'start' | 'end' | null;
  readonly from: number;
  readonly to: number;
}

/** The far-left opening year carries no rule; each 1 January inside the plan carries one. */
export interface TimelineYear {
  readonly key: string;
  readonly year: number;
  readonly line: number;
  readonly rule: boolean;
}

export interface Timeline {
  readonly days: number;
  readonly tracks: string;
  readonly label: string;
  readonly bands: readonly TimelineBand[];
  readonly phases: readonly TimelinePhase[];
  readonly years: readonly TimelineYear[];
}

interface Day {
  readonly from: number;
  readonly to: number;
}

interface RawBand extends Day {
  readonly label: string;
  readonly year: number;
  readonly january: boolean;
}

interface RawPhase extends Day {
  readonly startWeek: number;
  readonly endWeek: number;
  readonly phase: string;
}

function parts(iso: string): readonly [number, number, number] {
  const [year, month, day] = iso.split('-').map(Number);
  return [year ?? 0, month ?? 1, day ?? 1];
}

/** Days since the epoch in UTC. `Date.UTC` is used as pure calendar arithmetic, never as a clock. */
function dayNumber(year: number, month: number, day: number): number {
  return Date.UTC(year, month - 1, day) / MS_PER_DAY;
}

function dayOf(iso: string): number {
  const [year, month, day] = parts(iso);
  return dayNumber(year, month, day);
}

function monthLabel(month: number): string {
  return (MONTH_NAMES[month - 1] ?? '').toUpperCase();
}

function weekWord(weeks: number): string {
  return weeks === 1 ? '1 week' : `${String(weeks)} weeks`;
}

/** Every month's REAL overlap with the plan, so a partial month at either end is a partial band. */
function monthBands(startIso: string, days: number): RawBand[] {
  const origin = dayOf(startIso);
  const [startYear, startMonth] = parts(startIso);
  const bands: RawBand[] = [];
  let year = startYear;
  let month = startMonth;

  while (dayNumber(year, month, 1) - origin < days) {
    const from = Math.max(dayNumber(year, month, 1) - origin, 0);
    const nextYear = month === 12 ? year + 1 : year;
    const nextMonth = month === 12 ? 1 : month + 1;
    const to = Math.min(dayNumber(nextYear, nextMonth, 1) - origin, days);
    if (to > from) {
      bands.push({ from, to, label: monthLabel(month), year, january: month === 1 });
    }
    year = nextYear;
    month = nextMonth;
  }
  return bands;
}

/* `end_week` is inclusive, as the phase badge's "Weeks 5–8" already reads. Clamped to the
   plan's own last day so a tree that disagreed with `week_count` cannot overrun the grid. */
function phaseSpans(plan: PlanTree, days: number): RawPhase[] {
  return plan.mesocycles
    .filter((mesocycle) => (mesocycle.start_week - 1) * DAYS_PER_WEEK < days)
    .map((mesocycle) => ({
      startWeek: mesocycle.start_week,
      endWeek: mesocycle.end_week,
      phase: mesocycle.phase,
      from: (mesocycle.start_week - 1) * DAYS_PER_WEEK,
      to: Math.min(mesocycle.end_week * DAYS_PER_WEEK, days),
    }));
}

/** The whole model. `label` resolves a phase key to the guide's own wording, which lives in the
 *  vocabulary rather than here. */
export function planTimeline(
  plan: PlanTree,
  todayIso: string,
  label: (phase: string) => string,
): Timeline {
  const days = Math.max(plan.week_count, 0) * DAYS_PER_WEEK;
  const bands = monthBands(plan.start_date, days);
  const spans = phaseSpans(plan, days);

  // The tracks are cut at the UNION of both boundary sets and sized in DAYS, which is the one
  // property that puts a 3-week phase on exactly 21/28 of a 28-day February.
  const cuts = [
    ...new Set([
      0,
      days,
      ...spans.flatMap((span) => [span.from, span.to]),
      ...bands.flatMap((band) => [band.from, band.to]),
    ]),
  ].sort((a, b) => a - b);
  const lines = new Map(cuts.map((cut, index) => [cut, index + 1]));
  const at = (offset: number): number => lines.get(offset) ?? 1;
  const tracks = cuts
    .slice(1)
    .map((cut, index) => `minmax(0, ${String(cut - (cuts[index] ?? 0))}fr)`)
    .join(' ');

  const today = dayOf(todayIso) - dayOf(plan.start_date);
  const last = spans.length - 1;

  const phases = spans.map((span, index): TimelinePhase => {
    const weeks = span.endWeek - span.startWeek + 1;
    const name = label(span.phase);
    const duration = weekWord(weeks);
    const range =
      weeks === 1
        ? `week ${String(span.startWeek)}`
        : `weeks ${String(span.startWeek)} to ${String(span.endWeek)}`;
    const current = today >= span.from && today < span.to;
    return {
      startWeek: span.startWeek,
      name,
      duration,
      weeks: range,
      description: `${name}, ${duration}, ${range}${current ? ', the phase you are in now' : ''}`,
      current,
      side: index % 2 === 0 ? 'above' : 'below',
      edge: index === 0 ? 'start' : index === last ? 'end' : null,
      from: at(span.from),
      to: at(span.to),
    };
  });

  const [startYear, startMonth] = parts(plan.start_date);
  const years: TimelineYear[] = [];
  // The opening year is omitted outright on a December start: it would fight the January label
  // a few days later for the same space. The 1 January rule below is unaffected either way.
  if (startMonth !== 12) {
    years.push({ key: 'start', year: startYear, line: 1, rule: false });
  }
  for (const band of bands) {
    if (band.january && band.from > 0) {
      years.push({
        key: `jan-${String(band.year)}`,
        year: band.year,
        line: at(band.from),
        rule: true,
      });
    }
  }

  return {
    days,
    tracks,
    label: `Plan timeline, ${String(phases.length)} ${phases.length === 1 ? 'phase' : 'phases'}, scrollable`,
    bands: bands.map((band): TimelineBand => ({
      key: `${String(band.year)}-${band.label}`,
      label: band.label,
      from: at(band.from),
      to: at(band.to),
    })),
    phases,
    years,
  };
}
