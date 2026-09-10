import type { JournalEntry, JournalPlan } from '../api/types';
import type { JournalFieldValues } from '../session/journal';
import { isJournalDraftEmpty, parsedBodyWeightKg } from '../session/journal';
import type { JournalPutVariables } from '../session/journalApi';

/** The diary list's pure half: order, grouping, and the body of an EDIT. Nothing here renders,
 *  so both weigh-in rules and the uuid rule are unit tests — `entries.test.ts`. */

/** The overlay's own heading id, so the sheet is `aria-labelledby` the words already on screen. */
export const DIARY_ENTRY_HEADING_ID = 'ct-diary-entry-heading';

/** An entry the server could attribute to no plan. NORMAL — before any plan, or in a gap. */
export const UNATTRIBUTED_LABEL = 'Not part of a plan';

export type SortOrder = 'newest' | 'oldest';

/** Client-side, over what is already loaded: order is not part of the query key, so pressing
 *  either control cannot issue a request. */
export function sortEntries(
  entries: readonly JournalEntry[],
  order: SortOrder,
): readonly JournalEntry[] {
  const sign = order === 'newest' ? -1 : 1;
  // `id` breaks the tie: two entries CAN share a date, and a total order keeps React's keys
  // and the rendered rows in step across a re-sort.
  return [...entries].sort(
    (left, right) =>
      sign *
      (left.entry_date === right.entry_date
        ? left.id - right.id
        : left.entry_date < right.entry_date
          ? -1
          : 1),
  );
}

export interface EntryGroup {
  readonly key: string;
  /** The row from `JournalResponse.plans`, which is where the NAME and the week starts live.
   *  `null` is the unattributed group, which is a real group and not a leftover. */
  readonly plan: JournalPlan | null;
  readonly entries: readonly JournalEntry[];
}

/** One group per plan. ⚠️ The ORDER of the groups is NOT a contract: each plan section sorts its
 *  own entries now, so which section leads is `sortPlanGroups`' answer and nothing else's. */
export function groupByPlan(
  entries: readonly JournalEntry[],
  plans: readonly JournalPlan[],
): readonly EntryGroup[] {
  const byId = new Map(plans.map((plan) => [plan.plan_id, plan]));
  const groups = new Map<string, { plan: JournalPlan | null; entries: JournalEntry[] }>();
  for (const entry of entries) {
    const key = entry.plan === null ? 'none' : `plan:${String(entry.plan.plan_id)}`;
    // ⚠️ The lookup, never the entry: `plan_name` is deliberately not on `EntryPlanOut`, so a
    // rename lands in one place. Every attributed entry's `plan_id` is guaranteed present.
    const plan = entry.plan === null ? null : (byId.get(entry.plan.plan_id) ?? null);
    const group = groups.get(key) ?? { plan, entries: [] };
    group.entries.push(entry);
    groups.set(key, group);
  }
  return [...groups].map(([key, group]) => ({ key, ...group }));
}

/** Which plan section comes first (Kilian's own control): newest plan first, or oldest. The key
 *  is the earliest day that section covers, so the group no plan claims takes its turn too. */
export function sortPlanGroups(
  groups: readonly EntryGroup[],
  order: SortOrder,
): readonly EntryGroup[] {
  const sign = order === 'newest' ? -1 : 1;
  // The PLAN's own stored week starts are the server's fact about when that block began; the
  // entries stand in for a group that has none, and `sort()` on ISO days is chronological.
  const startOf = (group: EntryGroup): string =>
    [
      ...(group.plan?.weeks ?? []).map((week) => week.start_date),
      ...group.entries.map((entry) => entry.entry_date),
    ].sort()[0] ?? '';
  return [...groups].sort((left, right) => {
    const [first, second] = [startOf(left), startOf(right)];
    return first === second ? 0 : sign * (first < second ? -1 : 1);
  });
}

/** What the edit form starts from. The stored weigh-in comes back as the raw string, so a
 *  round trip cannot re-parse a decimal into a different number. */
export function entryValues(entry: JournalEntry): JournalFieldValues {
  return {
    body: entry.body ?? '',
    feel: entry.feel,
    sleepQuality: entry.sleep_quality,
    skin: entry.skin,
    bodyWeightKg: entry.body_weight_kg ?? '',
  };
}

/** ⚠️ Two data-loss guards live in this one function, both proven by `entries.test.ts`. */
export function buildEntryEdit(
  entry: JournalEntry,
  values: JournalFieldValues,
  showBodyMetrics: boolean,
): JournalPutVariables | null {
  // The `not_empty` CHECK would refuse it, and a 4xx never succeeds — `buildJournalPut`'s rule.
  if (isJournalDraftEmpty(values)) return null;
  const body = values.body.trim();
  return {
    // ⚠️ THIS ENTRY'S OWN uuid. The PUT replaces by it; a fresh one would mint a SECOND row
    // for the same day instead of editing the first.
    clientUuid: entry.client_uuid,
    body: {
      // The PUT replaces WHOLE, so every field goes, including the two the form never showed.
      entry_date: entry.entry_date,
      body: body === '' ? null : body,
      feel: values.feel,
      sleep_quality: values.sleepQuality,
      skin: values.skin,
      // ⚠️ With body metrics OFF no weight is rendered, so the form holds none — the STORED
      // one is resent verbatim. Sending `null` here silently erases a number nobody can see.
      body_weight_kg: showBodyMetrics
        ? parsedBodyWeightKg(values.bodyWeightKg)
        : entry.body_weight_kg,
      // Resent for the same reason: dropping it would unlink the entry from its session.
      logged_session_id: entry.logged_session_id,
    },
  };
}

/** Why pressing Save would be wrong, or `null` when it would be right. A weigh-in the server
 *  would refuse must not overwrite the one it holds, so the control goes rather than greys. */
export function editBlocker(values: JournalFieldValues, showBodyMetrics: boolean): string | null {
  if (isJournalDraftEmpty(values)) return 'An entry needs at least one thing written in it.';
  if (!showBodyMetrics) return null;
  const raw = values.bodyWeightKg.trim();
  if (raw === '' || parsedBodyWeightKg(values.bodyWeightKg) !== null) return null;
  return 'That weigh-in is not a number this can save, so nothing is sent.';
}
