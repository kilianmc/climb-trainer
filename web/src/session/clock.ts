import type { CompiledPhase } from './protocol';

/** The clock maths, with the clock passed in: every function takes the time as an argument,
 * which is what makes a five-minute backgrounded jump a unit test rather than a phone. */

export interface Cursor {
  readonly phaseIndex: number;
  /** Wall-clock start of the phase, derived by ADDING durations — never re-stamped to `now`. */
  readonly phaseStartedAtEpochMs: number;
}

export interface Advanced {
  readonly cursor: Cursor;
  /** Phase boundaries crossed by this call. `0` — nothing happened. */
  readonly crossed: number;
  /** Phases that elapsed UNSEEN — `crossed - 1`, floored at zero. The resync trigger: `> 0`
   * means fire ONE cue for the phase landed on. Per boundary is the four-beeps-at-once bug. */
  readonly skipped: number;
  /** The phase the run is now on, or `null` when the timeline ran out. */
  readonly landedOn: CompiledPhase | null;
  readonly done: boolean;
}

/** Walk the cursor to wherever the wall clock says the run is — WHILE overdue, because a
 * backgrounded phone throttles rAF to minutes. A backwards clock never rewinds it. */
export function advance(
  cursor: Cursor,
  timeline: readonly CompiledPhase[],
  nowEpochMs: number,
): Advanced {
  let { phaseIndex, phaseStartedAtEpochMs } = cursor;
  let crossed = 0;

  for (;;) {
    const current = timeline[phaseIndex];
    if (current === undefined || current.durationMs === null) break;
    if (nowEpochMs - phaseStartedAtEpochMs < current.durationMs) break;
    phaseStartedAtEpochMs += current.durationMs;
    phaseIndex += 1;
    crossed += 1;
  }

  const landedOn = timeline[phaseIndex] ?? null;
  return {
    cursor: { phaseIndex, phaseStartedAtEpochMs },
    crossed,
    skipped: Math.max(0, crossed - 1),
    landedOn,
    done: landedOn === null,
  };
}

/** How long the current phase has been running. Never negative. */
export function phaseElapsedMs(cursor: Cursor, nowEpochMs: number): number {
  return Math.max(0, nowEpochMs - cursor.phaseStartedAtEpochMs);
}

/** Milliseconds left, or `null` when there is no countdown: an `open` phase and a finished
 * timeline are both "no number", told apart by `advance`'s `done` rather than by a zero. */
export function remainingMs(
  cursor: Cursor,
  timeline: readonly CompiledPhase[],
  nowEpochMs: number,
): number | null {
  const current = timeline[cursor.phaseIndex];
  if (current?.durationMs == null) return null;
  return Math.max(0, current.durationMs - phaseElapsedMs(cursor, nowEpochMs));
}

/** The floor the server's `GREATEST` makes permanent, so the start PUT sends exactly this. */
export const MIN_DURATION_MINUTES = 1;
/** A day: a run left open overnight would otherwise earn a 422, which is quarantined
 * forever — the whole session lost to a forgotten tab. */
export const MAX_DURATION_MINUTES = 1440;

/**
 * Elapsed minutes so far, floored at 1 and clamped to a day. **This is the only source of
 * `duration_minutes`.**
 *
 * ⚠️ Never the plan's `estimated_minutes`. `activity.duration_minutes` is updated with
 * `GREATEST(existing, incoming)` and `srpe_load` is generated from it, so sending 90 at minute
 * zero pins the session at 90 minutes and corrupts training load for good — and #12's editor
 * cannot repair it, because this route cannot shorten a session.
 */
export function elapsedMinutes(startedAtEpochMs: number, nowEpochMs: number): number {
  const minutes = Math.floor((nowEpochMs - startedAtEpochMs) / 60_000);
  if (!Number.isFinite(minutes)) return MIN_DURATION_MINUTES;
  return Math.min(MAX_DURATION_MINUTES, Math.max(MIN_DURATION_MINUTES, minutes));
}
