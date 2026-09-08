import { describe, expect, it } from 'vitest';

import { makeBlock, makeLibrary, makeSession, makeSet } from './fixtures';
import { buildJournalPut, isJournalDraftEmpty, parsedBodyWeightKg } from './journal';
import { compileProtocol } from './protocol';
import type { JournalDraft, RunRecord } from './runStore';
import { EMPTY_JOURNAL_DRAFT, createRun, parseRun } from './runStore';

/** The diary box's contract with `server/journal/routes.py` — no React, no fetch. An empty
 *  draft is never sent; a weigh-in ALONE is a real entry, which is why `body` is nullable. */

const START = Date.UTC(2026, 7, 28, 17, 0, 0);

function run(
  journal: Partial<JournalDraft> = {},
  loggedSessionId: number | null = null,
): RunRecord {
  const session = makeSession([
    makeBlock({
      protocol_kind: 'max_hang',
      exercise_id: 11,
      sets: [makeSet({ id: 501, set_index: 1, target_work_seconds: 10 })],
    }),
  ]);
  const record = createRun({
    occurredOn: '2026-08-28',
    discipline: 'boulder',
    plannedSessionId: 7,
    startedAtEpochMs: START,
    timeline: compileProtocol(session, makeLibrary()),
    preDoneBlockIndexes: [],
  });
  return { ...record, loggedSessionId, journal: { ...EMPTY_JOURNAL_DRAFT, ...journal } };
}

describe('what counts as something to write down', () => {
  it('treats a fresh draft as empty', () => {
    expect(isJournalDraftEmpty(EMPTY_JOURNAL_DRAFT)).toBe(true);
    expect(buildJournalPut(run())).toBeNull();
  });

  it('treats whitespace as nothing typed', () => {
    expect(isJournalDraftEmpty({ ...EMPTY_JOURNAL_DRAFT, body: '   \n\t ' })).toBe(true);
    expect(buildJournalPut(run({ body: '   ' }))).toBeNull();
  });

  it.each(['body', 'feel', 'sleepQuality', 'skin', 'bodyWeightKg'] as const)(
    'treats %s alone as a real entry, matching the CHECK',
    (field) => {
      const value = field === 'body' ? 'tweaky' : field === 'bodyWeightKg' ? '71.4' : 3;
      const draft = { ...EMPTY_JOURNAL_DRAFT, [field]: value };
      expect(isJournalDraftEmpty(draft)).toBe(false);
      expect(buildJournalPut(run(draft))).not.toBeNull();
    },
  );

  it('sends a weigh-in with NO body as a null body, never an empty string', () => {
    const body = buildJournalPut(run({ bodyWeightKg: '71.4' }));
    expect(body?.body).toBeNull();
    expect(body?.body_weight_kg).toBe(71.4);
  });
});

describe('the weigh-in the column will accept', () => {
  it.each([
    ['71.4', 71.4],
    ['20', 20],
    ['300', 300],
    ['  71.4  ', 71.4],
  ])('reads %s as %s', (raw, expected) => {
    expect(parsedBodyWeightKg(raw)).toBe(expected);
  });

  // ⚠️ `null`, not a 422: the column's CHECK is 20-300, so an out-of-range number is dropped
  // rather than sent — a 4xx would refuse the whole entry, text and all.
  it.each(['', '   ', 'abc', '19.9', '300.1', '0', '-5'])('reads %s as nothing', (raw) => {
    expect(parsedBodyWeightKg(raw)).toBeNull();
  });
});

describe('the PUT body', () => {
  it('is the whole entry, on the run’s own local date', () => {
    expect(
      buildJournalPut(
        run(
          { body: '  felt strong  ', feel: 4, sleepQuality: 5, skin: 2, bodyWeightKg: '71.4' },
          312,
        ),
      ),
    ).toEqual({
      entry_date: '2026-08-28',
      body: 'felt strong',
      feel: 4,
      sleep_quality: 5,
      skin: 2,
      body_weight_kg: 71.4,
      logged_session_id: 312,
    });
  });

  it('goes out UNLINKED rather than not at all while the session flush is still queued', () => {
    // Refusing to save what somebody typed because their sets have not landed is the one
    // outcome this box may not have. `logged_session_id` fills in on the next resubmission.
    expect(buildJournalPut(run({ body: 'offline note' }, null))?.logged_session_id).toBeNull();
  });
});

describe('surviving a failed write', () => {
  it('round-trips the typed text through the persisted record', () => {
    const typed = run({ body: 'fingers feel tweaky', feel: 2, bodyWeightKg: '71.' });
    const reloaded = parseRun(JSON.stringify(typed));
    expect(reloaded?.journal).toEqual(typed.journal);
    // ⚠️ "71." is kept verbatim: parsing per keystroke would make "71.4" untypeable.
    expect(reloaded?.journal.bodyWeightKg).toBe('71.');
  });

  it('discards a record whose draft is not a draft, rather than driving the box off it', () => {
    const broken = { ...run(), journal: { body: 42 } };
    expect(parseRun(JSON.stringify(broken))).toBeNull();
  });

  it('discards a draft with no `entryId`, rather than guessing Save or Update', () => {
    // The one field an edit must never clear is the one a stored record must always carry.
    const journal: Record<string, unknown> = { ...run().journal };
    delete journal.entryId;
    expect(parseRun(JSON.stringify({ ...run(), journal }))).toBeNull();
  });
});
