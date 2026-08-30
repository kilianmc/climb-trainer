import type { PlanTree } from '../api/types';
import { selectSession } from '../session/today';

import { sessionBlock } from './explain';

/* Which phases of the plan are expanded, persisted per plan under `ct:planPhases`.
   ⚠️ `ct:` namespace: in the federated mount this storage belongs to kilianmc.com. */

export const PHASE_STORAGE_KEY = 'ct:planPhases';
/** Bumped whenever the stored shape changes. Another version is discarded, never migrated. */
export const PHASE_VERSION = 1;

/* A phase is identified by its mesocycle's `start_week`, which is unique in a plan and is
   already the React key on the section. Ids are absent from a preview; start weeks are not. */
export interface StoredPhases {
  readonly v: number;
  readonly plan: string;
  readonly open: readonly number[];
}

/** Which plan the stored set belongs to. A different plan starts from the default again. */
export function planKey(plan: PlanTree): string {
  return plan.id == null ? `preview:${plan.start_date}` : `plan:${String(plan.id)}`;
}

/** Every phase of the plan, in order — the argument to "expand all". */
export function allPhases(plan: PlanTree): number[] {
  return plan.mesocycles.map((mesocycle) => mesocycle.start_week);
}

/** The block the climber is in, via the lookup this repo already has. ⚠️ **Fallback: the LAST
 *  phase** — `selectSession` returns nothing once every session is past, and that block is why. */
export function defaultOpenPhases(plan: PlanTree, todayIso: string): number[] {
  const phases = allPhases(plan);
  if (phases.length === 0) return [];
  const block = sessionBlock(plan, selectSession(plan, todayIso).session);
  if (block !== null) return [block.startWeek];
  return phases.slice(-1);
}

/** Same set, order-insensitive. ⚠️ React setting `open` itself fires a `toggle` event, so
 *  without this a collapse-all costs one re-render per section for no change. */
export function samePhases(a: readonly number[], b: readonly number[]): boolean {
  return a.length === b.length && a.every((week) => b.includes(week));
}

function isPhaseList(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'number');
}

/** `null` for every way the stored value can be untrustworthy, which means "use the default":
 *  another version, another plan, or a shape that is not a list of numbers. */
export function parsePhases(raw: string | null, key: string): number[] | null {
  if (raw === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
  const record = parsed as Record<string, unknown>;
  if (record.v !== PHASE_VERSION || record.plan !== key) return null;
  return isPhaseList(record.open) ? record.open : null;
}

/** ONE plan's set is kept, so a climber who has had six plans has one entry, not six. */
export function serialisePhases(key: string, open: readonly number[]): string {
  const record: StoredPhases = { v: PHASE_VERSION, plan: key, open: [...open] };
  return JSON.stringify(record);
}

/** A blocked, full or partitioned store costs the preference, never the screen. */
export function readOpenPhases(key: string): number[] | null {
  try {
    return parsePhases(window.localStorage.getItem(PHASE_STORAGE_KEY), key);
  } catch {
    return null;
  }
}

export function writeOpenPhases(key: string, open: readonly number[]): void {
  try {
    window.localStorage.setItem(PHASE_STORAGE_KEY, serialisePhases(key, open));
  } catch {
    // Same rule as `session/runStore.ts`: persistence is best-effort, the value is not.
  }
}
