import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LoggedSetInput } from '../api/types';

import { makeBlock, makeLibrary, makeSession, makeSet } from './fixtures';
import type { CompiledPhase } from './protocol';
import { compileProtocol } from './protocol';
import {
  RUN_STORAGE_KEY,
  RUN_VERSION,
  createRun,
  getRun,
  parseRun,
  readStoredRun,
  sessionCompletion,
  setRun,
  updateRun,
} from './runStore';

/**
 * The persisted run is the only copy of an unflushed session, so what it does with a BAD copy
 * is the whole test:
 *
 * - **Absent, corrupt, wrong-`v`, or right-shaped-but-wrong-typed all yield no run.** A
 *   half-validated record drives a timeline of `undefined`s and mints sets the server refuses.
 * - **A throwing `localStorage` costs persistence, not the run** — Safari in a partitioned
 *   third-party frame throws on `setItem`, and the federated mount is exactly that frame.
 * - **Nothing sensitive is written.** In the shell, `localStorage` belongs to kilianmc.com.
 */

const START = Date.UTC(2026, 7, 28, 17, 0, 0);

const phase: CompiledPhase = {
  kind: 'work',
  durationMs: 10_000,
  label: 'Max hangs',
  blockIndex: 0,
  exerciseKey: 'max_hangs',
  exerciseId: 11,
  protocolKind: 'max_hang',
  setIndex: 1,
  setOfBlock: 1,
  setsInBlock: 1,
  prescribedSetId: 501,
  completesSet: true,
  targetReps: null,
  targetWorkSeconds: 10,
};

function seeded() {
  return createRun({
    occurredOn: '2026-08-28',
    discipline: 'sport',
    plannedSessionId: 5001,
    startedAtEpochMs: START,
    timeline: [phase],
  });
}

beforeEach(() => {
  window.localStorage.clear();
  setRun(null);
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('parseRun', () => {
  it('yields no run for absent, corrupt or non-object storage', () => {
    expect(parseRun(null)).toBeNull();
    expect(parseRun('')).toBeNull();
    expect(parseRun('{oh no')).toBeNull();
    expect(parseRun('"a string"')).toBeNull();
    expect(parseRun('[]')).toBeNull();
  });

  it('yields no run for a record written by another version', () => {
    const record = { ...seeded(), v: RUN_VERSION + 1 };
    expect(parseRun(JSON.stringify(record))).toBeNull();
  });

  it.each([
    ['no timeline', { timeline: [] }],
    ['a timeline of junk', { timeline: [{ kind: 'sprint', durationMs: 1, label: 'x' }] }],
    ['a bad occurred_on', { occurredOn: '28/08/2026' }],
    ['a discipline that is not one', { discipline: 'trad' }],
    ['a cursor that is not numbers', { cursor: { phaseIndex: 'first', phaseStartedAtEpochMs: 0 } }],
    ['a pending entry with no uuid', { pending: [{ set_index: 1 }] }],
    ['a non-finite start', { startedAtEpochMs: Number.NaN }],
  ])('yields no run for %s', (_label, override) => {
    expect(parseRun(JSON.stringify({ ...seeded(), ...override }))).toBeNull();
  });

  it('round-trips a good record', () => {
    const run = seeded();
    expect(parseRun(JSON.stringify(run))).toEqual(run);
  });
});

describe('the store', () => {
  it('persists under the ct: namespace and reads back', () => {
    const run = seeded();
    setRun(run);

    expect(window.localStorage.getItem(RUN_STORAGE_KEY)).not.toBeNull();
    expect(readStoredRun()).toEqual(run);
    expect(getRun()).toEqual(run);
  });

  it('writes no token and no query cache', () => {
    setRun(seeded());
    const raw = window.localStorage.getItem(RUN_STORAGE_KEY) ?? '';

    expect(raw).not.toMatch(/token|bearer|authorization|refresh/i);
    // The only ct: keys this feature owns. Nothing else may appear.
    expect(Object.keys(window.localStorage).filter((key) => key.startsWith('ct:'))).toEqual([
      RUN_STORAGE_KEY,
    ]);
  });

  it('clears the key rather than storing null', () => {
    setRun(seeded());
    setRun(null);

    expect(window.localStorage.getItem(RUN_STORAGE_KEY)).toBeNull();
    expect(getRun()).toBeNull();
  });

  it('keeps the run when the store throws on write', () => {
    const run = seeded();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota', 'QuotaExceededError');
    });

    expect(() => {
      setRun(run);
    }).not.toThrow();
    expect(getRun()).toEqual(run);
  });

  it('reads as no run when the store throws on read', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });

    expect(readStoredRun()).toBeNull();
  });

  it('updateRun is a no-op when no run is in flight', () => {
    updateRun((run) => ({ ...run, sessionRpe: 9 }));
    expect(getRun()).toBeNull();
  });

  it('updateRun commits and persists', () => {
    setRun(seeded());
    updateRun((run) => ({ ...run, sessionRpe: 9 }));

    expect(getRun()?.sessionRpe).toBe(9);
    expect(readStoredRun()?.sessionRpe).toBe(9);
  });
});

/** The SERVER's derived query, reproduced here so the two can never disagree: the join
 *  `logged_set.prescribed_set_id → session_block`, counting blocks with at least one set. */
describe('sessionCompletion', () => {
  /** Three one-set blocks, so each block's share of the session is a clean third. */
  function threeBlocks() {
    const plan = makeSession([
      makeBlock({ exercise_id: 11, sets: [makeSet({ id: 501, target_work_seconds: 10 })] }),
      makeBlock({
        order_index: 1,
        exercise_key: 'front_lever',
        exercise_id: 12,
        sets: [makeSet({ id: 601, target_work_seconds: 10 })],
      }),
      makeBlock({
        order_index: 2,
        exercise_key: 'lock_offs',
        exercise_id: 13,
        sets: [makeSet({ id: 701, target_work_seconds: 10 })],
      }),
    ]);
    return createRun({
      occurredOn: '2026-08-28',
      discipline: 'sport',
      plannedSessionId: 5001,
      startedAtEpochMs: START,
      timeline: compileProtocol(plan, makeLibrary()),
    });
  }

  function loggedSet(prescribedSetId: number, setIndex: number): LoggedSetInput {
    return {
      client_uuid: `00000000-0000-4000-8000-00000000000${String(setIndex)}`,
      set_index: setIndex,
      exercise_id: 11,
      prescribed_set_id: prescribedSetId,
      actual_reps: null,
      actual_work_seconds: null,
      rpe: null,
      completed_at: new Date(START).toISOString(),
    };
  }

  it('reads 67% for three parts with one skipped, counting acked and pending alike', () => {
    const run = {
      ...threeBlocks(),
      logged: [loggedSet(501, 1)],
      pending: [loggedSet(601, 2)],
    };

    // ⚠️ Kilian: "if i skipped one part, it should not be 100%." The third block logged nothing,
    // which is exactly how a skip stays honest — it is absent from the join, not marked.
    expect(sessionCompletion(run)).toEqual({ blocksDone: 2, blockCount: 3, percent: 67 });
  });

  it('counts a block ONCE however many of its sets landed', () => {
    const run = { ...threeBlocks(), logged: [loggedSet(501, 1), loggedSet(501, 2)] };
    expect(sessionCompletion(run)).toEqual({ blocksDone: 1, blockCount: 3, percent: 33 });
  });

  it('does not count a quarantined set: a 4xx means the server has no row to join to', () => {
    const run = { ...threeBlocks(), quarantined: [loggedSet(701, 3)] };
    expect(sessionCompletion(run)).toEqual({ blocksDone: 0, blockCount: 3, percent: 0 });
  });
});
