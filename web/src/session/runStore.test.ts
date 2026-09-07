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
    preDoneBlockIndexes: [],
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

  it('yields no run for a record written by another version, the PREVIOUS one included', () => {
    for (const v of [RUN_VERSION + 1, RUN_VERSION - 1]) {
      expect(parseRun(JSON.stringify({ ...seeded(), v }))).toBeNull();
    }
  });

  it.each([
    ['no timeline', { timeline: [] }],
    ['a timeline of junk', { timeline: [{ kind: 'sprint', durationMs: 1, label: 'x' }] }],
    ['a bad occurred_on', { occurredOn: '28/08/2026' }],
    ['a discipline that is not one', { discipline: 'trad' }],
    ['a cursor that is not numbers', { cursor: { phaseIndex: 'first', phaseStartedAtEpochMs: 0 } }],
    ['a pending entry with no uuid', { pending: [{ set_index: 1 }] }],
    ['a non-finite start', { startedAtEpochMs: Number.NaN }],
    // The v4 shape, which had no such field: `JSON.stringify` drops it, as a v4 record does.
    ['no pre-done list at all', { preDoneBlockIndexes: undefined }],
    ['a pre-done list of junk', { preDoneBlockIndexes: ['first'] }],
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

/** The SERVER's derived query, reproduced here so the two can never disagree — a block counts
 *  once EVERY prescribed set of it has a logged set (#82). Them disagreeing IS that issue. */
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
      preDoneBlockIndexes: [],
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

  it('counts a block ONCE however many rows landed against its one set', () => {
    const run = { ...threeBlocks(), logged: [loggedSet(501, 1), loggedSet(501, 2)] };
    expect(sessionCompletion(run)).toEqual({ blocksDone: 1, blockCount: 3, percent: 33 });
  });

  /** One three-set block: the shape "entered, one set flushed, then skipped" needs. */
  function oneBlockOfThree() {
    const plan = makeSession([
      makeBlock({
        exercise_id: 11,
        rest_between_sets_seconds: 20,
        sets: [1, 2, 3].map((index) =>
          makeSet({ id: 500 + index, set_index: index, target_work_seconds: 10 }),
        ),
      }),
    ]);
    return createRun({
      occurredOn: '2026-08-28',
      discipline: 'sport',
      plannedSessionId: 5001,
      startedAtEpochMs: START,
      timeline: compileProtocol(plan, makeLibrary()),
      preDoneBlockIndexes: [],
    });
  }

  it('⚠️ does NOT count a block with only SOME of its sets logged — the #82 defect', () => {
    // Kilian entered this block, let one set flush and then skipped it. `logged_set` rows cannot
    // be deleted (#81), so under the old rule that one row read done for good.
    const run = { ...oneBlockOfThree(), logged: [loggedSet(501, 1)] };
    expect(sessionCompletion(run)).toEqual({ blocksDone: 0, blockCount: 1, percent: 0 });
  });

  it('counts it once its LAST set lands, which is what pressing Done logs', () => {
    const run = {
      ...oneBlockOfThree(),
      logged: [loggedSet(501, 1), loggedSet(502, 2)],
      pending: [loggedSet(503, 3)],
    };
    expect(sessionCompletion(run)).toEqual({ blocksDone: 1, blockCount: 1, percent: 100 });
  });

  it('⚠️ leaves a block that cannot be logged OUT of both figures, not stuck under 100%', () => {
    // A previewed plan names no exercise, so `mintSet` refuses every phase of the block: counting
    // it would pin the session below 100% however much of it the climber did.
    const plan = makeSession([
      makeBlock({ exercise_id: 11, sets: [makeSet({ id: 501, target_work_seconds: 10 })] }),
      makeBlock({
        order_index: 1,
        exercise_key: 'front_lever',
        exercise_id: null,
        sets: [makeSet({ id: null, target_work_seconds: 10 })],
      }),
    ]);
    const run = {
      ...createRun({
        occurredOn: '2026-08-28',
        discipline: 'sport' as const,
        plannedSessionId: 5001,
        startedAtEpochMs: START,
        timeline: compileProtocol(plan, makeLibrary()),
        preDoneBlockIndexes: [],
      }),
      logged: [loggedSet(501, 1)],
    };

    expect(sessionCompletion(run)).toEqual({ blocksDone: 1, blockCount: 1, percent: 100 });
  });

  /** Four one-set blocks, `preDone` of them already logged on the SERVER at Start. */
  function fourBlocks(preDone: readonly number[]) {
    const plan = makeSession(
      [501, 601, 701, 801].map((id, index) =>
        makeBlock({
          order_index: index,
          exercise_key: `block_${String(index)}`,
          exercise_id: 11 + index,
          sets: [makeSet({ id, target_work_seconds: 10 })],
        }),
      ),
    );
    return createRun({
      occurredOn: '2026-09-02',
      discipline: 'sport',
      plannedSessionId: 5001,
      startedAtEpochMs: START,
      timeline: compileProtocol(plan, makeLibrary()),
      preDoneBlockIndexes: preDone,
    });
  }

  /** ⚠️ #82's last defect, in Kilian's words: "when I click on start again, it shows all 4 of
   *  them as 'not started'. That is wrong — the first 3 should be shown as 'completed'." */
  it('SEEDS the items the server already holds as completed, and counts them at 75%', () => {
    const run = fourBlocks([0, 1, 2]);

    expect(run.items.map((item) => item.status)).toEqual([
      'completed',
      'completed',
      'completed',
      'pending',
    ]);
    // ⚠️ No set is FABRICATED for the three: those rows are on the server already, and entries
    // with no measured reps or load would read in the summary as logged in this attempt.
    expect(run.logged).toEqual([]);
    expect(run.pending).toEqual([]);
    expect(sessionCompletion(run)).toEqual({ blocksDone: 3, blockCount: 4, percent: 75 });
  });

  it('reaches 100% once the FOURTH block’s sets land, and never counts one twice', () => {
    const run = fourBlocks([0, 1, 2]);

    expect(sessionCompletion({ ...run, pending: [loggedSet(801, 1)] })).toEqual({
      blocksDone: 4,
      blockCount: 4,
      percent: 100,
    });
    // A pre-done block re-entered and logged again is still ONE block of the four.
    expect(sessionCompletion({ ...run, logged: [loggedSet(501, 1)] })).toEqual({
      blocksDone: 3,
      blockCount: 4,
      percent: 75,
    });
  });

  it('does not count a quarantined set: a 4xx means the server has no row to join to', () => {
    const run = { ...threeBlocks(), quarantined: [loggedSet(701, 3)] };
    expect(sessionCompletion(run)).toEqual({ blocksDone: 0, blockCount: 3, percent: 0 });
  });
});
