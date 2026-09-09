import { useState } from 'react';

import type { JournalEntry } from '../api/types';
import { formatDay } from '../plan/blueprint';
import { JournalFields } from '../session/JournalFields';
import type { JournalFieldValues } from '../session/journal';
import { useJournalPut } from '../session/journalApi';
import { Sheet } from '../ui/Sheet';

import { DIARY_ENTRY_HEADING_ID, buildEntryEdit, editBlocker, entryValues } from './entries';
import { EntryAttribution } from './EntryRow';

/** One entry in full, read-only, with an Edit that turns it into the diary box. The sheet, the
 *  focus contract and the Tab trap are `ui/Sheet.tsx`'s — the session player's own overlay. */

/** ⚠️ `canEdit` is FALSE for a demo principal and the control is then ABSENT, not disabled
 *  (issue #65). Reading the diary still works: the GET is not a mutating method. */
export function EntryDetail({
  entry,
  planName,
  phaseName,
  showBodyMetrics,
  canEdit,
  onClose,
}: {
  entry: JournalEntry;
  planName: string | null;
  phaseName: string | null;
  showBodyMetrics: boolean;
  canEdit: boolean;
  onClose: () => void;
}) {
  const [values, setValues] = useState<JournalFieldValues | null>(null);
  const put = useJournalPut();
  const blocker = values === null ? null : editBlocker(values, showBodyMetrics);

  async function save(edited: JournalFieldValues): Promise<void> {
    const variables = buildEntryEdit(entry, edited, showBodyMetrics);
    if (variables === null) return;
    try {
      await put.mutateAsync(variables);
    } catch {
      // `put.isError` says so below, with every word still in the form.
      return;
    }
    setValues(null);
  }

  return (
    <Sheet
      labelledBy={DIARY_ENTRY_HEADING_ID}
      onClose={onClose}
      actions={
        <>
          {values !== null && blocker === null ? (
            <button
              type="button"
              className="ct-app__button ct-app__button--primary"
              disabled={put.isPending}
              onClick={() => {
                void save(values);
              }}
            >
              {put.isPending ? 'Saving…' : 'Save this entry'}
            </button>
          ) : null}
          {values === null && canEdit ? (
            <button
              type="button"
              className="ct-app__button ct-app__button--primary"
              onClick={() => {
                setValues(entryValues(entry));
              }}
            >
              Edit
            </button>
          ) : null}
          <button type="button" className="ct-app__button" onClick={onClose}>
            Close
          </button>
        </>
      }
    >
      <section className="ct-app__card">
        <h2 id={DIARY_ENTRY_HEADING_ID}>{formatDay(entry.entry_date)}</h2>
        <p className="ct-app__tags">
          <EntryAttribution entry={entry} planName={planName} phaseName={phaseName} />
        </p>

        {values === null ? (
          <EntryReadout entry={entry} showBodyMetrics={showBodyMetrics} />
        ) : (
          <JournalFields
            idPrefix="ct-diary-edit"
            values={values}
            showBodyMetrics={showBodyMetrics}
            onChange={(patch) => {
              setValues({ ...values, ...patch });
            }}
          />
        )}

        {blocker === null ? null : <p className="ct-app__error">{blocker}</p>}
        {put.isError ? (
          <p className="ct-app__error" role="alert">
            That did not save. Every word you typed is still here — try again, or close this and
            nothing changes.
          </p>
        ) : null}
      </section>
    </Sheet>
  );
}

/** ⚠️ `entry.body` is USER-TYPED: a text node, never `dangerouslySetInnerHTML`, and not for
 *  markdown either. With body metrics off the weigh-in is absent here as everywhere. */
function EntryReadout({
  entry,
  showBodyMetrics,
}: {
  entry: JournalEntry;
  showBodyMetrics: boolean;
}) {
  return (
    <>
      {entry.body === null ? (
        <p className="ct-app__muted">Nothing written down for this day.</p>
      ) : (
        <p className="ct-app__prose">{entry.body}</p>
      )}
      <p className="ct-app__tags">
        <Score label="Energy" value={entry.feel} />
        <Score label="Sleep" value={entry.sleep_quality} />
        <Score label="Skin" value={entry.skin} />
      </p>
      {showBodyMetrics && entry.body_weight_kg !== null ? (
        <p className="ct-app__caption">{`What the scale said: ${entry.body_weight_kg} kg`}</p>
      ) : null}
    </>
  );
}

function Score({ label, value }: { label: string; value: number | null }) {
  return (
    <span className="ct-app__badge">{`${label}: ${value === null ? 'not said' : `${String(value)} of 5`}`}</span>
  );
}
