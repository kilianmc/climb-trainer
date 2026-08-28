import type { LoggedSetAck, LoggedSetInput, SessionLogRequest } from '../api/types';

import { elapsedMinutes } from './clock';
import type { CompiledPhase } from './protocol';
import type { RunRecord } from './runStore';

/**
 * The Tier-2 outbox: mint a set, hold it, send it once, and know what to do with the answer.
 *
 * Pure — every function takes a `RunRecord` and returns a new one, so a whole simulated run is
 * a unit test. The triggers themselves are NOT here; see `api.ts`.
 *
 * ⚠️ **`sets` is a DELTA.** A set is replaced whole by its `client_uuid`, and a duplicate
 * `client_uuid` **or** `set_index` inside one payload is a server 422 that rejects the entire
 * flush — so `recordSet` is the chokepoint that makes a duplicate unrepresentable.
 *
 * ⚠️ **A set stays in `pending` until an outcome arrives.** Removing it at send time and
 * putting it back on failure has a window in which a crash loses it; leaving it costs nothing,
 * because the server upserts by `client_uuid` and a re-sent set is last-write-wins.
 */

/** The route is measured at five statements for 1..120 sets in one flush, so 120 is the
 * shape it was PROVEN against rather than an arbitrary page size. */
export const MAX_SETS_PER_FLUSH = 120;

export interface SetOutcome {
  readonly completedAtEpochMs: number;
  readonly actualReps?: number | null;
  readonly actualWorkSeconds?: number | null;
  readonly rpe?: number | null;
}

/** One finished set, or `null` when the required `exercise_id` is absent — refusing beats a
 * 422 that quarantines the flush. The body-weight pair is omitted: no endpoint exposes one. */
export function mintSet(phase: CompiledPhase, outcome: SetOutcome): LoggedSetInput | null {
  if (phase.exerciseId === null || phase.setIndex === null) return null;
  return {
    client_uuid: crypto.randomUUID(),
    set_index: phase.setIndex,
    exercise_id: phase.exerciseId,
    prescribed_set_id: phase.prescribedSetId,
    actual_reps: outcome.actualReps ?? null,
    actual_work_seconds: outcome.actualWorkSeconds ?? null,
    rpe: outcome.rpe ?? null,
    completed_at: new Date(outcome.completedAtEpochMs).toISOString(),
  };
}

/** Outbox a finished set, REPLACING any pending one sharing its `client_uuid` or
 * `set_index`: two rows with one conflict key is a `cardinality_violation`, i.e. a 422. */
export function recordSet(run: RunRecord, set: LoggedSetInput): RunRecord {
  const kept = run.pending.filter(
    (entry) => entry.client_uuid !== set.client_uuid && entry.set_index !== set.set_index,
  );
  return { ...run, pending: [...kept, set] };
}

/**
 * The lowest `set_index` no row in this run has ever used — the base for a RE-RUN of an item.
 *
 * ⚠️ **`logged_set` rows cannot be deleted** (issue #81: there is no endpoint), so re-running an
 * item may not reuse the ordinals the server already has rows for. `set_index` is unique per
 * session, so a re-run that reused them would be a `cardinality_violation` — a 422 that
 * quarantines the whole flush. Counting `quarantined` too is deliberate: a refused set may still
 * have landed, and an ordinal that *might* be taken is not one to hand out again.
 */
export function nextSetIndex(run: RunRecord): number {
  const used = [...run.logged, ...run.pending, ...run.quarantined];
  return used.reduce((highest, set) => Math.max(highest, set.set_index), 0) + 1;
}

/** The next flush's payload: everything pending, up to the measured ceiling, in order. */
export function nextBatch(run: RunRecord): LoggedSetInput[] {
  return run.pending.slice(0, MAX_SETS_PER_FLUSH);
}

/** `sets` split into flushes the route was measured against. An empty input yields no chunks. */
export function chunkSets(
  sets: readonly LoggedSetInput[],
  size = MAX_SETS_PER_FLUSH,
): LoggedSetInput[][] {
  const chunks: LoggedSetInput[][] = [];
  for (let index = 0; index < sets.length; index += size) {
    chunks.push(sets.slice(index, index + size));
  }
  return chunks;
}

/** Retire what the server acknowledged, by the uuid it echoed — driven by the ACK and not by
 * what was sent, so a partial answer retires exactly what landed. */
export function applyAck(run: RunRecord, acks: readonly LoggedSetAck[]): RunRecord {
  const acked = new Set(acks.map((ack) => ack.client_uuid));
  if (acked.size === 0) return run;
  const settled = run.pending.filter((set) => acked.has(set.client_uuid));
  return {
    ...run,
    pending: run.pending.filter((set) => !acked.has(set.client_uuid)),
    logged: [...run.logged, ...settled],
  };
}

/**
 * A 4xx refused this batch. Move it out of `pending` **permanently**.
 *
 * A 422 rejects the whole flush by design and every `HTTPException` detail on the route is a
 * fixed string, so nothing about the payload will be different next time: retrying is the
 * "payload that retries forever and can never succeed" that `server/fields.py` warns about.
 * Kept rather than dropped so the summary can say a set was refused.
 */
export function quarantine(run: RunRecord, batch: readonly LoggedSetInput[]): RunRecord {
  const refused = new Set(batch.map((set) => set.client_uuid));
  if (refused.size === 0) return run;
  return {
    ...run,
    pending: run.pending.filter((set) => !refused.has(set.client_uuid)),
    quarantined: [...run.quarantined, ...batch],
  };
}

/** The retryable path: the batch goes back at the FRONT of `pending`, in order, and waits for
 * the next trigger — NEVER a timer. A no-op while it is still there, which is the normal case. */
export function requeue(run: RunRecord, batch: readonly LoggedSetInput[]): RunRecord {
  const returning = batch.filter(
    (set) => !run.pending.some((entry) => entry.client_uuid === set.client_uuid),
  );
  if (returning.length === 0) return run;
  return { ...run, pending: [...returning, ...run.pending] };
}

export interface PutOptions {
  readonly sets: readonly LoggedSetInput[];
  readonly finished: boolean;
  readonly nowEpochMs: number;
}

/**
 * The body of one `PUT /api/sessions/{client_uuid}` — start, recovery flush, Finish and the
 * RPE follow-up all build it here, so no call site can forget the envelope.
 *
 * ⚠️ **`occurred_on`, `duration_minutes` and `discipline` are required on EVERY request**,
 * the RPE follow-up included. `duration_minutes` is `elapsedMinutes` and nothing else: the
 * server merges it with `GREATEST` into a generated `srpe_load`, so the plan's
 * `estimated_minutes` would pin the session at 90 minutes for good.
 *
 * `rpe` is **omitted** until the climber picks one. An explicit `null` means "clear", so a
 * stale start-PUT retry landing after the RPE PUT would wipe the number they just gave.
 */
export function buildPut(run: RunRecord, options: PutOptions): SessionLogRequest {
  const body: SessionLogRequest = {
    discipline: run.discipline,
    duration_minutes: elapsedMinutes(run.startedAtEpochMs, options.nowEpochMs),
    finished: options.finished,
    occurred_on: run.occurredOn,
    planned_session_id: run.plannedSessionId,
    sets: [...options.sets],
    started_at: new Date(run.startedAtEpochMs).toISOString(),
  };
  return run.sessionRpe === null ? body : { ...body, rpe: run.sessionRpe };
}
