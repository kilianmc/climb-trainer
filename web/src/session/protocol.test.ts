import { describe, expect, it } from 'vitest';

import type { ProtocolKind } from '../api/types';

import { makeBlock, makeLibrary, makeSession, makeSet } from './fixtures';
import { PREPARE_SECONDS, compileProtocol, timelineDurationMs } from './protocol';

/**
 * The compiler is the one place a mis-read plan becomes a wrong workout, so every arm here is
 * a domain rule rather than a restatement of the code:
 *
 * - **The three rests** — `target_rest_seconds` within a set, `rest_between_sets_seconds`
 *   between sets, `rest_after_seconds` after the block. `server/models.py::SessionBlock` says
 *   none may absorb another; these tests are what makes that executable.
 * - **`set_index` 1..N across the whole session** — the server answers a duplicate `set_index`
 *   in one payload with a 422 that quarantines the flush, so a per-block index loses the run.
 * - **Every `ProtocolKind` compiles** — the exhaustive `switch` makes a missing kind a `tsc`
 *   error, which no runtime test can observe; what IS observable is that all nine produce a
 *   playable timeline, which is the half a stray `default:` would hide.
 * - **`completesSet`** — mark it too early and a set is written before it happened.
 */

const library = makeLibrary();

describe('the three rests', () => {
  it('keeps within-set, between-set and after-block rests distinct', () => {
    const session = makeSession([
      makeBlock({
        protocol_kind: 'repeaters',
        rest_between_sets_seconds: 180,
        rest_after_seconds: 300,
        sets: [
          makeSet({ id: 1, target_reps: 3, target_work_seconds: 7, target_rest_seconds: 3 }),
          makeSet({ id: 2, target_reps: 3, target_work_seconds: 7, target_rest_seconds: 3 }),
        ],
      }),
      makeBlock({ protocol_kind: 'max_hang', sets: [makeSet({ id: 3, target_work_seconds: 10 })] }),
    ]);

    const timeline = compileProtocol(session, library);
    const rests = timeline
      .filter((phase) => phase.kind === 'rest')
      .map((phase) => phase.durationMs);

    // 2 within-set rests per repeater set x 2 sets, then the between-sets rest, then the
    // after-block rest. Four distinct values, none of them merged.
    expect(rests).toEqual([3000, 3000, 180_000, 3000, 3000, 300_000]);
  });

  it('emits no rest between the last set of a block and the block rest', () => {
    const session = makeSession([
      makeBlock({
        rest_between_sets_seconds: 120,
        rest_after_seconds: 240,
        sets: [
          makeSet({ id: 1, target_work_seconds: 10 }),
          makeSet({ id: 2, target_work_seconds: 10 }),
        ],
      }),
    ]);

    const timeline = compileProtocol(session, library);
    // One between-sets rest for two sets, and no after-block rest at all: it is the last block.
    expect(timeline.filter((phase) => phase.kind === 'rest')).toHaveLength(1);
    expect(timeline.at(-1)?.kind).toBe('work');
  });

  it('drops a zero or null rest rather than flashing a zero-second phase', () => {
    const session = makeSession([
      makeBlock({
        rest_between_sets_seconds: 0,
        rest_after_seconds: null,
        sets: [
          makeSet({ id: 1, target_work_seconds: 10 }),
          makeSet({ id: 2, target_work_seconds: 10 }),
        ],
      }),
    ]);

    expect(compileProtocol(session, library).some((phase) => phase.kind === 'rest')).toBe(false);
  });
});

describe('set_index', () => {
  it('is the chronological 1..N ordinal of the whole session, not the per-block one', () => {
    const perBlock = [makeSet({ id: 1, set_index: 1 }), makeSet({ id: 2, set_index: 2 })];
    const session = makeSession([
      makeBlock({ order_index: 0, sets: perBlock }),
      makeBlock({ order_index: 1, exercise_key: 'pull_ups', sets: perBlock }),
    ]);

    const completions = compileProtocol(session, library).filter((phase) => phase.completesSet);
    expect(completions.map((phase) => phase.setIndex)).toEqual([1, 2, 3, 4]);
    // The per-block index is 1,2,1,2 — sending that is a duplicate-set_index 422.
    expect(completions.map((phase) => phase.setOfBlock)).toEqual([1, 2, 1, 2]);
  });

  it('leaves structural phases out of the set numbering entirely', () => {
    const session = makeSession([
      makeBlock({ rest_after_seconds: 60, sets: [makeSet({ id: 1 })] }),
      makeBlock({ exercise_key: 'pull_ups', sets: [makeSet({ id: 2 })] }),
    ]);

    const structural = compileProtocol(session, library).filter(
      (phase) =>
        phase.kind === 'prepare' || (phase.kind === 'rest' && phase.prescribedSetId === null),
    );
    expect(structural).not.toHaveLength(0);
    expect(structural.every((phase) => phase.setIndex === null)).toBe(true);
  });
});

describe('the protocol kinds', () => {
  const kinds: ProtocolKind[] = [
    'max_hang',
    'repeaters',
    'intervals',
    'circuit',
    'limit_boulder',
    'straight_sets',
    'laps',
    'hold',
    'other',
  ];

  it.each(kinds)('%s compiles to a playable set', (kind) => {
    const session = makeSession([
      makeBlock({
        protocol_kind: kind,
        sets: [makeSet({ id: 1, target_reps: 3, target_work_seconds: 7, target_rest_seconds: 3 })],
      }),
    ]);

    const timeline = compileProtocol(session, library);
    const owned = timeline.filter((phase) => phase.setIndex === 1);
    expect(owned).not.toHaveLength(0);
    expect(owned.filter((phase) => phase.completesSet)).toHaveLength(1);
  });

  it('gives an untimed protocol an open phase rather than an invented countdown', () => {
    const session = makeSession([
      makeBlock({
        protocol_kind: 'limit_boulder',
        sets: [makeSet({ id: 1, target_work_seconds: 300 })],
      }),
    ]);

    const [, effort] = compileProtocol(session, library);
    expect(effort?.kind).toBe('open');
    expect(effort?.durationMs).toBeNull();
  });

  it('falls back to open when a timed protocol has no target_work_seconds', () => {
    const session = makeSession([
      makeBlock({ protocol_kind: 'repeaters', sets: [makeSet({ id: 1, target_reps: 6 })] }),
    ]);

    expect(compileProtocol(session, library).filter((phase) => phase.kind === 'open')).toHaveLength(
      1,
    );
  });
});

describe('completesSet', () => {
  it('marks the last rep of a repeater set, never an earlier one', () => {
    const session = makeSession([
      makeBlock({
        protocol_kind: 'repeaters',
        sets: [makeSet({ id: 7, target_reps: 3, target_work_seconds: 7, target_rest_seconds: 3 })],
      }),
    ]);

    const timeline = compileProtocol(session, library);
    const marked = timeline.filter((phase) => phase.completesSet);
    expect(marked).toHaveLength(1);
    expect(marked[0]).toMatchObject({ kind: 'work', prescribedSetId: 7 });
    expect(timeline.indexOf(marked[0]!)).toBe(timeline.length - 1);
  });
});

describe('the shape of a compiled run', () => {
  it('opens every block with a prepare phase and counts only timed phases in the total', () => {
    const session = makeSession([
      makeBlock({ sets: [makeSet({ id: 1, target_work_seconds: 10 })] }),
      makeBlock({ protocol_kind: 'other', exercise_key: 'traverse', sets: [makeSet({ id: 2 })] }),
    ]);

    const timeline = compileProtocol(session, library);
    expect(timeline.filter((phase) => phase.kind === 'prepare')).toHaveLength(2);
    // Two prepares plus the one timed effort; the `other` block's open phase adds nothing.
    expect(timelineDurationMs(timeline)).toBe(PREPARE_SECONDS * 2 * 1000 + 10_000);
  });
});
