import type { JournalEntryRequest } from '../api/types';

import type { JournalDraft, RunRecord } from './runStore';

/** The diary box's pure half, pure like `outbox.ts` so the whole write path is a unit test.
 *  ⚠️ The five fields here are exactly the ones `journal_entry`'s `not_empty` CHECK counts. */

/** The box's own heading, so the overlay wrapping it is `aria-labelledby` the words already on
 *  screen. One constant, because a renamed heading would otherwise leave the sheet nameless. */
export const JOURNAL_HEADING_ID = 'ct-journal-heading';

/** `server/models.py::JOURNAL_BODY_MAX`, mirrored so the control can stop before the server does. */
export const JOURNAL_BODY_MAX = 4000;

/** The 1-5 scale behind `feel`, `sleep_quality` and `skin`. One-based: `0` is not in the CHECK. */
export const WELLBEING_VALUES = [1, 2, 3, 4, 5] as const;

/** `journal_entry.body_weight_kg`'s own `CHECK (BETWEEN 20 AND 300)`, mirrored at the edge. */
export const BODY_WEIGHT_MIN = 20;
export const BODY_WEIGHT_MAX = 300;

/** The typed weigh-in as a number, or `null` for blank, unparseable or outside the column's
 *  range. One function, so the hint below and the PUT can never disagree about a value. */
export function parsedBodyWeightKg(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return null;
  if (value < BODY_WEIGHT_MIN || value > BODY_WEIGHT_MAX) return null;
  return value;
}

/** What to say under the weigh-in field, or `null` when there is nothing to say. */
export function bodyWeightHint(raw: string): string | null {
  if (raw.trim() === '' || parsedBodyWeightKg(raw) !== null) return null;
  return `A weigh-in is a number between ${String(BODY_WEIGHT_MIN)} and ${String(BODY_WEIGHT_MAX)} kg.`;
}

/** Nothing to send: every one of the CHECK's five fields is absent. */
export function isJournalDraftEmpty(draft: JournalDraft): boolean {
  return (
    draft.body.trim() === '' &&
    draft.feel === null &&
    draft.sleepQuality === null &&
    draft.skin === null &&
    parsedBodyWeightKg(draft.bodyWeightKg) === null
  );
}

/** What pressing the box's one control would actually do. `'none'` means it could do nothing,
 *  and a control that cannot do anything must not be on screen (Kilian). */
export type JournalSaveOffer = 'none' | 'save' | 'update';

export function journalSaveOffer(draft: JournalDraft): JournalSaveOffer {
  // `buildJournalPut` returns `null` here, so the press could only refuse itself.
  if (isJournalDraftEmpty(draft)) return 'none';
  // Never resent UNEDITED — `outbox.ts::quarantine`. An edit is what clears this mark.
  if (draft.refusedAtEpochMs !== null) return 'none';
  // What is on screen is what the server acked. There is nothing left to send.
  if (draft.savedAtEpochMs !== null) return 'none';
  // ⚠️ A 4xx sets no `entryId`, so a refusal that was then edited offers Save, never Update:
  // nothing landed, so that press CREATES the row rather than editing one.
  return draft.entryId === null ? 'save' : 'update';
}

/** The body of `PUT /api/journal/{client_uuid}`, or `null` when there is nothing to write —
 *  `mintSet`'s rule, since the `not_empty` CHECK would refuse it and a 4xx never succeeds. */
export function buildJournalPut(run: RunRecord): JournalEntryRequest | null {
  const draft = run.journal;
  if (isJournalDraftEmpty(draft)) return null;
  const body = draft.body.trim();
  return {
    entry_date: run.occurredOn,
    body: body === '' ? null : body,
    feel: draft.feel,
    sleep_quality: draft.sleepQuality,
    skin: draft.skin,
    body_weight_kg: parsedBodyWeightKg(draft.bodyWeightKg),
    // `null` until a flush is acked. An unlinked entry beats refusing to save what somebody
    // typed because their sets are still queued; a later resubmission fills the link in.
    logged_session_id: run.loggedSessionId,
  };
}
