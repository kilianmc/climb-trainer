import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LoggedSetAck, SessionLogRequest } from '../api/types';

import { makeBlock, makeLibrary, makeSession, makeSet } from './fixtures';
import { applyAck, buildPut, mintSet, nextBatch, quarantine, recordSet } from './outbox';
import { compileProtocol } from './protocol';
import type { RunRecord } from './runStore';
import { createRun } from './runStore';

/**
 * One whole run, driven by hand, asserting the **exact four PUT bodies**. No React and no
 * fetch: this is the contract with `server/sessions/routes.py`, and every clause of it is a
 * bug that ships silently otherwise.
 *
 * - **Every request carries the full envelope** — `occurred_on`, `discipline` and
 *   `duration_minutes` are required even on the RPE follow-up, which reads like a patch.
 * - **`duration_minutes` is elapsed-so-far, floored at 1** — asserted *not* to be the plan's
 *   `estimated_minutes`, which `GREATEST` would make permanent and #12 cannot repair.
 * - **`sets` is a delta** — no set appears in two bodies, and no body repeats a `client_uuid`
 *   or a `set_index`.
 * - **`set_index` is 1..N across the session**, not per block.
 * - **Running through sets sends nothing** — there is no debounce and no item-count trigger, so
 *   between the start PUT and the first recovery flush the wire is silent.
 */

const START = Date.UTC(2026, 7, 28, 17, 0, 0);
const ESTIMATED_MINUTES = 90;

let minted = 0;
function nextUuid(): ReturnType<Crypto['randomUUID']> {
  minted += 1;
  return `00000000-0000-4000-8000-${String(minted).padStart(12, '0')}` as ReturnType<
    Crypto['randomUUID']
  >;
}

beforeEach(() => {
  minted = 0;
  vi.spyOn(crypto, 'randomUUID').mockImplementation(nextUuid);
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Two blocks, four sets: a timed hang block and a repeater block. */
function timeline() {
  const session = makeSession(
    [
      makeBlock({
        protocol_kind: 'max_hang',
        exercise_id: 11,
        rest_between_sets_seconds: 180,
        rest_after_seconds: 300,
        sets: [
          makeSet({ id: 501, set_index: 1, target_work_seconds: 10 }),
          makeSet({ id: 502, set_index: 2, target_work_seconds: 10 }),
        ],
      }),
      makeBlock({
        protocol_kind: 'repeaters',
        exercise_key: 'repeaters',
        exercise_id: 12,
        rest_between_sets_seconds: 120,
        sets: [
          makeSet({
            id: 503,
            set_index: 1,
            target_reps: 2,
            target_work_seconds: 7,
            target_rest_seconds: 3,
          }),
          makeSet({
            id: 504,
            set_index: 2,
            target_reps: 2,
            target_work_seconds: 7,
            target_rest_seconds: 3,
          }),
        ],
      }),
    ],
    '2026-08-28',
  );
  expect(session.estimated_minutes).toBe(ESTIMATED_MINUTES);
  return compileProtocol(session, makeLibrary());
}

function ackFor(body: SessionLogRequest): LoggedSetAck[] {
  return body.sets.map((set, index) => ({
    client_uuid: set.client_uuid,
    id: 9000 + index,
    set_index: set.set_index,
  }));
}

/** Log the nth completed set of the run, at `atEpochMs`. */
function logSet(run: RunRecord, ordinal: number, atEpochMs: number): RunRecord {
  const phase = run.timeline.filter((entry) => entry.completesSet)[ordinal - 1];
  expect(phase).toBeDefined();
  const set = mintSet(phase!, { completedAtEpochMs: atEpochMs, actualWorkSeconds: 10, rpe: 7 });
  expect(set).not.toBeNull();
  return recordSet(run, set!);
}

describe('a whole run, four PUTs', () => {
  it('sends the start, the recovery flush, Finish and the RPE follow-up, and nothing else', () => {
    const sent: SessionLogRequest[] = [];
    let run = createRun({
      occurredOn: '2026-08-28',
      discipline: 'sport',
      plannedSessionId: 5001,
      startedAtEpochMs: START,
      timeline: timeline(),
      preDoneBlockIndexes: [],
    });

    expect(run.clientUuid).toBe('00000000-0000-4000-8000-000000000001');

    // 1 — Start, on the click. The floor, because nothing is known yet.
    const start = buildPut(run, { sets: [], finished: false, nowEpochMs: START });
    sent.push(start);
    expect(start).toEqual({
      discipline: 'sport',
      duration_minutes: 1,
      finished: false,
      occurred_on: '2026-08-28',
      planned_session_id: 5001,
      sets: [],
      started_at: '2026-08-28T17:00:00.000Z',
    });

    // Two sets happen. Nothing is sent: no debounce, no item-count trigger.
    run = logSet(run, 1, START + 8 * 60_000);
    run = logSet(run, 2, START + 12 * 60_000);
    expect(sent).toHaveLength(1);

    // 2 — Recovery flush, on `visibilitychange`->hidden.
    const flushBatch = nextBatch(run);
    const flush = buildPut(run, {
      sets: flushBatch,
      finished: false,
      nowEpochMs: START + 15 * 60_000,
    });
    sent.push(flush);
    expect(flush).toEqual({
      discipline: 'sport',
      duration_minutes: 15,
      finished: false,
      occurred_on: '2026-08-28',
      planned_session_id: 5001,
      started_at: '2026-08-28T17:00:00.000Z',
      sets: [
        {
          client_uuid: '00000000-0000-4000-8000-000000000002',
          set_index: 1,
          exercise_id: 11,
          prescribed_set_id: 501,
          actual_reps: null,
          actual_work_seconds: 10,
          rpe: 7,
          completed_at: '2026-08-28T17:08:00.000Z',
        },
        {
          client_uuid: '00000000-0000-4000-8000-000000000003',
          set_index: 2,
          exercise_id: 11,
          prescribed_set_id: 502,
          actual_reps: null,
          actual_work_seconds: 10,
          rpe: 7,
          completed_at: '2026-08-28T17:12:00.000Z',
        },
      ],
    });
    run = applyAck(run, ackFor(flush));
    expect(run.pending).toHaveLength(0);

    // Two more sets, then Finish.
    run = logSet(run, 3, START + 24 * 60_000);
    run = logSet(run, 4, START + 29 * 60_000);

    // 3 — Finish. The delta only: the first two sets are already the server's.
    const finishBatch = nextBatch(run);
    const finish = buildPut(run, {
      sets: finishBatch,
      finished: true,
      nowEpochMs: START + 31 * 60_000,
    });
    sent.push(finish);
    expect(finish.finished).toBe(true);
    expect(finish.duration_minutes).toBe(31);
    expect(finish.sets.map((set) => set.set_index)).toEqual([3, 4]);
    expect(finish.sets.map((set) => set.exercise_id)).toEqual([12, 12]);
    expect(finish.sets.map((set) => set.prescribed_set_id)).toEqual([503, 504]);
    expect('rpe' in finish).toBe(false);
    run = applyAck(run, ackFor(finish));

    // 4 — The session RPE, once the climber picks a number. Same envelope, no sets.
    run = { ...run, sessionRpe: 8, finishedAtEpochMs: START + 31 * 60_000 };
    const rated = buildPut(run, { sets: [], finished: true, nowEpochMs: START + 32 * 60_000 });
    sent.push(rated);
    expect(rated).toEqual({
      discipline: 'sport',
      duration_minutes: 32,
      finished: true,
      occurred_on: '2026-08-28',
      planned_session_id: 5001,
      rpe: 8,
      sets: [],
      started_at: '2026-08-28T17:00:00.000Z',
    });

    expect(sent).toHaveLength(4);
  });

  it('never sends estimated_minutes as duration_minutes', () => {
    const run = createRun({
      occurredOn: '2026-08-28',
      discipline: 'sport',
      plannedSessionId: 5001,
      startedAtEpochMs: START,
      timeline: timeline(),
      preDoneBlockIndexes: [],
    });

    for (const elapsed of [0, 60_000, 45 * 60_000]) {
      const body = buildPut(run, { sets: [], finished: false, nowEpochMs: START + elapsed });
      expect(body.duration_minutes).not.toBe(ESTIMATED_MINUTES);
      expect(body.duration_minutes).toBe(Math.max(1, Math.floor(elapsed / 60_000)));
    }
  });

  it('carries the full envelope on every request, the RPE follow-up included', () => {
    const run: RunRecord = {
      ...createRun({
        occurredOn: '2026-08-28',
        discipline: 'boulder',
        plannedSessionId: null,
        startedAtEpochMs: START,
        timeline: timeline(),
        preDoneBlockIndexes: [],
      }),
      sessionRpe: 6,
    };

    const body = buildPut(run, { sets: [], finished: true, nowEpochMs: START + 60_000 });
    expect(Object.keys(body).sort()).toEqual([
      'discipline',
      'duration_minutes',
      'finished',
      'occurred_on',
      'planned_session_id',
      'rpe',
      'sets',
      'started_at',
    ]);
  });

  it('sends no set twice and no duplicate client_uuid or set_index in one payload', () => {
    let run = createRun({
      occurredOn: '2026-08-28',
      discipline: 'sport',
      plannedSessionId: 5001,
      startedAtEpochMs: START,
      timeline: timeline(),
      preDoneBlockIndexes: [],
    });
    for (let ordinal = 1; ordinal <= 4; ordinal += 1) {
      run = logSet(run, ordinal, START + ordinal * 60_000);
    }
    // The climber redoes set 3: a new mint for an index already in the outbox.
    run = logSet(run, 3, START + 10 * 60_000);

    const batch = nextBatch(run);
    expect(new Set(batch.map((set) => set.client_uuid)).size).toBe(batch.length);
    expect(new Set(batch.map((set) => set.set_index)).size).toBe(batch.length);
    expect(batch.map((set) => set.set_index).sort()).toEqual([1, 2, 3, 4]);

    const first = buildPut(run, { sets: batch, finished: true, nowEpochMs: START + 11 * 60_000 });
    run = applyAck(run, ackFor(first));
    const second = buildPut(run, {
      sets: nextBatch(run),
      finished: true,
      nowEpochMs: START + 12 * 60_000,
    });
    expect(second.sets).toEqual([]);
  });

  it('a quarantined batch never appears in a later flush', () => {
    let run = createRun({
      occurredOn: '2026-08-28',
      discipline: 'sport',
      plannedSessionId: 5001,
      startedAtEpochMs: START,
      timeline: timeline(),
      preDoneBlockIndexes: [],
    });
    run = logSet(run, 1, START + 60_000);
    run = logSet(run, 2, START + 120_000);

    const refused = nextBatch(run);
    run = quarantine(run, refused);
    run = logSet(run, 3, START + 180_000);

    const later = buildPut(run, {
      sets: nextBatch(run),
      finished: true,
      nowEpochMs: START + 240_000,
    });
    expect(later.sets.map((set) => set.set_index)).toEqual([3]);
    expect(run.quarantined).toHaveLength(2);
  });
});
