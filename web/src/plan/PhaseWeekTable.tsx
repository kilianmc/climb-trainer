import type { CSSProperties } from 'react';

import type { PlanMesocycle } from '../api/types';

import { WEEKDAY_LABELS, phaseWeeks } from './phaseWeek';

/* This phase, week by week: 7 weekday columns x one row per week, at every width. It never
   transposes — narrow shrinks the same grid. `styles/_plan.scss` carries the geometry. */

function cell(row: number, column: number): CSSProperties {
  return { '--rw': row, '--cw': column } as CSSProperties;
}

/** ⚠️ The legend is the table's own `<caption>`: FIRST in the DOM, as HTML requires, and last
 *  on screen via `caption-side: bottom`. `styles/_plan.scss` carries why. */
export function PhaseWeekTable({ mesocycle }: { mesocycle: PlanMesocycle }) {
  const model = phaseWeeks(mesocycle);
  if (model.rows.length === 0) return null;

  return (
    <table className="ct-app__weekgrid" role="table" aria-label="This phase week by week">
      <caption style={cell(model.rows.length + 2, 1)}>
        {model.legend.map((entry, index) => (
          <span key={entry.key}>
            {index > 0 && <span aria-hidden="true"> · </span>}
            <strong>{entry.code}</strong> {entry.name.toLowerCase()}
          </span>
        ))}
      </caption>

      {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- `display: contents` strips it. */}
      <thead role="rowgroup">
        <tr role="row">
          {/* No corner cell: the dead top-left `<th>` is simply not rendered. */}
          {WEEKDAY_LABELS.map((label, day) => (
            <th
              scope="col"
              role="columnheader"
              className="ct-app__weekhead"
              key={label}
              style={cell(1, day + 2)}
            >
              {label}
            </th>
          ))}
        </tr>
      </thead>

      {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- `display: contents` strips it. */}
      <tbody role="rowgroup">
        {model.rows.map((row, index) => (
          <tr role="row" key={row.weekNo}>
            <th scope="row" role="rowheader" className="ct-app__weekrow" style={cell(index + 2, 1)}>
              Week {row.weekNo}
            </th>
            {row.days.map((day) => (
              // eslint-disable-next-line jsx-a11y/no-interactive-element-to-noninteractive-role -- `display: contents` on the row strips the cell's own semantics; every level states its role.
              <td role="cell" key={day.weekday} style={cell(index + 2, day.weekday + 2)}>
                {day.aspects.length === 0 ? (
                  <span className="ct-app__rest">Rest</span>
                ) : (
                  <div className="ct-app__day">
                    {day.aspects.map((entry, line) => (
                      <span className="ct-app__line" key={`${entry.key}:${String(line)}`}>
                        {/* CLIPPED at narrow width, never `display: none`, so the full name stays
                            in the accessible name; the code is `aria-hidden`. */}
                        <span className="ct-app__full">{entry.name}</span>
                        <span className="ct-app__abbr" aria-hidden="true">
                          {entry.code}
                        </span>
                      </span>
                    ))}
                  </div>
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
