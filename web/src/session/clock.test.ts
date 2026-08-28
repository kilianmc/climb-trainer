import { describe, expect, it } from 'vitest';

import {
  MAX_DURATION_MINUTES,
  MIN_DURATION_MINUTES,
  advance,
  elapsedMinutes,
  phaseElapsedMs,
  remainingMs,
} from './clock';
import type { CompiledPhase } from './protocol';

/**
 * The clock is what a backgrounded phone breaks, and every break is silent:
 *
 * - **Advance WHILE overdue** — a throttled rAF can return minutes later, so advancing once
 *   leaves the player permanently behind the wall clock.
 * - **`skipped`** is the resync trigger and the cue suppressor. Off by one and either the
 *   banner never shows or the player fires four beeps at once.
 * - **Never rewind** — an NTP correction steps the clock backwards; replaying a phase would
 *   re-run work the climber already did.
 * - **`elapsedMinutes`** is the sole source of `duration_minutes`, which the server merges with
 *   `GREATEST` into a generated `srpe_load` column. Its floor and its ceiling are both
 *   permanent mistakes if wrong.
 */

function timed(durationMs: number): CompiledPhase {
  return {
    kind: 'work',
    durationMs,
    label: 'Max hangs',
    blockIndex: 0,
    exerciseKey: 'max_hangs',
    exerciseId: 11,
    protocolKind: 'max_hang',
    setIndex: 1,
    setOfBlock: 1,
    setsInBlock: 1,
    prescribedSetId: 1,
    completesSet: false,
    targetReps: null,
    targetWorkSeconds: durationMs / 1000,
  };
}

function open(): CompiledPhase {
  return { ...timed(0), kind: 'open', durationMs: null };
}

const START = 1_772_000_000_000;

describe('advance', () => {
  it('crosses every boundary a five-minute absence covered, in one call', () => {
    const timeline = Array.from({ length: 8 }, () => timed(60_000));

    const result = advance(
      { phaseIndex: 0, phaseStartedAtEpochMs: START },
      timeline,
      START + 300_000,
    );

    expect(result.cursor.phaseIndex).toBe(5);
    expect(result.crossed).toBe(5);
    // Four phases elapsed entirely unseen; the fifth is the one being landed on.
    expect(result.skipped).toBe(4);
    expect(result.done).toBe(false);
  });

  it('anchors the new phase to the boundary, not to now, so error cannot accumulate', () => {
    const timeline = [timed(60_000), timed(60_000)];

    const result = advance(
      { phaseIndex: 0, phaseStartedAtEpochMs: START },
      timeline,
      START + 95_000,
    );

    expect(result.cursor.phaseStartedAtEpochMs).toBe(START + 60_000);
    expect(remainingMs(result.cursor, timeline, START + 95_000)).toBe(25_000);
  });

  it('reports one crossing and no skips for an ordinary boundary', () => {
    const timeline = [timed(60_000), timed(60_000)];

    const result = advance(
      { phaseIndex: 0, phaseStartedAtEpochMs: START },
      timeline,
      START + 60_000,
    );

    expect(result.crossed).toBe(1);
    expect(result.skipped).toBe(0);
  });

  it('stops on an open phase however long the tab was away', () => {
    const timeline = [timed(10_000), open(), timed(10_000)];

    const result = advance(
      { phaseIndex: 0, phaseStartedAtEpochMs: START },
      timeline,
      START + 600_000,
    );

    expect(result.cursor.phaseIndex).toBe(1);
    expect(result.landedOn?.kind).toBe('open');
    expect(result.done).toBe(false);
  });

  it('stops at the end of the timeline and says so', () => {
    const timeline = [timed(10_000), timed(10_000)];

    const result = advance(
      { phaseIndex: 0, phaseStartedAtEpochMs: START },
      timeline,
      START + 999_000,
    );

    expect(result.cursor.phaseIndex).toBe(2);
    expect(result.landedOn).toBeNull();
    expect(result.done).toBe(true);
  });

  it('never rewinds when the clock steps backwards', () => {
    const timeline = [timed(60_000), timed(60_000)];
    const cursor = { phaseIndex: 1, phaseStartedAtEpochMs: START + 60_000 };

    const result = advance(cursor, timeline, START + 30_000);

    expect(result.cursor).toEqual(cursor);
    expect(result.crossed).toBe(0);
    expect(result.skipped).toBe(0);
  });

  it('is idempotent, so the rAF tick and its setTimeout backup can both fire', () => {
    const timeline = [timed(60_000), timed(60_000), timed(60_000)];
    const first = advance(
      { phaseIndex: 0, phaseStartedAtEpochMs: START },
      timeline,
      START + 61_000,
    );
    const second = advance(first.cursor, timeline, START + 61_000);

    expect(second.cursor).toEqual(first.cursor);
    expect(second.crossed).toBe(0);
  });
});

describe('remainingMs and phaseElapsedMs', () => {
  it('returns null for an open phase and for a finished timeline', () => {
    const timeline = [open()];
    expect(
      remainingMs({ phaseIndex: 0, phaseStartedAtEpochMs: START }, timeline, START),
    ).toBeNull();
    expect(
      remainingMs({ phaseIndex: 1, phaseStartedAtEpochMs: START }, timeline, START),
    ).toBeNull();
  });

  it('counts up from zero on an open phase and never goes negative', () => {
    const cursor = { phaseIndex: 0, phaseStartedAtEpochMs: START };
    expect(phaseElapsedMs(cursor, START + 4200)).toBe(4200);
    expect(phaseElapsedMs(cursor, START - 4200)).toBe(0);
  });
});

describe('elapsedMinutes', () => {
  it('floors at one so the start PUT can carry the required duration_minutes', () => {
    expect(elapsedMinutes(START, START)).toBe(MIN_DURATION_MINUTES);
    expect(elapsedMinutes(START, START + 59_000)).toBe(1);
  });

  it('is elapsed minutes so far, never a plan estimate', () => {
    expect(elapsedMinutes(START, START + 47 * 60_000)).toBe(47);
  });

  it('clamps a run left open overnight to a day rather than earning a permanent 422', () => {
    expect(elapsedMinutes(START, START + 40 * 3_600_000)).toBe(MAX_DURATION_MINUTES);
  });

  it('survives a backwards clock without sending a negative', () => {
    expect(elapsedMinutes(START, START - 3_600_000)).toBe(MIN_DURATION_MINUTES);
  });
});
