import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LoggedSetInput } from '../api/types';

import {
  MAX_SETS_PER_FLUSH,
  applyAck,
  chunkSets,
  mintSet,
  nextBatch,
  quarantine,
  recordSet,
  requeue,
} from './outbox';
import type { CompiledPhase } from './protocol';
import type { RunRecord } from './runStore';
import { createRun } from './runStore';

/**
 * The outbox is the only thing standing between a finished set and losing it, so each arm here
 * is a data-loss path rather than a restatement:
 *
 * - **5xx requeues in order**; **4xx quarantines and is never resent**, because a 422 rejects
 *   the whole flush by design and cannot succeed on a retry.
 * - **Acks retire by uuid**, so a partial answer retires exactly what landed.
 * - **A set with no `exercise_id` is refused at mint time** — a previewed plan has none and the
 *   field is required, so minting one buys a 422 that quarantines everything with it.
 * - **120 per flush**, the size the route's five-statement bound was measured against.
 *
 * The failure *classification* lives in `api.ts` and is tested there; this file is what happens
 * to the run once the answer is known.
 */

const START = Date.UTC(2026, 7, 28, 17, 0, 0);

let minted = 0;
beforeEach(() => {
  minted = 0;
  vi.spyOn(crypto, 'randomUUID').mockImplementation(() => {
    minted += 1;
    return `00000000-0000-4000-8000-${String(minted).padStart(12, '0')}` as ReturnType<
      Crypto['randomUUID']
    >;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function phase(setIndex: number, exerciseId: number | null = 11): CompiledPhase {
  return {
    kind: 'work',
    durationMs: 10_000,
    label: 'Max hangs',
    blockIndex: 0,
    exerciseKey: 'max_hangs',
    exerciseId,
    protocolKind: 'max_hang',
    setIndex,
    setOfBlock: setIndex,
    setsInBlock: 4,
    prescribedSetId: 500 + setIndex,
    completesSet: true,
    targetReps: null,
    targetWorkSeconds: 10,
  };
}

function emptyRun(): RunRecord {
  return createRun({
    occurredOn: '2026-08-28',
    discipline: 'sport',
    plannedSessionId: 5001,
    startedAtEpochMs: START,
    timeline: [phase(1)],
    preDoneBlockIndexes: [],
  });
}

function withSets(count: number): RunRecord {
  let run = emptyRun();
  for (let index = 1; index <= count; index += 1) {
    const set = mintSet(phase(index), { completedAtEpochMs: START + index * 60_000 });
    run = recordSet(run, set!);
  }
  return run;
}

describe('mintSet', () => {
  it('refuses a set the server could never accept', () => {
    expect(mintSet(phase(1, null), { completedAtEpochMs: START })).toBeNull();
    expect(mintSet({ ...phase(1), setIndex: null }, { completedAtEpochMs: START })).toBeNull();
  });

  it('mints a client uuid and leaves the body-weight pair off entirely', () => {
    const set = mintSet(phase(3), { completedAtEpochMs: START, actualReps: 5, rpe: 8 });
    expect(set).toEqual({
      client_uuid: '00000000-0000-4000-8000-000000000001',
      set_index: 3,
      exercise_id: 11,
      prescribed_set_id: 503,
      actual_reps: 5,
      actual_work_seconds: null,
      rpe: 8,
      completed_at: '2026-08-28T17:00:00.000Z',
    });
  });
});

describe('recordSet', () => {
  it('replaces a pending set that shares a set_index rather than duplicating it', () => {
    let run = withSets(2);
    const redo = mintSet(phase(2), { completedAtEpochMs: START + 900_000, rpe: 9 });
    run = recordSet(run, redo!);

    expect(run.pending).toHaveLength(2);
    expect(run.pending.map((set) => set.set_index)).toEqual([1, 2]);
    expect(run.pending.at(-1)?.rpe).toBe(9);
  });

  it('replaces by client_uuid too, so a re-recorded set never doubles', () => {
    let run = withSets(1);
    const same = { ...run.pending[0]!, set_index: 9, rpe: 4 };
    run = recordSet(run, same);

    expect(run.pending).toHaveLength(1);
    expect(run.pending[0]).toMatchObject({ set_index: 9, rpe: 4 });
  });
});

describe('applyAck', () => {
  it('retires exactly the uuids the server echoed and keeps the rest pending', () => {
    const run = withSets(3);
    const acked = run.pending.slice(0, 2);

    const next = applyAck(
      run,
      acked.map((set, index) => ({
        client_uuid: set.client_uuid,
        id: index,
        set_index: set.set_index,
      })),
    );

    expect(next.logged.map((set) => set.set_index)).toEqual([1, 2]);
    expect(next.pending.map((set) => set.set_index)).toEqual([3]);
  });

  it('is a no-op for an empty ack list', () => {
    const run = withSets(2);
    expect(applyAck(run, [])).toBe(run);
  });
});

describe('quarantine', () => {
  it('moves a 4xx batch out of pending permanently', () => {
    const run = withSets(3);
    const batch = nextBatch(run);

    const next = quarantine(run, batch);

    expect(next.pending).toEqual([]);
    expect(next.quarantined.map((set) => set.set_index)).toEqual([1, 2, 3]);
    // A second flush after another set is logged carries only the new one.
    expect(
      nextBatch(recordSet(next, mintSet(phase(4), { completedAtEpochMs: START })!)),
    ).toHaveLength(1);
  });
});

describe('requeue', () => {
  it('is a no-op while the batch is still pending, because sending never removes it', () => {
    const run = withSets(2);
    expect(requeue(run, nextBatch(run))).toBe(run);
  });

  it('restores a lost batch at the front, in order', () => {
    const run = withSets(3);
    const lost = run.pending.slice(0, 2);
    const stripped: RunRecord = { ...run, pending: run.pending.slice(2) };

    const next = requeue(stripped, lost);

    expect(next.pending.map((set) => set.set_index)).toEqual([1, 2, 3]);
  });
});

describe('chunkSets', () => {
  it('splits at the size the route was measured against and drops nothing', () => {
    const sets: LoggedSetInput[] = Array.from({ length: 250 }, (_, index) => ({
      client_uuid: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
      set_index: index + 1,
      exercise_id: 11,
    }));

    const chunks = chunkSets(sets);

    expect(chunks.map((chunk) => chunk.length)).toEqual([
      MAX_SETS_PER_FLUSH,
      MAX_SETS_PER_FLUSH,
      10,
    ]);
    expect(chunks.flat()).toHaveLength(250);
  });

  it('yields no chunk at all for an empty outbox', () => {
    expect(chunkSets([])).toEqual([]);
  });

  it('caps one flush at the measured ceiling', () => {
    const run = withSets(MAX_SETS_PER_FLUSH + 5);
    expect(nextBatch(run)).toHaveLength(MAX_SETS_PER_FLUSH);
  });
});
