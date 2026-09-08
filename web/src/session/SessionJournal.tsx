import { useEffect, useRef } from 'react';

import { useProfileView } from '../profile/api';

import type { JournalSaveOffer } from './journal';
import {
  BODY_WEIGHT_MAX,
  BODY_WEIGHT_MIN,
  JOURNAL_BODY_MAX,
  JOURNAL_HEADING_ID,
  WELLBEING_VALUES,
  bodyWeightHint,
  isJournalDraftEmpty,
  journalSaveOffer,
} from './journal';
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
  const weightHint = bodyWeightHint(draft.bodyWeightKg);
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

      <label className="ct-app__field" htmlFor="ct-journal-body">
        How it went
        <textarea
          id="ct-journal-body"
          ref={bodyRef}
          className="ct-app__input"
          rows={4}
          maxLength={JOURNAL_BODY_MAX}
          placeholder="Fingers felt tweaky, backing off the crimps this week…"
          value={draft.body}
          onChange={(event) => run.setJournalDraft({ body: event.target.value })}
        />
      </label>

      <p className="ct-app__muted">On the three below, 1 is the worst it gets and 5 the best.</p>
      <ScoreField
        id="ct-journal-feel"
        label="How you feel"
        value={draft.feel}
        onPick={(feel) => run.setJournalDraft({ feel })}
      />
      <ScoreField
        id="ct-journal-sleep"
        label="Last night's sleep"
        value={draft.sleepQuality}
        onPick={(sleepQuality) => run.setJournalDraft({ sleepQuality })}
      />
      <ScoreField
        id="ct-journal-skin"
        label="Skin"
        value={draft.skin}
        onPick={(skin) => run.setJournalDraft({ skin })}
      />

      {showBodyMetrics ? (
        <>
          <label className="ct-app__field" htmlFor="ct-journal-weight">
            Weight today (kg)
            <input
              id="ct-journal-weight"
              className="ct-app__input"
              type="number"
              inputMode="decimal"
              step="0.1"
              min={BODY_WEIGHT_MIN}
              max={BODY_WEIGHT_MAX}
              placeholder="e.g. 71.4"
              value={draft.bodyWeightKg}
              onChange={(event) => run.setJournalDraft({ bodyWeightKg: event.target.value })}
            />
          </label>
          {weightHint === null ? (
            <p className="ct-app__muted">
              Just what the scale said today. It is recorded, never scored — nothing in this app
              asks you to change it.
            </p>
          ) : (
            <p className="ct-app__error">{weightHint}</p>
          )}
        </>
      ) : null}

      <JournalSaveState run={run} draft={draft} readOnly={readOnly} offer={offer} />
    </section>
  );
}

/** One 1-5 select on the shared `ct-app__select` primitive — `SessionRpe`'s markup exactly,
 *  because five buttons in a row is a wall on a phone and the chevron is drawn once. */
function ScoreField({
  id,
  label,
  value,
  onPick,
}: {
  id: string;
  label: string;
  value: number | null;
  onPick: (value: number | null) => void;
}) {
  return (
    <label className="ct-app__field" htmlFor={id}>
      {label}
      <span className="ct-app__select">
        <select
          id={id}
          className="ct-app__input"
          value={value ?? ''}
          onChange={(event) => {
            const picked = Number(event.target.value);
            onPick(Number.isFinite(picked) && picked > 0 ? picked : null);
          }}
        >
          <option value="">Rather not say</option>
          {WELLBEING_VALUES.map((score) => (
            <option key={score} value={score}>
              {String(score)}
            </option>
          ))}
        </select>
      </span>
    </label>
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
