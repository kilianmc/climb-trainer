import { useEffect, useRef } from 'react';

import { useProfileView } from '../profile/api';

import { JournalFields } from './JournalFields';
import type { JournalSaveOffer } from './journal';
import { JOURNAL_HEADING_ID, isJournalDraftEmpty, journalSaveOffer } from './journal';
import type { JournalDraft } from './runStore';
import type { SessionRun } from './useSessionRun';

/** The diary box: its OWN write like `SessionRpe`, and the text lives on the persisted run, so
 *  a failed one keeps every word. ⚠️ Both weigh-in rules are guarded by `journalBox.test.tsx`. */
export function SessionJournal({ run, readOnly }: { run: SessionRun; readOnly: boolean }) {
  const draft = run.journal;
  const { profile } = useProfileView();
  // ⚠️ An unread profile reads as OFF, never as ON: for this one setting, erring toward not
  // asking is the only safe direction, and the summary is reached long after `/api/profile`.
  const showBodyMetrics = profile?.show_body_metrics === true;
  const offer: JournalSaveOffer = readOnly ? 'none' : journalSaveOffer(draft);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const wasOffered = useRef(offer !== 'none');

  // ⚠️ Rescue focus ONLY when it is stranded on `<body>`, where React drops it after removing
  // the control just pressed — `__root.tsx`'s rule. Any other time, moving it would be a theft.
  useEffect(() => {
    const stranded = wasOffered.current && offer === 'none';
    wasOffered.current = offer !== 'none';
    if (!stranded) return;
    const active = document.activeElement;
    if (active === null || active === document.body) bodyRef.current?.focus();
  }, [offer]);

  return (
    <section className="ct-app__card">
      <h2 id={JOURNAL_HEADING_ID}>Anything worth writing down?</h2>
      <p className="ct-app__muted">
        For your own diary. Nobody else reads it, and every part of this is optional.
      </p>

      <JournalFields
        idPrefix="ct-journal"
        values={draft}
        showBodyMetrics={showBodyMetrics}
        bodyRef={bodyRef}
        onChange={run.setJournalDraft}
      />

      <JournalSaveState run={run} draft={draft} readOnly={readOnly} offer={offer} />
    </section>
  );
}

/** ⚠️ Five outcomes, five sentences — nothing written yet, saved, changed since saved, a 5xx
 *  that goes out again, and a 4xx that never will unedited. `SaveState`'s rule, in this box. */
function JournalSaveState({
  run,
  draft,
  readOnly,
  offer,
}: {
  run: SessionRun;
  draft: JournalDraft;
  readOnly: boolean;
  offer: JournalSaveOffer;
}) {
  const empty = isJournalDraftEmpty(draft);

  if (readOnly) {
    return (
      <p className="ct-app__notice" role="note">
        <span>
          Nothing is written down on the demo account, so this box saves nowhere. In your own
          account it would go straight into your diary.
        </span>
      </p>
    );
  }

  return (
    <>
      {draft.refusedAtEpochMs !== null ? (
        <p className="ct-app__error" role="alert">
          The server refused this entry, and sending it again unchanged could only be refused the
          same way. Every word you typed is still here — change something and save again.
        </p>
      ) : draft.savedAtEpochMs !== null ? (
        <p className="ct-app__status">Saved to your diary.</p>
      ) : empty ? (
        <p className="ct-app__muted">Nothing written down yet.</p>
      ) : offer === 'update' ? (
        <p className="ct-app__status ct-app__status--error" role="alert">
          Changed since you saved it. The new words are on this device — press Update to put them in
          your diary.
        </p>
      ) : (
        <p className="ct-app__status ct-app__status--error" role="alert">
          Not sent yet. It is saved on this device, so nothing you typed is lost — press Save to try
          again.
        </p>
      )}

      {/* ⚠️ ABSENT, not disabled, whenever a press would do nothing: an empty draft, one already
          saved unchanged, and a refusal that must never go out again unedited. */}
      {offer === 'none' ? null : (
        <div className="ct-app__actions">
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            disabled={run.isSavingJournal}
            onClick={run.saveJournal}
          >
            {run.isSavingJournal
              ? offer === 'update'
                ? 'Updating…'
                : 'Saving…'
              : offer === 'update'
                ? 'Update this entry'
                : 'Save this entry'}
          </button>
        </div>
      )}
    </>
  );
}
