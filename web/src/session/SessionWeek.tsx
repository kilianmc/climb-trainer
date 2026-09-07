import type { CSSProperties } from 'react';

import type { WeekDay, WeekView } from './week';

/* This calendar week, one row of seven days. It REUSES the plan screen's week table whole —
   the grid, the day blocks, the clipped codes, the caption legend — see `styles/_session.scss`. */

function cell(row: number, column: number): CSSProperties {
  return { '--rw': row, '--cw': column } as CSSProperties;
}

/** The aspect codes, and above them the completion word. `&__abbr` is `aria-hidden` and
 *  `&__full` is clipped rather than removed, so the full words stay in the accessible name. */
function Day({ day }: { day: WeekDay }) {
  if (day.aspects.length === 0) return <span className="ct-app__rest">Rest</span>;
  return (
    <div className="ct-app__day" data-completion={day.mark?.band}>
      {day.mark === null ? null : (
        <span className="ct-app__weekmark">
          <span className="ct-app__full">{day.mark.label}</span>
          <span className="ct-app__abbr" aria-hidden="true">
            {day.mark.short}
          </span>
        </span>
      )}
      {day.aspects.map((entry, line) => (
        <span className="ct-app__line" key={`${entry.key}:${String(line)}`}>
          <span className="ct-app__full">{entry.name}</span>
          <span className="ct-app__abbr" aria-hidden="true">
            {entry.code}
          </span>
        </span>
      ))}
    </div>
  );
}

/** ⚠️ Today is marked on the COLUMN HEADER, in the word and in the fill: the day block's own
 *  edge already carries the completion band, and two rings on one cell say nothing. */
export function SessionWeek({ week }: { week: WeekView }) {
  return (
    <table
      className="ct-app__weekgrid ct-app__weekcal ct-app__wide"
      role="table"
      aria-label="This week"
    >
      {week.legend.length === 0 ? null : (
        <caption style={cell(3, 1)}>
          {week.legend.map((entry, index) => (
            <span key={entry.key}>
              {index > 0 && <span aria-hidden="true"> · </span>}
              <strong>{entry.code}</strong> {entry.name.toLowerCase()}
            </span>
          ))}
        </caption>
      )}

      {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- `display: contents` strips it. */}
      <thead role="rowgroup">
        <tr role="row">
          {week.days.map((day) => (
            <th
              scope="col"
              role="columnheader"
              className="ct-app__weekhead"
              key={day.iso}
              data-today={day.isToday ? 'true' : undefined}
              style={cell(1, day.weekday + 1)}
            >
              {day.label}
              <span className="ct-app__weekdate">{day.isToday ? 'Today' : day.dayOfMonth}</span>
            </th>
          ))}
        </tr>
      </thead>

      {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- `display: contents` strips it. */}
      <tbody role="rowgroup">
        <tr role="row">
          {week.days.map((day) => (
            // eslint-disable-next-line jsx-a11y/no-interactive-element-to-noninteractive-role -- `display: contents` on the row strips the cell's own semantics; every level states its role.
            <td role="cell" key={day.iso} style={cell(2, day.weekday + 1)}>
              <Day day={day} />
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}
