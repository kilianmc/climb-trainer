import type { CSSProperties } from 'react';
import { Fragment, useMemo } from 'react';

import type { PlanTree } from '../api/types';

import type { PhaseGuides } from './PhaseGuide';
import { phaseLabel } from './PhaseGuide';
import { planTimeline } from './timeline';

/* The plan's phases on one horizontal bar, in a scroller, at every width. The model is
   `timeline.ts`; every value here is `styles/_plan.scss`'s, from the signed-off preview. */

function span(from: number, to: number): CSSProperties {
  return { '--from': from, '--to': to } as CSSProperties;
}

/** ⚠️ The CALLOUT is the button, never the dot — a 44px target on a 1.6rem segment. The dot and
 *  the segment are `aria-hidden` presentation. */
export function PlanTimeline({
  plan,
  guides,
  todayIso,
  onSelect,
}: {
  plan: PlanTree;
  guides: PhaseGuides;
  todayIso: string;
  onSelect: (startWeek: number) => void;
}) {
  const timeline = useMemo(
    () => planTimeline(plan, todayIso, (phase) => phaseLabel(guides, phase)),
    [plan, todayIso, guides],
  );

  if (timeline.phases.length === 0) return null;

  return (
    // Focusable, or a keyboard user cannot scroll it; named, so the group is not entered blind.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="ct-app__tlscroll" tabIndex={0} role="group" aria-label={timeline.label}>
      {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- `list-style: none` drops list
          semantics in WebKit, and the phase items are `display: contents`. */}
      <ol
        className="ct-app__timeline"
        role="list"
        style={{ '--tracks': timeline.tracks, '--days': timeline.days } as CSSProperties}
      >
        {timeline.bands.map((band) => (
          <li
            className="ct-app__tlmonth"
            role="presentation"
            key={band.key}
            style={span(band.from, band.to)}
          >
            {band.label}
          </li>
        ))}

        {timeline.phases.map((phase) => (
          // eslint-disable-next-line jsx-a11y/no-redundant-roles -- `display: contents` strips it.
          <li className="ct-app__tlphase" role="listitem" key={phase.startWeek}>
            <span
              className="ct-app__tlseg"
              style={span(phase.from, phase.to)}
              data-current={phase.current ? 'true' : undefined}
              data-edge={phase.edge ?? undefined}
              aria-hidden="true"
            />
            <span
              className="ct-app__tldot"
              style={span(phase.from, phase.to)}
              data-current={phase.current ? 'true' : undefined}
              aria-hidden="true"
            />
            <button
              type="button"
              className="ct-app__tlmark"
              style={span(phase.from, phase.to)}
              data-side={phase.side}
              aria-label={phase.description}
              onClick={() => {
                onSelect(phase.startWeek);
              }}
            >
              <span className="ct-app__tlconnector" data-side={phase.side} aria-hidden="true" />
              <span className="ct-app__tlname">{phase.name}</span>
              <span className="ct-app__tldur">{phase.duration}</span>
            </button>
          </li>
        ))}

        {timeline.years.map((year) => (
          <Fragment key={year.key}>
            {/* Two grid items, never a wrapper: an `<li>` around them would take the placement
                and leave the rule and the label unplaced. */}
            {year.rule && (
              <li
                className="ct-app__tlrule"
                role="presentation"
                style={{ '--at': year.line } as CSSProperties}
                aria-hidden="true"
              />
            )}
            <li
              className="ct-app__tlyear"
              role="presentation"
              style={{ '--at': year.line } as CSSProperties}
            >
              {year.year}
            </li>
          </Fragment>
        ))}
      </ol>
    </div>
  );
}
