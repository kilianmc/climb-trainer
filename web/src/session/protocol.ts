import type { LibraryExercise, PlanBlock, PlanSession, ProtocolKind } from '../api/types';
import { exerciseLabel } from '../plan/blueprint';

/**
 * The protocol compiler: a planned session in, a frozen list of timed phases out.
 *
 * Pure — no clock, no React, no fetch. The player never re-derives a timeline from the plan
 * mid-run (`runStore.ts` freezes this array), so every decision that shapes the run is taken
 * here, once, and is unit-testable without mounting anything.
 *
 * ⚠️ **THREE distinct rests live in the plan tree and none may absorb another**, per the
 * comment on `server/models.py::SessionBlock`: `prescribed_set.target_rest_seconds` is rest
 * *within* a set (between reps of a repeater), `session_block.rest_between_sets_seconds` is
 * rest *between* sets of a block, and `session_block.rest_after_seconds` is rest *after* the
 * whole block. Collapsing any two of them silently rewrites the training stimulus.
 *
 * ⚠️ **`setIndex` is the chronological 1..N ordinal of the WHOLE session**, assigned here —
 * never `SetOut.set_index`, which restarts at 1 in every block. The server answers a duplicate
 * `set_index` inside one payload with a 422 (CLAUDE.md, "The `sets` array is a DELTA").
 */

/** The four things a phase can be. `open` has no duration: it ends on a tap. */
export type PhaseKind = 'prepare' | 'work' | 'rest' | 'open';

export interface CompiledPhase {
  readonly kind: PhaseKind;
  /** `null` **iff** `kind === 'open'`. Everything else is a countdown. */
  readonly durationMs: number | null;
  /** The block's exercise, as a climber reads it. Rests carry it too — a rest belongs to the
   * block it interrupts, and a pure module should not own screen copy. */
  readonly label: string;
  readonly blockIndex: number;
  readonly exerciseKey: string;
  /** `null` on a previewed plan, where nothing is a row yet. Such a set cannot be logged. */
  readonly exerciseId: number | null;
  readonly protocolKind: ProtocolKind;
  /** Chronological 1..N across the session; `null` on phases that belong to no set. */
  readonly setIndex: number | null;
  /** 1-based position of the set inside its block, and the block's set count, for "3 of 5". */
  readonly setOfBlock: number | null;
  readonly setsInBlock: number;
  readonly prescribedSetId: number | null;
  /** The last phase of a set — the one place the run mints a `logged_set`. */
  readonly completesSet: boolean;
  readonly targetReps: number | null;
  readonly targetWorkSeconds: number | null;
}

/** The lead-in at the top of each block. A constant because nothing in the plan tree records
 * it, and without it a block starts working the instant the previous rest ends. */
export const PREPARE_SECONDS = 15;

/** Makes a new `ProtocolKind` a BUILD failure here rather than a silent `open` at runtime. */
function assertNever(kind: never): never {
  throw new Error(`Unhandled protocol kind: ${JSON.stringify(kind)}`);
}

interface BlockContext {
  readonly blockIndex: number;
  readonly label: string;
  readonly exerciseKey: string;
  readonly exerciseId: number | null;
  readonly protocolKind: ProtocolKind;
  readonly setsInBlock: number;
}

interface SetContext extends BlockContext {
  readonly setIndex: number;
  readonly setOfBlock: number;
  readonly prescribedSetId: number | null;
  readonly targetReps: number | null;
  readonly targetWorkSeconds: number | null;
}

function phase(context: SetContext, kind: PhaseKind, seconds: number | null): CompiledPhase {
  return {
    kind,
    durationMs: seconds === null ? null : seconds * 1000,
    label: context.label,
    blockIndex: context.blockIndex,
    exerciseKey: context.exerciseKey,
    exerciseId: context.exerciseId,
    protocolKind: context.protocolKind,
    setIndex: context.setIndex,
    setOfBlock: context.setOfBlock,
    setsInBlock: context.setsInBlock,
    prescribedSetId: context.prescribedSetId,
    completesSet: false,
    targetReps: context.targetReps,
    targetWorkSeconds: context.targetWorkSeconds,
  };
}

/** A phase that belongs to the block but to no set: the lead-in and the two structural rests. */
function structural(context: BlockContext, kind: PhaseKind, seconds: number): CompiledPhase {
  return {
    kind,
    durationMs: seconds * 1000,
    label: context.label,
    blockIndex: context.blockIndex,
    exerciseKey: context.exerciseKey,
    exerciseId: context.exerciseId,
    protocolKind: context.protocolKind,
    setIndex: null,
    setOfBlock: null,
    setsInBlock: context.setsInBlock,
    prescribedSetId: null,
    completesSet: false,
    targetReps: null,
    targetWorkSeconds: null,
  };
}

/** One timed effort, or an untimed one the climber ends with a tap. */
function effort(context: SetContext): CompiledPhase[] {
  const seconds = context.targetWorkSeconds;
  return seconds !== null && seconds > 0
    ? [phase(context, 'work', seconds)]
    : [phase(context, 'open', null)];
}

/** `target_reps` efforts separated by the WITHIN-SET rest. None after the final rep: what
 * follows is the block's `rest_between_sets_seconds`, and both would double the recovery. */
function repeaters(context: SetContext, restSeconds: number | null): CompiledPhase[] {
  const seconds = context.targetWorkSeconds;
  if (seconds === null || seconds <= 0) return [phase(context, 'open', null)];

  const reps = Math.max(1, context.targetReps ?? 1);
  const phases: CompiledPhase[] = [];
  for (let rep = 0; rep < reps; rep += 1) {
    phases.push(phase(context, 'work', seconds));
    if (rep < reps - 1 && restSeconds !== null && restSeconds > 0) {
      phases.push(phase(context, 'rest', restSeconds));
    }
  }
  return phases;
}

/** The exhaustive switch: a new `ProtocolKind` is a `tsc` error on `assertNever`, which is
 * the entire point of writing it this way. */
function setPhases(context: SetContext, restWithinSetSeconds: number | null): CompiledPhase[] {
  switch (context.protocolKind) {
    case 'repeaters':
      return repeaters(context, restWithinSetSeconds);
    case 'max_hang':
    case 'intervals':
    case 'hold':
    case 'laps':
    case 'straight_sets':
      return effort(context);
    // Nothing here is on a clock — a circuit ends when the climber falls off — and a
    // countdown invented for them would be a lie the player then beeps at.
    case 'circuit':
    case 'limit_boulder':
    case 'other':
      return [phase(context, 'open', null)];
    default:
      return assertNever(context.protocolKind);
  }
}

function blockContext(
  block: PlanBlock,
  blockIndex: number,
  exercises: ReadonlyMap<string, LibraryExercise>,
): BlockContext {
  return {
    blockIndex,
    label: exerciseLabel(block.exercise_key, exercises),
    exerciseKey: block.exercise_key,
    exerciseId: block.exercise_id ?? null,
    protocolKind: block.protocol_kind,
    setsInBlock: block.sets.length,
  };
}

/** Flatten a planned session into the timeline the player drives; `exercises` is
 * `blueprint.ts::exercisesByKey`. A `null` or `0` rest emits nothing rather than a flash. */
export function compileProtocol(
  session: PlanSession,
  exercises: ReadonlyMap<string, LibraryExercise>,
): CompiledPhase[] {
  const timeline: CompiledPhase[] = [];
  let ordinal = 0;

  session.blocks.forEach((block, blockIndex) => {
    const context = blockContext(block, blockIndex, exercises);
    timeline.push(structural(context, 'prepare', PREPARE_SECONDS));

    block.sets.forEach((set, position) => {
      ordinal += 1;
      const phases = setPhases(
        {
          ...context,
          setIndex: ordinal,
          setOfBlock: position + 1,
          prescribedSetId: set.id ?? null,
          targetReps: set.target_reps,
          targetWorkSeconds: set.target_work_seconds,
        },
        set.target_rest_seconds,
      );
      // The set is logged when its LAST phase ends; marking an earlier one would write a
      // set the climber has not finished.
      const last = phases.at(-1);
      if (last !== undefined) phases[phases.length - 1] = { ...last, completesSet: true };
      timeline.push(...phases);

      const between = block.rest_between_sets_seconds;
      if (position < block.sets.length - 1 && between !== null && between > 0) {
        timeline.push(structural(context, 'rest', between));
      }
    });

    const after = block.rest_after_seconds;
    if (blockIndex < session.blocks.length - 1 && after !== null && after > 0) {
      timeline.push(structural(context, 'rest', after));
    }
  });

  return timeline;
}

export interface BlockRange {
  readonly blockIndex: number;
  readonly label: string;
  /** Index of the block's first phase in the timeline, and ONE PAST its last. */
  readonly start: number;
  readonly end: number;
  readonly setsInBlock: number;
  /** The first chronological set ordinal the block owns — the base a re-run offsets from.
   * `null` when it owns none: a block of purely structural phases, which no compiler emits yet. */
  readonly firstSetIndex: number | null;
}

/**
 * The timeline, cut back into the blocks it was flattened from — the "items" the player lists.
 *
 * Derived rather than stored: `compileProtocol` already stamps `blockIndex` on every phase, and
 * a second copy of the same fact is a second thing to keep in step. It is `[start, end)` because
 * that is the shape `Array.prototype.slice` wants, and slicing the timeline to `end` is exactly
 * how the clock is stopped at the end of an item without teaching `clock.ts` about blocks.
 */
export function blockRanges(timeline: readonly CompiledPhase[]): BlockRange[] {
  const ranges: BlockRange[] = [];
  timeline.forEach((phase, index) => {
    const last = ranges.at(-1);
    if (last === undefined || last.blockIndex !== phase.blockIndex) {
      ranges.push({
        blockIndex: phase.blockIndex,
        label: phase.label,
        start: index,
        end: index + 1,
        setsInBlock: phase.setsInBlock,
        firstSetIndex: phase.setIndex,
      });
      return;
    }
    ranges[ranges.length - 1] = {
      ...last,
      end: index + 1,
      firstSetIndex: last.firstSetIndex ?? phase.setIndex,
    };
  });
  return ranges;
}

/** How long the timed part of a run lasts. `open` phases contribute nothing — they are a tap. */
export function timelineDurationMs(timeline: readonly CompiledPhase[]): number {
  return timeline.reduce((total, item) => total + (item.durationMs ?? 0), 0);
}
