/**
 * The mid-session notes overlay: the diary box, over the player, with the clock stopped.
 *
 * ⚠️ **The app's FIRST overlay, so it is the precedent every later one copies.** Focus moves in
 * on open and back to the opener on close, Tab cannot leave it, and the visible Close control in
 * the last row is the way out. Escape is wired too — but in the federated mount the shell's own
 * hook closes ITS view on Escape first, which is accepted (Kilian) and not worked around here.
 * ⚠️ **`togglePause` is a TOGGLE that no-ops when nothing is running, so nothing calls it
 * blindly**: this sheet gives back exactly the pause it took, and never a deliberate one.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { SessionJournal } from './SessionJournal';
import { JOURNAL_HEADING_ID } from './journal';
import type { SessionRun } from './useSessionRun';

/** Whether the sheet is open, and the two presses that move it. */
export interface SessionNotesState {
  readonly open: boolean;
  readonly openNotes: () => void;
  readonly closeNotes: () => void;
}

/** Open state plus the one pause this overlay owns. React state, deliberately: an unmount takes
 *  the sheet with it, and a forgotten pause leaves the clock STOPPED, never silently running. */
export function useSessionNotes(run: SessionRun): SessionNotesState {
  const { paused, togglePause } = run;
  const [state, setState] = useState({ open: false, ownsPause: false });

  const openNotes = useCallback((): void => {
    // ⚠️ A clock ALREADY stopped is left alone — a toggle would RESUME the pause the climber
    // chose — and otherwise the toggle's own answer is what close is allowed to give back.
    const ownsPause = paused ? false : togglePause();
    setState({ open: true, ownsPause });
  }, [paused, togglePause]);

  const closeNotes = useCallback((): void => {
    if (state.ownsPause) togglePause();
    setState({ open: false, ownsPause: false });
  }, [state.ownsPause, togglePause]);

  return { open: state.open, openNotes, closeNotes };
}

/** Everything inside the sheet a Tab could land on, in document order. A disabled control is
 *  excluded here rather than filtered after, so the in-flight Save button drops out on its own. */
const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/** Tab, wrapped — the whole of "the background is unreachable by keyboard". ⚠️ The sheet is
 *  `tabindex="-1"` and so NOT a stop: at open `index` is `-1`, and the first Tab moves inward. */
function trapTab(panel: HTMLElement, event: React.KeyboardEvent): void {
  const stops = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)];
  if (stops.length === 0) {
    // Nothing to move to: hold focus on the sheet rather than hand it to the screen behind.
    event.preventDefault();
    return;
  }
  const index = stops.findIndex((stop) => stop === document.activeElement);
  const forward = !event.shiftKey;
  const leaving = index === -1 || (forward ? index === stops.length - 1 : index === 0);
  if (!leaving) return;
  event.preventDefault();
  const target = forward ? stops[0] : stops.at(-1);
  target?.focus();
}

/** The sheet. ONE `SessionJournal` — the component the summary renders inline, against the same
 *  `run.journal` draft — so both placements write the one row the run's `client_uuid` keys. */
export function SessionNotes({
  run,
  readOnly,
  onClose,
}: {
  run: SessionRun;
  readOnly: boolean;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  // ⚠️ The opener is read at MOUNT and refocused on unmount, so no ref has to be threaded
  // through the player. `isConnected`: navigating away takes the opener with it.
  useEffect(() => {
    const opener = document.activeElement;
    panelRef.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>): void => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      const panel = panelRef.current;
      if (event.key === 'Tab' && panel !== null) trapTab(panel, event);
    },
    [onClose],
  );

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- a modal dialog's Escape and Tab trap belong on the sheet itself; there is no interactive element that could hold them, and the rule cannot tell this apart from a handler bolted onto a div in place of a button.
    <div
      ref={panelRef}
      className="ct-app__overlay"
      role="dialog"
      aria-modal="true"
      // The words already on screen name the sheet: the box's own heading, never a second copy.
      aria-labelledby={JOURNAL_HEADING_ID}
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <div className="ct-app__overlay-body">
        <SessionJournal run={run} readOnly={readOnly} />
      </div>
      {/* Last row, so it is on screen however far the form has scrolled — the player's own rule
          that a primary action lives at the bottom, where a thumb reaches it. */}
      <div className="ct-app__overlay-bar">
        <button type="button" className="ct-app__button ct-app__button--primary" onClick={onClose}>
          Close the notes
        </button>
      </div>
    </div>
  );
}
