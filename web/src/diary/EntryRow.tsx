import type { ReactNode } from 'react';

import type { JournalEntry } from '../api/types';
import { formatDay } from '../plan/blueprint';
import { phaseCode } from '../plan/phaseWeek';

import { UNATTRIBUTED_LABEL } from './entries';

/** One entry as ONE line: its date, its plan, its own words, then its phase and its week, so the
 *  list can be filtered by eye (Kilian). `phaseName` comes from the vocabulary, never from here. */

export function EntryRow({
  entry,
  planName,
  phaseName,
  onOpen,
}: {
  entry: JournalEntry;
  planName: string | null;
  phaseName: string | null;
  onOpen: () => void;
}) {
  return (
    <li>
      <button type="button" className="ct-app__diaryrow" onClick={onOpen}>
        <span className="ct-app__diarydate">{formatDay(entry.entry_date)}</span>{' '}
        <EntryAttribution entry={entry} planName={planName} phaseName={phaseName}>
          <EntryWords body={entry.body} />
        </EntryAttribution>
      </button>
    </li>
  );
}

/** ⚠️ USER FREE TEXT, untrusted on OUTPUT: a text node, never an assembled HTML string. Where it
 *  stops is `text-overflow`, so the `…` lands at the row's real edge rather than at a count. */
function EntryWords({ body }: { body: string | null }) {
  const words = body?.trim() ?? '';
  // NORMAL: an entry can be only a weigh-in or only scores, and the rest of the row still reads.
  if (words === '') return null;
  return <span className="ct-app__diarytext">{words}</span>;
}

/** ⚠️ `planName` is USER-TYPED and a text node, resolved through `JournalResponse.plans` — the
 *  entry carries none. An unattributed entry says so plainly, and that is not an error. */
export function EntryAttribution({
  entry,
  planName,
  phaseName,
  children,
}: {
  entry: JournalEntry;
  planName: string | null;
  phaseName: string | null;
  /** The row slots its own words in here, between the plan and the phase; the sheet passes none. */
  children?: ReactNode;
}) {
  if (entry.plan === null) {
    return (
      <>
        <span className="ct-app__diarynone">{UNATTRIBUTED_LABEL}</span> {children}
      </>
    );
  }
  return (
    <>
      <span className="ct-app__diaryplan">{planName}</span> {children}{' '}
      <span className="ct-app__diaryphase">
        {/* `PhaseWeekTable`'s pair: the full name is CLIPPED rather than dropped, so it stays in
            the accessible name at every width, and the code is `aria-hidden`. */}
        <span className="ct-app__full">{phaseName ?? entry.plan.phase}</span>
        <span className="ct-app__abbr" aria-hidden="true">
          {phaseCode(entry.plan.phase)}
        </span>
      </span>{' '}
      <span className="ct-app__diaryweek">{`wk ${String(entry.plan.week_no)}`}</span>
    </>
  );
}
