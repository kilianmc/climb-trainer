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
import { useCallback, useState } from 'react';

import { Sheet } from '../ui/Sheet';

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
  return (
    <Sheet
      labelledBy={JOURNAL_HEADING_ID}
      onClose={onClose}
      actions={
        <button type="button" className="ct-app__button ct-app__button--primary" onClick={onClose}>
          Close the notes
        </button>
      }
    >
      <SessionJournal run={run} readOnly={readOnly} />
    </Sheet>
  );
}
