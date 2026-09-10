import { useId, useMemo, useState } from 'react';

import type { JournalEntry } from '../api/types';
import { formatDay } from '../plan/blueprint';

import type { PlanWeek, ScoreKey, ScoreRow } from './chart';
import {
  ALL_SERIES_KEYS,
  CHART_VIEW,
  ORPHAN_STUB,
  PLOT,
  SERIES_NAMES,
  WEEK_LABEL_Y,
  WEEK_TICK,
  diaryChart,
  formatDayNumeric,
  formatKg,
  scoreRows,
  toggleSeries,
} from './chart';

/** One hand-drawn chart per plan section — there is no charting dependency and there must not be
 *  one. The weigh-in is a COLUMN of its table: kilograms cannot share a 1-5 axis (Kilian). */

/** ⚠️ Literals, never interpolated, and the dash pattern lives in CSS so a theme can see it. */
const LINE_CLASS: Record<ScoreKey, string> = {
  feel: 'ct-app__chartline ct-app__chartline--solid',
  sleep_quality: 'ct-app__chartline ct-app__chartline--dashes',
  skin: 'ct-app__chartline ct-app__chartline--dots',
};

/** The style as a WORD, and it is the SWATCH's accessible name: the stroke is the only identity
 *  these lines have, so a reader who cannot see it is told which one is which instead. */
const STYLE_WORD: Record<ScoreKey, string> = {
  feel: 'solid line',
  sleep_quality: 'dashed line',
  skin: 'dotted line',
};

/** The data channel, so no reading is gated behind reading a picture — the weigh-in included, and
 *  the ONLY place every one is listed. Built on open: a closed `details` still renders children. */
function ReadingsNumbers({
  rows,
  withWeight,
}: {
  rows: readonly ScoreRow[];
  /** ⚠️ `show_body_metrics`: the weigh-in column is ABSENT when it is off, header and cells. */
  withWeight: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return null;
  return (
    <details
      className="ct-app__disclosure"
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary>These readings, as numbers</summary>
      {open ? (
        <table className="ct-app__charttable">
          <thead>
            <tr>
              <th scope="col">Day</th>
              {SERIES_NAMES.map((name) => (
                <th key={name} scope="col">
                  {name}
                </th>
              ))}
              {withWeight ? <th scope="col">Weight</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.entryDate}-${String(row.id)}`}>
                <td>{formatDayNumeric(row.entryDate)}</td>
                {row.values.map((value, index) => (
                  <td key={String(index)}>{value === null ? '—' : value}</td>
                ))}
                {withWeight ? <td>{row.kg === null ? '—' : `${formatKg(row.kg)}kg`}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </details>
  );
}

export function WellbeingChart({
  entries,
  anchorIso,
  weeks,
  todayIso,
  showBodyMetrics,
}: {
  entries: readonly JournalEntry[];
  /** This span's first day — a plan's own start, or `null` to let the earliest reading anchor it. */
  anchorIso: string | null;
  /** THIS plan's stored week starts. Empty means no ruler — never a week this screen invented. */
  weeks: readonly PlanWeek[];
  /** This span's last day. Not always today: an old plan's chart ends where that plan does. */
  todayIso: string;
  /** ⚠️ `show_body_metrics`, and an unread profile reads as OFF: no weight figure and no weight
   *  column may reach this screen when it is off. */
  showBodyMetrics: boolean;
}) {
  const [shown, setShown] = useState<readonly ScoreKey[]>(ALL_SERIES_KEYS);
  // ⚠️ Per INSTANCE, so one plan's checkboxes cannot drive another's inputs by sharing an id.
  const legendId = useId();
  const chart = useMemo(
    () => diaryChart(entries, anchorIso, todayIso, weeks),
    [entries, anchorIso, todayIso, weeks],
  );
  const rows = useMemo(() => scoreRows(entries, showBodyMetrics), [entries, showBodyMetrics]);

  if (chart === null) {
    return (
      <>
        <h3>Health metrics</h3>
        <p className="ct-app__muted">
          Nothing scored yet. Every entry that rates how you felt, how you slept or your skin puts a
          mark on this chart.
        </p>
        <ReadingsNumbers rows={rows} withWeight={showBodyMetrics} />
      </>
    );
  }

  const span = `${formatDay(chart.fromIso)} to ${formatDay(chart.toIso)}`;
  const drawn = chart.series.filter((one) => shown.includes(one.key));
  const drawnReadings = drawn.reduce((total, one) => total + one.marks.length, 0);
  const ruled = chart.weeks.length > 0;
  return (
    <>
      <h3>Health metrics</h3>
      <div className="ct-app__chartbox">
        <div className="ct-app__chart">
          <svg
            className="ct-app__chartplot"
            viewBox={`0 0 ${String(CHART_VIEW.width)} ${String(CHART_VIEW.height)}`}
            role="img"
            aria-label={`${drawn.map((one) => one.name).join(', ')} from ${span} — ${String(drawnReadings)} readings on a 1 to 5 scale${ruled ? ', with a tick at every week of this plan' : ''}. The numbers are in the table under this chart.`}
          >
            {/* Scaffolding, not data: a tick per week, and a full-height rule only where a label
                lands, so the vertical ink tracks the LABELS rather than the weeks. */}
            {chart.weeks.map((week) => (
              <g key={week.weekNo}>
                <line
                  className="ct-app__chartweek"
                  vectorEffect="non-scaling-stroke"
                  x1={week.x}
                  x2={week.x}
                  y1={week.labelled ? PLOT.top : PLOT.bottom}
                  y2={PLOT.bottom + WEEK_TICK}
                />
                {week.labelled ? (
                  <text
                    className="ct-app__charttick"
                    x={week.x}
                    y={WEEK_LABEL_Y}
                    textAnchor={week.anchor}
                  >
                    {`wk ${String(week.weekNo)}`}
                  </text>
                ) : null}
              </g>
            ))}
            {chart.levels.map((level) => (
              <g key={level.value}>
                <line
                  className="ct-app__chartgrid"
                  vectorEffect="non-scaling-stroke"
                  x1={PLOT.start}
                  x2={PLOT.end}
                  y1={level.y}
                  y2={level.y}
                />
                <text
                  className="ct-app__charttick"
                  x={PLOT.start - 7}
                  y={level.y}
                  textAnchor="end"
                  dominantBaseline="middle"
                >
                  {level.value}
                </text>
              </g>
            ))}
            {drawn.map((one) => (
              <g key={one.key}>
                {one.path === '' ? null : (
                  <path
                    className={LINE_CLASS[one.key]}
                    vectorEffect="non-scaling-stroke"
                    d={one.path}
                  />
                )}
                {/* ⚠️ The lone reading a polyline cannot draw, as a stub of its OWN line — the
                    smallest thing that still reads as that line, and never a marker shape. */}
                {one.orphans.map((mark) => (
                  <line
                    key={mark.entryDate}
                    className={LINE_CLASS[one.key]}
                    vectorEffect="non-scaling-stroke"
                    x1={mark.x - ORPHAN_STUB / 2}
                    x2={mark.x + ORPHAN_STUB / 2}
                    y1={mark.y}
                    y2={mark.y}
                  />
                ))}
              </g>
            ))}
          </svg>
          <p className="ct-app__chartspan">
            <span>{formatDay(chart.fromIso)}</span>
            <span>{formatDay(chart.toIso)}</span>
          </p>
        </div>
        {/* ⚠️ A legend, not end labels: three integer series on five levels coincide constantly,
            so a label at the end of each line would sit on top of the other two. */}
        <ul className="ct-app__chartlegend">
          {chart.series.map((one) => {
            const checked = shown.includes(one.key);
            return (
              <li key={one.key}>
                <label className="ct-app__chartkeybox" htmlFor={`${legendId}-${one.key}`}>
                  <input
                    id={`${legendId}-${one.key}`}
                    type="checkbox"
                    checked={checked}
                    disabled={checked && shown.length === 1}
                    onChange={() => {
                      setShown(toggleSeries(shown, one.key));
                    }}
                  />
                  {/* ⚠️ NAMED, not hidden: the swatch draws the stroke for an eye, and the same
                      word is its accessible name for a reader who has only the name. */}
                  <svg
                    className="ct-app__chartswatch"
                    viewBox="0 0 20 20"
                    role="img"
                    aria-label={STYLE_WORD[one.key]}
                  >
                    <line className={LINE_CLASS[one.key]} x1={1} x2={19} y1={10} y2={10} />
                  </svg>
                  <span className="ct-app__chartkey">{one.name}</span>
                  {/* Not a style word but INFORMATION, so it stays visible text. */}
                  {one.marks.length === 0 ? (
                    <span className="ct-app__chartkeystyle">nothing scored yet</span>
                  ) : null}
                </label>
              </li>
            );
          })}
        </ul>
      </div>
      <ReadingsNumbers rows={rows} withWeight={showBodyMetrics} />
    </>
  );
}
