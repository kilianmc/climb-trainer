import { describe, expect, it } from 'vitest';

import type { JournalEntry, JournalPlan } from '../api/types';

import {
  buildEntryEdit,
  editBlocker,
  entryValues,
  groupByPlan,
  sortEntries,
  sortPlanGroups,
} from './entries';

/** ⚠️ The two data-loss guards of the edit path, as units: an edit must resubmit THAT entry's
 *  own `client_uuid`, and must not erase a weigh-in the form never showed. */

const UUID_A = '11111111-1111-4111-8111-111111111111';
const UUID_B = '22222222-2222-4222-8222-222222222222';

function entry(overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: 1,
    client_uuid: UUID_A,
    entry_date: '2026-05-12',
    body: 'crimps felt sharp',
    feel: 4,
    sleep_quality: 3,
    skin: 2,
    body_weight_kg: '71.4',
    logged_session_id: 909,
    plan: { plan_id: 7, phase: 'strength', week_no: 3 },
    ...overrides,
  };
}

describe('an edit replaces THIS entry rather than minting a second one', () => {
  it('resubmits the entry’s own client_uuid', () => {
    const stored = entry({ client_uuid: UUID_B });
    const variables = buildEntryEdit(stored, entryValues(stored), true);
    // ⚠️ A fresh uuid would leave TWO rows for one day: the PUT is keyed on this value.
    expect(variables?.clientUuid).toBe(UUID_B);
  });

  it('keeps the entry’s own date and its session link, which no form shows', () => {
    const stored = entry({ entry_date: '2026-01-02', logged_session_id: 4242 });
    const variables = buildEntryEdit(stored, entryValues(stored), true);
    expect(variables?.body.entry_date).toBe('2026-01-02');
    expect(variables?.body.logged_session_id).toBe(4242);
  });

  it('sends nothing at all when every field has been emptied', () => {
    const values = { body: '  ', feel: null, sleepQuality: null, skin: null, bodyWeightKg: '' };
    expect(buildEntryEdit(entry(), values, true)).toBeNull();
  });
});

describe('a weigh-in survives an edit made with body metrics OFF', () => {
  it('round-trips the STORED weight verbatim', () => {
    const stored = entry({ body_weight_kg: '71.4' });
    const values = { ...entryValues(stored), body: 'edited with the setting off' };
    const variables = buildEntryEdit(stored, values, false);
    // ⚠️ THE GUARD. The PUT replaces whole, and with the setting off no weight is rendered
    // anywhere — so `null` here would silently erase a number the climber cannot see.
    expect(variables?.body.body_weight_kg).toBe('71.4');
  });

  it('ignores whatever the form holds — an unseeded draft cannot erase it either', () => {
    const stored = entry({ body_weight_kg: '71.4' });
    const values = { ...entryValues(stored), bodyWeightKg: '' };
    expect(buildEntryEdit(stored, values, false)?.body.body_weight_kg).toBe('71.4');
  });

  it('leaves a stored NULL null, rather than inventing one', () => {
    const stored = entry({ body_weight_kg: null });
    const variables = buildEntryEdit(stored, entryValues(stored), false);
    expect(variables?.body.body_weight_kg).toBeNull();
  });

  it('sends what was TYPED once the setting is on', () => {
    const stored = entry({ body_weight_kg: '71.4' });
    const values = { ...entryValues(stored), bodyWeightKg: '69.8' };
    expect(buildEntryEdit(stored, values, true)?.body.body_weight_kg).toBe(69.8);
  });

  it('clears the weight when the setting is on and the field was emptied', () => {
    const stored = entry({ body_weight_kg: '71.4' });
    const values = { ...entryValues(stored), bodyWeightKg: '' };
    expect(buildEntryEdit(stored, values, true)?.body.body_weight_kg).toBeNull();
  });
});

describe('the save control refuses rather than overwriting with a refusal', () => {
  it('blocks a weigh-in the column would reject, so the stored one is not replaced', () => {
    const values = { ...entryValues(entry()), bodyWeightKg: 'abc' };
    expect(editBlocker(values, true)).toMatch(/not a number/i);
  });

  it('ignores an unparseable weight the form never showed', () => {
    const values = { ...entryValues(entry()), bodyWeightKg: 'abc' };
    expect(editBlocker(values, false)).toBeNull();
  });

  it('blocks an entry with nothing in it', () => {
    const values = { body: '', feel: null, sleepQuality: null, skin: null, bodyWeightKg: '' };
    expect(editBlocker(values, true)).toMatch(/at least one/i);
  });
});

/** ⚠️ The wire's `plans` lookup, which is the ONLY copy of a plan's name — `EntryPlanOut`
 *  deliberately carries none, so a rename lands in one place. */
const PLANS: JournalPlan[] = [
  { plan_id: 7, name: 'Road to 6B', weeks: [] },
  { plan_id: 2, name: 'Winter', weeks: [] },
];

describe('the list orders and groups without asking the server again', () => {
  const may = entry({ id: 1, client_uuid: UUID_A, entry_date: '2026-05-12' });
  const june = entry({ id: 2, client_uuid: UUID_B, entry_date: '2026-06-01' });
  const sameDay = entry({ id: 3, client_uuid: 'c', entry_date: '2026-05-12' });

  it('sorts both ways, breaking a shared date on id so the order is total', () => {
    const rows = [may, june, sameDay];
    expect(sortEntries(rows, 'newest').map((row) => row.id)).toEqual([2, 3, 1]);
    expect(sortEntries(rows, 'oldest').map((row) => row.id)).toEqual([1, 3, 2]);
  });

  it('groups by plan, and one group holds every entry that plan claims', () => {
    const older = entry({
      id: 9,
      client_uuid: 'd',
      plan: { plan_id: 2, phase: 'base', week_no: 1 },
    });
    const groups = groupByPlan([june, older, may], PLANS);
    // ⚠️ WHICH groups, not in which order: the order is `sortPlanGroups`' contract now, because
    // each section sorts its own entries and the plan order is its own control.
    expect(new Set(groups.map((group) => group.plan?.name))).toEqual(
      new Set(['Road to 6B', 'Winter']),
    );
    expect(groups.find((group) => group.plan?.plan_id === 7)?.entries.map((row) => row.id)).toEqual(
      [2, 1],
    );
  });

  it('keeps unattributed entries as a group of their own rather than dropping them', () => {
    const orphan = entry({ id: 5, client_uuid: 'e', plan: null });
    const groups = groupByPlan([orphan, june], PLANS);
    const none = groups.find((group) => group.key === 'none');

    expect(groups).toHaveLength(2);
    expect(none?.plan).toBeNull();
    expect(none?.entries.map((row) => row.id)).toEqual([5]);
  });

  it('⚠️ orders the SECTIONS by the earliest day each covers, both ways', () => {
    const winter = entry({
      id: 9,
      client_uuid: 'd',
      entry_date: '2025-11-02',
      plan: { plan_id: 2, phase: 'base', week_no: 1 },
    });
    const orphan = entry({ id: 5, client_uuid: 'e', entry_date: '2025-01-01', plan: null });
    const groups = groupByPlan([june, winter, orphan], PLANS);

    expect(sortPlanGroups(groups, 'newest').map((group) => group.plan?.name ?? 'none')).toEqual([
      'Road to 6B',
      'Winter',
      'none',
    ]);
    expect(sortPlanGroups(groups, 'oldest').map((group) => group.plan?.name ?? 'none')).toEqual([
      'none',
      'Winter',
      'Road to 6B',
    ]);
  });

  it('⚠️ takes the plan NAME from the lookup, which is the only copy of it', () => {
    // A rename writes one row. An entry that carried its own copy would still say the old name.
    const groups = groupByPlan([may], [{ plan_id: 7, name: 'Renamed this morning', weeks: [] }]);
    expect(groups[0]?.plan?.name).toBe('Renamed this morning');
  });
});
