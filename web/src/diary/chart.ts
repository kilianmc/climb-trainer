import type { JournalEntry, JournalPlan, PlanTree } from '../api/types';

/** feel, sleep and skin as RAW readings over ONE span, told apart by STROKE STYLE alone. Pure —
 *  every date arrives as an ISO string and every comparison is integer or string arithmetic. */

/** MEASURED for FIT at 2.42:1 — 118px tall at the mobile size, and 1008x416 at the `26rem` BLOCK
 *  bound in `_diary.scss`, which is the axis Kilian asked for the bound to be on. */
export const CHART_VIEW = { width: 320, height: 132 } as const;

/** `start` carries the 1-5 labels; `bottom` carries the week ruler and the `wk N` row. */
const PAD = { start: 24, end: 12, top: 12, bottom: 22 } as const;

/** The plot's own edges, so the grid, the lines and the week ruler share one ruler. */
export const PLOT = {
  start: PAD.start,
  end: CHART_VIEW.width - PAD.end,
  top: PAD.top,
  bottom: CHART_VIEW.height - PAD.bottom,
} as const;

/** The ruler tick under the plot, the stub a lone reading gets, and the `wk N` baseline. */
export const WEEK_TICK = 4;
export const ORPHAN_STUB = 10;
export const WEEK_LABEL_Y = CHART_VIEW.height - 5;

const MS_PER_DAY = 86_400_000;

/** The axis is the columns' own `CHECK (BETWEEN 1 AND 5)` and never the readings' range: a week
 *  of 4s and 5s must not stretch to fill the frame as though it were the whole scale. */
const SCORE_MIN = 1;
const SCORE_MAX = 5;

/** Every level gets a gridline and a label: five discrete steps, all of them meaningful. */
export const SCORE_LEVELS: readonly number[] = Array.from(
  { length: SCORE_MAX - SCORE_MIN + 1 },
  (_unused, index) => SCORE_MIN + index,
);

/** MEASURED: `wk 40` is ~29 user units at 11px, so 40 leaves a third of a label clear. The plot
 *  is ONE viewBox scaled to its column, so labels and gaps scale together at every width. */
export const LABEL_GAP_MIN = 40;

/** Half a label, so the end ones are anchored inwards instead of clipped. */
const LABEL_HALF = 15;

/** Never EVERY week (Kilian), and each stride doubles, so an eight-week plan and a forty-week
 *  one get different densities rather than one hard-coded "every fourth". */
const LABEL_STEPS: readonly number[] = [2, 4, 8, 16, 32];

export type ScoreKey = 'feel' | 'sleep_quality' | 'skin';

export interface ScoreMark {
  readonly entryDate: string;
  readonly value: number;
  readonly x: number;
  readonly y: number;
}

export interface ScoreSeries {
  readonly key: ScoreKey;
  readonly name: string;
  /** `''` when this metric was never scored — the legend says so and no line is drawn. */
  readonly path: string;
  readonly marks: readonly ScoreMark[];
  /** ⚠️ Readings the path cannot draw. A polyline needs two points, so a lone reading would be
   *  blank canvas: these get a stub in the series' own stroke style, never a marker. */
  readonly orphans: readonly ScoreMark[];
}

export interface ChartLevel {
  readonly value: number;
  readonly y: number;
}

/** One week boundary as the SERVER dated it. `startIso` is a real week start, not `span / 7`. */
export interface PlanWeek {
  readonly weekNo: number;
  readonly startIso: string;
}

/** A week boundary placed on the axis. Only a subset is `labelled`; the rest is ruler. */
export interface WeekTick {
  readonly weekNo: number;
  readonly x: number;
  readonly labelled: boolean;
  readonly anchor: 'start' | 'middle' | 'end';
}

export interface DiaryChart {
  /** The span's ends, for the end labels. The PLAN's dates, not the readings' extent. */
  readonly fromIso: string;
  readonly toIso: string;
  /** DRAW ORDER, and it is load-bearing: solid underneath, dashed over it, dotted on top, so
   *  the gaps in the upper strokes are what reveal a lower line where two coincide. */
  readonly series: readonly ScoreSeries[];
  readonly levels: readonly ChartLevel[];
  readonly weeks: readonly WeekTick[];
  readonly readings: number;
}

/** Identity is the LINE STYLE, never the hue: `_tokens.scss` has no categorical palette and the
 *  only hues clearing 4.5:1 on a card are the reserved status ones. */
const SERIES: readonly { key: ScoreKey; name: string }[] = [
  { key: 'feel', name: 'Energy' },
  { key: 'sleep_quality', name: 'Sleep' },
  { key: 'skin', name: 'Skin' },
];

/** Calendar arithmetic on integers, never a clock — `plan/timeline.ts`'s rule. */
function dayOf(iso: string): number {
  const [year, month, day] = iso.split('-').map(Number);
  return Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1) / MS_PER_DAY;
}

/** An ISO day compares chronologically as a STRING, so the span's ends need no `Date` at all. */
const earlier = (left: string, right: string): string => (left < right ? left : right);
const later = (left: string, right: string): string => (left > right ? left : right);

function levelY(value: number): number {
  const up = (value - SCORE_MIN) / (SCORE_MAX - SCORE_MIN);
  return PLOT.bottom - up * (PLOT.bottom - PLOT.top);
}

/** ⚠️ `entries` arrives NEWEST first from the server, so nothing here may assume an order. `id`
 *  breaks the tie: two entries can share a day and a line needs a total order. */
function oldestFirst(entries: readonly JournalEntry[]): readonly JournalEntry[] {
  return [...entries].sort((left, right) =>
    left.entry_date === right.entry_date
      ? left.id - right.id
      : left.entry_date < right.entry_date
        ? -1
        : 1,
  );
}

function isScored(entry: JournalEntry): boolean {
  return entry.feel !== null || entry.sleep_quality !== null || entry.skin !== null;
}

/** The ACTIVE plan's week starts, off `GET /api/plans/active`. The client re-derives NO training
 *  rule here: where a week begins is the server's fact, and this only flattens and sorts it. */
export function planWeeks(plan: PlanTree | null | undefined): readonly PlanWeek[] {
  return (plan?.mesocycles ?? [])
    .flatMap((meso) => meso.microcycles)
    .map((cycle) => ({ weekNo: cycle.week_no, startIso: cycle.start_date }))
    .sort((left, right) => (left.startIso < right.startIso ? -1 : 1));
}

/** ONE plan's week starts off `JournalResponse.plans` — the only ruler an OLDER plan has, since
 *  `/api/plans/active` reaches the active one alone. Same stored dates, same no-deriving rule. */
export function journalPlanWeeks(plan: JournalPlan | null | undefined): readonly PlanWeek[] {
  return (plan?.weeks ?? [])
    .map((week) => ({ weekNo: week.week_no, startIso: week.start_date }))
    .sort((left, right) => (left.startIso < right.startIso ? -1 : 1));
}

/** One group's own axis. A plan group runs from its first stored week to its last, clamped to
 *  today; a group NO plan claims has no weeks, so its span is its own readings' extent. */
export function groupSpan(
  weeks: readonly PlanWeek[],
  entries: readonly JournalEntry[],
  todayIso: string,
): { readonly anchorIso: string | null; readonly endIso: string } {
  const lastWeek = weeks.at(-1)?.startIso;
  if (lastWeek === undefined) {
    // ⚠️ No ruler to invent and no reason to run to today: these entries are part of no plan,
    // so empty canvas past the newest of them would imply a stretch they do not cover.
    const newest = oldestFirst(entries).at(-1)?.entry_date;
    return { anchorIso: null, endIso: newest ?? todayIso };
  }
  return { anchorIso: weeks[0]?.startIso ?? null, endIso: earlier(lastWeek, todayIso) };
}

/** ⚠️ A reading with no neighbour is the one the path drops: `M x y` on its own paints nothing.
 *  Every other reading is joined by that path, so nothing else may take a mark. */
function orphansOf(marks: readonly ScoreMark[]): readonly ScoreMark[] {
  return marks.length === 1 ? marks : [];
}

/** How many ticks per label, from the CLOSEST pair actually placed — so the density follows the
 *  span. Two ticks can always carry both labels; a third is what starts the thinning. */
function labelStep(xs: readonly number[]): number {
  if (xs.length < 3) return 1;
  let closest = Number.POSITIVE_INFINITY;
  for (let index = 1; index < xs.length; index += 1) {
    closest = Math.min(closest, (xs[index] ?? 0) - (xs[index - 1] ?? 0));
  }
  return LABEL_STEPS.find((step) => closest * step >= LABEL_GAP_MIN) ?? LABEL_STEPS.at(-1) ?? 1;
}

function anchorOf(x: number): 'start' | 'middle' | 'end' {
  if (x < PLOT.start + LABEL_HALF) return 'start';
  return x > PLOT.end - LABEL_HALF ? 'end' : 'middle';
}

/** ⚠️ Every tick is one of that PLAN's own week starts, filtered to the span — never `span / 7`,
 *  which would draw a boundary the plan does not have. No weeks in, no ruler at all. */
function weekRuler(
  weekStarts: readonly PlanWeek[],
  fromIso: string,
  toIso: string,
  placeX: (iso: string) => number,
): readonly WeekTick[] {
  const inside = weekStarts.filter((week) => week.startIso >= fromIso && week.startIso <= toIso);
  const xs = inside.map((week) => placeX(week.startIso));
  const step = labelStep(xs);
  return inside.map((week, index) => {
    const x = xs[index] ?? PLOT.start;
    return { weekNo: week.weekNo, x, labelled: index % step === 0, anchor: anchorOf(x) };
  });
}

/** `null` when not one 1-5 reading was ever written: the caller renders a sentence, not a frame.
 *  `anchorIso` is this span's first day, or `null` to let the earliest reading anchor it. */
export function diaryChart(
  entries: readonly JournalEntry[],
  anchorIso: string | null,
  todayIso: string,
  weekStarts: readonly PlanWeek[] = [],
): DiaryChart | null {
  const dated = oldestFirst(entries);
  const scored = dated.filter(isScored);
  const first = scored[0];
  const last = scored.at(-1);
  if (first === undefined || last === undefined) return null;

  // ⚠️ The span is the PLAN's, widened ONLY to keep a reading dated outside it on the canvas:
  // an entry attributed through its own SESSION can be dated before the plan's first day.
  const anchor = anchorIso ?? dated[0]?.entry_date ?? first.entry_date;
  const fromIso = earlier(anchor, first.entry_date);
  const toIso = later(todayIso, last.entry_date);

  const span = dayOf(toIso) - dayOf(fromIso);
  const across = PLOT.end - PLOT.start;
  // A one-day span puts its readings at the trailing edge, which is where today is.
  const placeX = (iso: string): number =>
    PLOT.start + (span === 0 ? 1 : (dayOf(iso) - dayOf(fromIso)) / span) * across;

  const series = SERIES.map((definition): ScoreSeries => {
    const marks = scored.flatMap((entry): ScoreMark[] => {
      const value = entry[definition.key];
      if (value === null) return [];
      return [
        { entryDate: entry.entry_date, value, x: placeX(entry.entry_date), y: levelY(value) },
      ];
    });
    return {
      ...definition,
      marks,
      orphans: orphansOf(marks),
      path: marks
        .map((mark, index) => `${index === 0 ? 'M' : 'L'}${mark.x.toFixed(2)} ${mark.y.toFixed(2)}`)
        .join(' '),
    };
  });

  return {
    fromIso,
    toIso,
    series,
    levels: SCORE_LEVELS.map((value): ChartLevel => ({ value, y: levelY(value) })),
    weeks: weekRuler(weekStarts, fromIso, toIso, placeX),
    readings: series.reduce((total, one) => total + one.marks.length, 0),
  };
}

/** Every dated row the table view lists, oldest first: one cell per metric, then the weigh-in. */
export interface ScoreRow {
  readonly entryDate: string;
  readonly id: number;
  readonly values: readonly (number | null)[];
  /** The wire's own `Decimal` string, `null` when that day holds no weigh-in. */
  readonly kg: string | null;
}

/** The chart's data channel, so no reading is gated behind reading a picture. ⚠️ EVERY series,
 *  whatever the legend's checkboxes hide: the table is the channel for a reader who cannot see. */
export function scoreRows(
  entries: readonly JournalEntry[],
  withWeight = false,
): readonly ScoreRow[] {
  // ⚠️ `withWeight` widens the ROW SET too: the table is the only place every weigh-in is
  // listed, so an entry that scored nothing still owes a row or its weigh-in is lost.
  return oldestFirst(entries)
    .filter((entry) => isScored(entry) || (withWeight && entry.body_weight_kg !== null))
    .map((entry) => ({
      entryDate: entry.entry_date,
      id: entry.id,
      values: SERIES.map((definition) => entry[definition.key]),
      kg: entry.body_weight_kg,
    }));
}

/** The column names the table and the legend share, in draw order. */
export const SERIES_NAMES: readonly string[] = SERIES.map((definition) => definition.name);

/** Draw order as KEYS, which is also the legend's order and every chart's starting state. */
export const ALL_SERIES_KEYS: readonly ScoreKey[] = SERIES.map((definition) => definition.key);

/** Which series the plot draws. ⚠️ Unticking the LAST one is REFUSED rather than drawn as an
 *  empty frame, and re-ticking restores draw order so the solid line never lands on top. */
export function toggleSeries(shown: readonly ScoreKey[], key: ScoreKey): readonly ScoreKey[] {
  if (!shown.includes(key)) {
    return ALL_SERIES_KEYS.filter((one) => one === key || shown.includes(one));
  }
  return shown.length === 1 ? shown : shown.filter((one) => one !== key);
}

/** `2026-06-04` -> `04/06/26`, for the readings table's Day column. ⚠️ From the string's own
 *  PARTS like `formatDay`: a date-only string parses as UTC midnight, a day early west of GMT. */
export function formatDayNumeric(iso: string): string {
  const [year, month, day] = iso.split('-');
  if (year === undefined || month === undefined || day === undefined) return iso;
  if (year.length !== 4 || month.length !== 2 || day.length !== 2) return iso;
  return `${day}/${month}/${year.slice(-2)}`;
}

/** One decimal, and the wire string untouched when it is not a number this can read. */
export function formatKg(value: number | string): string {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(1) : String(value);
}
