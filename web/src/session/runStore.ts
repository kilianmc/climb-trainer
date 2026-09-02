import { useSyncExternalStore } from 'react';

import type { Discipline, LoggedSetInput } from '../api/types';

import type { Cursor } from './clock';
import type { CompiledPhase, PhaseKind } from './protocol';
import { blockRanges } from './protocol';

/**
 * The persisted run, under `ct:run`. Same shape as `theme.ts` — a module value, a listener set
 * and `useSyncExternalStore` — because a run is external state read during render.
 *
 * ⚠️ **The timeline is FROZEN into the record**, not re-derived from the plan on resume: a
 * second device can edit the plan mid-run, and a resumed run must be the run that started.
 *
 * ⚠️ **`ct:` namespace, and nothing sensitive.** In the federated mount `localStorage` belongs
 * to kilianmc.com, so no token and no query cache may be written here — only what is needed to
 * finish and flush a run the user is already inside.
 *
 * Written on **commit points only** — a phase change, a set logged, a flush result — never per
 * frame. A blocked or full store costs the run its persistence, never the run.
 */

export const RUN_STORAGE_KEY = 'ct:run';
/** Bumped whenever `RunRecord` changes shape. A record from another version is discarded. */
export const RUN_VERSION = 5;

/**
 * Where one ITEM — one block of the session — has got to.
 *
 * ⚠️ **The timer is per item, not per session.** Pressing Start on the session means "I am doing
 * this session" and starts nothing but the elapsed clock that feeds `duration_minutes`; each
 * item is entered deliberately. `completed` and `skipped` are reachable *without* ever running
 * the timer, because a climber who did the block away from the phone still did the block.
 */
export type ItemStatus = 'pending' | 'running' | 'completed' | 'skipped';

export interface RunItem {
  readonly blockIndex: number;
  readonly status: ItemStatus;
  /** How many times the item has been STARTED. `> 1` means it was restarted. */
  readonly runs: number;
  /**
   * Added to every `setIndex` this attempt mints.
   *
   * ⚠️ **A restart may not reuse the ordinals of the attempt before it.** `logged_set` rows
   * cannot be deleted (#81) and `set_index` is unique per session, so re-sending an ordinal the
   * server already has a row for under a NEW `client_uuid` is a `cardinality_violation` — a 422
   * that quarantines the whole flush. `outbox.ts::nextSetIndex` picks the base; this is the
   * difference between it and the block's own first ordinal.
   */
  readonly setIndexOffset: number;
}

export interface RunRecord {
  readonly v: number;
  /** Minted by `crypto.randomUUID()` at Start, and the idempotency key of every PUT. */
  readonly clientUuid: string;
  /** The LOCAL ISO date — `today.ts::localIsoDate`, never `toISOString().slice(0, 10)`. */
  readonly occurredOn: string;
  readonly discipline: Discipline;
  readonly plannedSessionId: number | null;
  readonly startedAtEpochMs: number;
  readonly timeline: readonly CompiledPhase[];
  /** One per block, in timeline order. The session's list of items. */
  readonly items: readonly RunItem[];
  /** Blocks the SERVER already held every set of at Start, by `blockIndex`; their items begin
   *  `completed`. ⚠️ They mint no set, so `sessionCompletion` has to count them — see it. */
  readonly preDoneBlockIndexes: readonly number[];
  /** The item whose timer is running, or `null` — which is the state a session STARTS in. */
  readonly activeBlockIndex: number | null;
  /** Meaningful only while an item is running; the clock is bounded to that item's phases. */
  readonly cursor: Cursor;
  /** Sets the server has acknowledged. Kept so the summary can show the whole run. */
  readonly logged: readonly LoggedSetInput[];
  /** Minted, unsent. This is the Tier-2 outbox, and it is authoritative until acked. */
  readonly pending: readonly LoggedSetInput[];
  /** A 4xx refused these. **Never resent** — retrying a 422 can only ever fail again. */
  readonly quarantined: readonly LoggedSetInput[];
  readonly sessionRpe: number | null;
  readonly finishedAtEpochMs: number | null;
  readonly savedAtEpochMs: number | null;
  /** When Done was pressed on the summary. ⚠️ On the RECORD, never in React state: the route
   *  unmounts on every navigation, and the summary used to come back with the RPE re-asked. */
  readonly summaryClosedAtEpochMs: number | null;
  /** When the tab last went hidden, so "Restart this phase" knows what to drop. */
  readonly hiddenAtEpochMs: number | null;
  /**
   * The wall-clock instant the running item was PAUSED, or `null`.
   *
   * ⚠️ **The pause is an instant, not a flag plus a remaining-time number.** The whole clock is
   * derived by comparing `cursor.phaseStartedAtEpochMs` against the wall clock, so freezing it
   * means freezing the instant the clock is read AT; resuming shifts the phase's start forward
   * by exactly `now - pausedAtEpochMs`. Storing a leftover duration instead would be a second,
   * disagreeing source of truth the moment a reload landed between the two.
   *
   * ⚠️ **It is persisted, and that is what makes a pause survive a reload and a backgrounding.**
   * A run paused, put in a pocket for ten minutes and reopened re-reads this instant and resumes
   * with the remaining time it was paused at, because nothing advanced in between.
   */
  readonly pausedAtEpochMs: number | null;
}

export interface RunSeed {
  readonly occurredOn: string;
  readonly discipline: Discipline;
  readonly plannedSessionId: number | null;
  readonly startedAtEpochMs: number;
  readonly timeline: readonly CompiledPhase[];
  /** `plan/completion.ts::doneBlockIndexes`. Required, not optional: an omitted one restarts a
   *  part-finished session as untouched, which is the defect (#82). */
  readonly preDoneBlockIndexes: readonly number[];
}

/** A fresh run. The uuid is minted here, client-side, and never asked of the server. */
export function createRun(seed: RunSeed): RunRecord {
  const preDone = new Set(seed.preDoneBlockIndexes);
  return {
    v: RUN_VERSION,
    clientUuid: crypto.randomUUID(),
    occurredOn: seed.occurredOn,
    discipline: seed.discipline,
    plannedSessionId: seed.plannedSessionId,
    startedAtEpochMs: seed.startedAtEpochMs,
    timeline: seed.timeline,
    preDoneBlockIndexes: [...preDone],
    // Nothing running: Start means "I am doing this session", not "begin item one". Entering an
    // item is a separate, deliberate press — including a pre-done one, which stays re-enterable.
    items: blockRanges(seed.timeline).map((range) => ({
      blockIndex: range.blockIndex,
      status: preDone.has(range.blockIndex) ? ('completed' as const) : ('pending' as const),
      runs: 0,
      setIndexOffset: 0,
    })),
    activeBlockIndex: null,
    cursor: { phaseIndex: 0, phaseStartedAtEpochMs: seed.startedAtEpochMs },
    logged: [],
    pending: [],
    quarantined: [],
    sessionRpe: null,
    finishedAtEpochMs: null,
    savedAtEpochMs: null,
    summaryClosedAtEpochMs: null,
    hiddenAtEpochMs: null,
    pausedAtEpochMs: null,
  };
}

/** The percentage's parts. ⚠️ `status = 'completed'` means "Finish was pressed" and is never
 *  this number: partial completion is a DERIVED QUERY, not a column (CLAUDE.md). */
export interface Completion {
  /** Blocks with EVERY prescribed set logged — the numerator of that query. */
  readonly blocksDone: number;
  /** Blocks that can be logged at all; one with nothing to record is out of both figures. */
  readonly blockCount: number;
  /** Whole percent. Three parts with one skipped reads 67, which is the case Kilian described. */
  readonly percent: number;
}

/** Which prescribed sets each block owes, by `blockIndex`. A block with none of them cannot be
 *  logged — `mintSet` refuses a phase with no `exerciseId` — so it is absent, not empty. */
function setsOwed(run: RunRecord): ReadonlyMap<number, Set<number>> {
  const owed = new Map<number, Set<number>>();
  for (const phase of run.timeline) {
    if (!phase.completesSet || phase.exerciseId === null || phase.prescribedSetId === null)
      continue;
    const ids = owed.get(phase.blockIndex) ?? new Set<number>();
    ids.add(phase.prescribedSetId);
    owed.set(phase.blockIndex, ids);
  }
  return owed;
}

/** How much got done, by the SERVER's own rule: a block counts once EVERY prescribed set of it
 *  has a logged set — or the run STARTED with it held. DONE OR NOT (Kilian); disagreeing was #82. */
export function sessionCompletion(run: RunRecord): Completion {
  // `quarantined` is excluded on purpose: a 4xx refused those, so no row exists to join to.
  const logged = new Set<number>();
  for (const set of [...run.logged, ...run.pending]) {
    if (set.prescribed_set_id != null) logged.add(set.prescribed_set_id);
  }
  const owed = setsOwed(run);
  // ⚠️ A block the server already held is DONE and mints nothing: those rows are written, under
  // an earlier `client_uuid`, and faking sets to make this add up would report unmeasured ones.
  const preDone = new Set(run.preDoneBlockIndexes);
  let blocksDone = 0;
  for (const [blockIndex, ids] of owed) {
    if (preDone.has(blockIndex) || [...ids].every((id) => logged.has(id))) blocksDone += 1;
  }
  return {
    blocksDone,
    blockCount: owed.size,
    percent: owed.size === 0 ? 0 : Math.round((blocksDone / owed.size) * 100),
  };
}

const PHASE_KINDS: readonly PhaseKind[] = ['prepare', 'work', 'rest', 'open'];
const ITEM_STATUSES: readonly ItemStatus[] = ['pending', 'running', 'completed', 'skipped'];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isFinite_(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNullableFinite(value: unknown): value is number | null {
  return value === null || isFinite_(value);
}

function isPhase(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    PHASE_KINDS.includes(value.kind as PhaseKind) &&
    isNullableFinite(value.durationMs) &&
    typeof value.label === 'string'
  );
}

function isItemArray(value: unknown): value is RunItem[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (entry) =>
        isRecord(entry) &&
        isFinite_(entry.blockIndex) &&
        ITEM_STATUSES.includes(entry.status as ItemStatus) &&
        isFinite_(entry.runs) &&
        isFinite_(entry.setIndexOffset),
    )
  );
}

function isIndexArray(value: unknown): value is number[] {
  return Array.isArray(value) && value.every(isFinite_);
}

function isSetArray(value: unknown): value is LoggedSetInput[] {
  return (
    Array.isArray(value) &&
    value.every(
      (entry) =>
        isRecord(entry) && typeof entry.client_uuid === 'string' && isFinite_(entry.set_index),
    )
  );
}

/** A stored record, or `null` for every way it can be untrustworthy. Discarding is the only
 * safe answer: a half-validated run drives a timeline of `undefined`s and mints 422s. */
export function parseRun(raw: string | null): RunRecord | null {
  if (raw === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;
  if (parsed.v !== RUN_VERSION) return null;
  if (typeof parsed.clientUuid !== 'string' || parsed.clientUuid === '') return null;
  if (typeof parsed.occurredOn !== 'string' || !ISO_DATE.test(parsed.occurredOn)) return null;
  if (parsed.discipline !== 'boulder' && parsed.discipline !== 'sport') return null;
  if (!isNullableFinite(parsed.plannedSessionId)) return null;
  if (!isFinite_(parsed.startedAtEpochMs)) return null;
  if (!Array.isArray(parsed.timeline) || parsed.timeline.length === 0) return null;
  if (!parsed.timeline.every(isPhase)) return null;
  if (!isItemArray(parsed.items)) return null;
  if (!isIndexArray(parsed.preDoneBlockIndexes)) return null;
  if (!isNullableFinite(parsed.activeBlockIndex)) return null;
  if (!isRecord(parsed.cursor)) return null;
  if (!isFinite_(parsed.cursor.phaseIndex) || !isFinite_(parsed.cursor.phaseStartedAtEpochMs)) {
    return null;
  }
  if (
    !isSetArray(parsed.logged) ||
    !isSetArray(parsed.pending) ||
    !isSetArray(parsed.quarantined)
  ) {
    return null;
  }
  if (!isNullableFinite(parsed.sessionRpe)) return null;
  if (
    !isNullableFinite(parsed.finishedAtEpochMs) ||
    !isNullableFinite(parsed.savedAtEpochMs) ||
    !isNullableFinite(parsed.summaryClosedAtEpochMs) ||
    !isNullableFinite(parsed.hiddenAtEpochMs) ||
    !isNullableFinite(parsed.pausedAtEpochMs)
  ) {
    return null;
  }
  return parsed as unknown as RunRecord;
}

/** Whatever `ct:run` holds right now. A store that throws reads as "no run". */
export function readStoredRun(): RunRecord | null {
  try {
    return parseRun(window.localStorage.getItem(RUN_STORAGE_KEY));
  } catch {
    return null;
  }
}

let current: RunRecord | null = readStoredRun();
const listeners = new Set<() => void>();

function snapshot(): RunRecord | null {
  return current;
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

export function getRun(): RunRecord | null {
  return current;
}

/** Commit a run — or `null` to clear it. Persistence is best-effort; the value is not. */
export function setRun(next: RunRecord | null): void {
  current = next;
  try {
    if (next === null) window.localStorage.removeItem(RUN_STORAGE_KEY);
    else window.localStorage.setItem(RUN_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // A blocked, full or partitioned store costs the run its persistence, not its existence.
    // Losing the tab now loses the unflushed tail, which is the same risk as no store at all.
  }
  for (const listener of listeners) listener();
}

/** Commit a change to the run in flight. A no-op when there is none. */
export function updateRun(change: (run: RunRecord) => RunRecord): void {
  if (current === null) return;
  setRun(change(current));
}

/** `useSyncExternalStore` for the same reason `theme.ts` uses it: external state, read in render. */
export function useRun(): RunRecord | null {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
