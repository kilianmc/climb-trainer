import { useId } from 'react';

/**
 * The completion bar, its numbered rail, and the single polite live region that goes with it.
 *
 * The accessibility contract is fixed, and every clause is a real failure mode.
 * **`role="progressbar"` with an accessible NAME** — a nameless progressbar announces "42
 * percent" of nothing; the name comes from `aria-labelledby` pointing at the visible label, so
 * the two cannot drift. **Never colour alone** — the percentage is TEXT, which
 * `contrast.test.ts` already proves at 4.5:1 in both schemes, and the fill carries a hairline.
 * **One live region, announcing at step boundaries only**, rendered ALWAYS and empty when there
 * is nothing to say: a region added to the DOM at the same moment as its text is frequently not
 * announced. **The fill transition sits under `prefers-reduced-motion` while the number updates
 * instantly**, because reduced motion is not reduced information.
 *
 * ⚠️ **The rail IS the bar here, not a second opinion about it.** The spine carries the
 * `progressbar` role and the fill, the numbered nodes sit on that spine, and the percentage
 * stays as text in the head. A numbered rail *beside* a filled track says the same thing twice
 * in two units, which is how a stepper starts disagreeing with a progress bar.
 *
 * ⚠️ **The nodes are SIBLINGS of the progressbar, never children.** A `progressbar` element's
 * contents are presentational, so focusable children there are invalid ARIA — and these are
 * real buttons with real names. Callers that pass no nodes (the dashboard) get the plain bar.
 *
 * No `position: fixed` and no viewport units: both mounts share this route tree, and in the
 * federated mount both resolve against kilianmc.com's viewport.
 */
export interface ProgressNode {
  /** The step's own name, for the node's accessible name. The visible content is the number. */
  label: string;
  done: boolean;
  current?: boolean;
  /**
   * Where the node goes. **Optional, and its absence is a real answer**: step 0 is the account,
   * and the wizard has no Account card to send anyone to. A node with no destination renders as an
   * inert `<span>` rather than a disabled button — a disabled button is still announced as a
   * control, and this one is not a control at all.
   */
  onGo?: () => void;
}

interface RailItem {
  key: string;
  /** The accessible name: which step, and whether it is answered. */
  name: string;
  /** What is drawn in the circle — a digit, or the word "Finish". */
  content: string;
  /** The last step wears the word instead of a digit, and its pill is wider for it. */
  last: boolean;
  done: boolean;
  current?: boolean | undefined;
  onGo?: (() => void) | undefined;
}

export interface ProfileProgressProps {
  /** 0-100. Always a real count of what is done — see `completion.ts`. */
  percent: number;
  /** Visible and announced name of the bar. */
  label: string;
  /**
   * Announced politely when it changes. Pass a step-boundary sentence, or `null` where
   * there are no boundaries (the profile editor).
   */
  announcement?: string | null;
  /**
   * The numbered nodes, in order, starting at step 0 (the account). Omit for a plain bar.
   *
   * ⚠️ The LAST one is drawn as "Finish" rather than as its digit — it is the last step, and there
   * is no terminal node after it.
   */
  nodes?: ProgressNode[];
}

export function ProfileProgress({
  percent,
  label,
  announcement = null,
  nodes,
}: ProfileProgressProps) {
  const labelId = useId();

  /**
   * The rail, as one list — the numbered steps plus the Finish pill.
   *
   * ⚠️ **This is presentation, and it is deliberately not arithmetic on the percentage.** Where
   * the fill ENDS is now a function of which nodes are done; what the bar REPORTS is still
   * `percent`, straight from `completionPercent`, on the `role="progressbar"` element and in the
   * text above it. The two are separate on purpose: a fill that stops at a node's edge is a
   * rounding of geometry, and rounding the announced value to match it would turn a real 60% into
   * a made-up number. Nothing here feeds back into `percent`.
   */
  const items =
    nodes === undefined
      ? null
      : nodes.map((node, index) => {
          // ⚠️ **The last node IS the last step, not a terminal node after it** (Kilian, round
          // 11): "when we get to the last question we are in the finish line". So there is no
          // fifth node summarising the other four — Finish is Injuries, wearing a word instead of
          // a digit.
          const last = index === nodes.length - 1;
          return {
            key: node.label,
            // The visible content is a digit or the word, so the name carries the rest: which step
            // it is, and whether it is answered. A row of circles labelled "1" to "3" is a row of
            // unlabelled circles to anyone not looking at it.
            //
            // ⚠️ Numbered from ZERO, because step 0 is the account and it is what the 20% floor
            // credits. `20 + 80 × done/4` is identically `100 × (1 + done) / 5`, so the floor
            // already WAS one of five units done — the rail says so out loud rather than opening
            // on an empty groove while the account is genuinely complete.
            //
            // ⚠️ Finish names a STEP and its own state, exactly like its siblings. It used to
            // report what was outstanding across all of them, which was right for a terminal node
            // and is wrong for a step. The honesty rule still holds without it: this node is
            // unfilled until its own step is persisted, so the rail cannot read complete with a
            // real step unanswered — and `aria-valuenow` above is unchanged either way. "Finish"
            // leads the name because it is the visible text, which WCAG 2.5.3 requires the
            // accessible name to contain.
            name: last
              ? `Finish — step ${String(index)}: ${node.label} — ${node.done ? 'done' : 'not answered yet'}`
              : `Step ${String(index)}: ${node.label} — ${node.done ? 'done' : 'not answered yet'}`,
            content: last ? 'Finish' : String(index),
            last,
            done: node.done,
            current: node.current,
            onGo: node.onGo,
          };
        });

  return (
    <div className="ct-app__progress">
      <p className="ct-app__progress-head">
        <span id={labelId}>{label}</span>
        <span className="ct-app__progress-value">{percent}% complete</span>
      </p>

      <div className={nodes === undefined ? undefined : 'ct-app__rail'}>
        <div
          className="ct-app__progress-track"
          role="progressbar"
          aria-labelledby={labelId}
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          {/* ⚠️ **The percentage fill is the PLAIN bar's only, and the rail replaces it rather
              than sitting on top of it.** With nodes present the track stays as the unfilled
              groove and the rail's own connectors draw the reached part, so nothing paints
              through a node. The `aria-valuenow` above is untouched either way — see the note on
              `railItems`. */}
          {nodes === undefined && (
            <span className="ct-app__progress-fill" style={{ inlineSize: `${percent}%` }} />
          )}
        </div>

        {items !== null && (
          // ⚠️ **`<nav>` → `<ol>` → `<li>` with `aria-current="step"` is the fixed accessibility
          // contract**, and since round 10 this is where it lives: the separate step list is gone
          // (it repeated what the rail and the section headings already said), so the rail is now
          // both the progress visual AND the canonical stepper. Deleting the list without moving
          // the landmark here would have dropped the contract on the floor.
          <nav className="ct-app__rail-nav" aria-label="Profile steps">
            <ol className="ct-app__rail-nodes">
              {items.map((item, index) => (
                <li className="ct-app__rail-item" key={item.key}>
                  {/* The connector INTO this node, and it is what makes the fill stop at a node
                    instead of running under it: it is a flex child of the gap it occupies, so its
                    ends are the two nodes' edges by construction — no arithmetic, nothing to
                    round, and nothing that could drift from the reported value. Filled when the
                    node BEFORE it is done, i.e. the line advances to the last one reached. */}
                  {index > 0 && (
                    <span
                      className="ct-app__rail-link"
                      data-filled={items[index - 1]?.done === true ? 'true' : 'false'}
                    />
                  )}
                  <RailNode item={item} />
                </li>
              ))}
            </ol>
          </nav>
        )}
      </div>

      <p className="ct-app__sr-only" aria-live="polite">
        {announcement ?? ''}
      </p>
    </div>
  );
}

/**
 * One node: a real button where it has somewhere to go, an inert span where it does not.
 *
 * The number is the visible content, so the accessible name carries the rest — which step it is
 * and whether it is answered. A row of circles labelled "0" to "4" is a row of unlabelled circles
 * to anyone not looking at it.
 */
function RailNode({ item }: { item: RailItem }) {
  const className = [
    'ct-app__rail-node',
    item.last ? 'ct-app__rail-node--finish' : '',
    item.done ? 'ct-app__rail-node--done' : '',
  ]
    .filter((name) => name !== '')
    .join(' ');

  if (item.onGo === undefined) {
    return (
      <span className={className} aria-label={item.name} role="img">
        {item.content}
      </span>
    );
  }

  return (
    <button
      type="button"
      className={className}
      aria-label={item.name}
      {...(item.current === true ? { 'aria-current': 'step' as const } : {})}
      onClick={item.onGo}
    >
      {item.content}
    </button>
  );
}
