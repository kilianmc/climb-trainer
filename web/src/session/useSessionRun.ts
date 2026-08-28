import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { Discipline, LibraryExercise, LoggedSetInput, PlanSession } from '../api/types';
import { useAuth } from '../auth/AuthProvider';

import { classifyFailure, useSessionLogPut, writesEnabled } from './api';
import type { Cursor } from './clock';
import { advance, phaseElapsedMs, remainingMs } from './clock';
import type { CueBus } from './cues';
import {
  audioCuesAvailable,
  createCueBus,
  cueForPhase,
  getSoundOn,
  setSoundOn,
  useSoundOn,
  vibrationAvailable,
} from './cues';
import {
  applyAck,
  buildPut,
  mintSet,
  nextBatch,
  nextSetIndex,
  quarantine,
  recordSet,
} from './outbox';
import type { BlockRange, CompiledPhase } from './protocol';
import { blockRanges, compileProtocol } from './protocol';
import type { ItemStatus, RunItem, RunRecord } from './runStore';
import { createRun, getRun, setRun, updateRun, useRun } from './runStore';
import { localIsoDate } from './today';
import type { WakeLockView } from './wakeLock';
import {
  acquireWakeLock,
  releaseWakeLock,
  setKeepScreenOn,
  useKeepScreenOn,
  useWakeLock,
} from './wakeLock';

/**
 * The session machine: one hook, everything a player screen needs, no presentation.
 *
 * ⚠️ **`requestAnimationFrame` drives the display and `setInterval` never does.** A counter
 * decremented per interval drifts, and on a backgrounded phone it stops entirely. `tick()` is
 * derived from a timestamp on every call and is therefore **idempotent**, which is what lets a
 * rAF frame and the backup `setTimeout` both fire with no double advance.
 *
 * ⚠️ **`performance.now()` for elapsed maths, `Date.now()` only for persistence.** The anchor
 * `{perf, epoch}` is re-stamped on mount and on every `visible`/`pageshow`, so an NTP step or a
 * user changing the clock mid-session cannot rewind a phase.
 *
 * ⚠️ **The countdown is written to the DOM through `countdownRef`, never through state.** A
 * `setState` at 60 Hz re-renders the tree sixty times a second and `react-hooks`'
 * `set-state-in-effect` rejects it anyway. React re-renders on **commit points only**.
 *
 * ⚠️ **At most one cue per tick.** A phone that was away for four minutes crosses several
 * boundaries in a single `advance`; firing per boundary is the four-beeps-at-once bug. One cue
 * for the phase landed on, plus a resync notice, and the missed ones are gone.
 *
 * ⚠️ **PAUSE FREEZES THE INSTANT THE CLOCK IS READ AT; resuming SHIFTS THE PHASE START.** Every
 * number here is `now - phaseStartedAtEpochMs`, so a pause that merely stopped the loop would
 * resume having silently advanced. The frozen instant is persisted, which is what carries a
 * pause through a reload and a backgrounding. **The SESSION's elapsed clock keeps running**: it
 * is the wall duration behind `duration_minutes`, the server merges that with `GREATEST` so it
 * can only grow, and a call mid-session is time the session took.
 *
 * ⚠️ **STARTING THE SESSION STARTS NO TIMER.** A session is a LIST OF ITEMS — one per block —
 * and Start means "I am doing this session": it mints the run and its elapsed clock, which is
 * the only source of `duration_minutes`. Each item is then entered deliberately, and may be
 * marked completed or skipped without its timer ever running. Once the session is finished it
 * cannot be started again; the summary is the end of it.
 */

/** Where the run is. `idle` covers both "never started" and "abandoned". */
export type RunStatus = 'idle' | 'running' | 'finished';

/** How far behind the timer the climber was, so the banner can say it in words. */
export interface ResyncNotice {
  /** Phases that elapsed unseen — `advance`'s `skipped`, which is `crossed - 1`. */
  readonly skipped: number;
  /** Time between the tab going hidden and this tick, or `null` if it never went hidden. */
  readonly awayMs: number | null;
  /** The phase the run resumed on. */
  readonly landedOn: CompiledPhase | null;
}

export interface StartOptions {
  readonly session: PlanSession;
  /** `plan/blueprint.ts::exercisesByKey` — names are not in the plan response. */
  readonly exercises: ReadonlyMap<string, LibraryExercise>;
  readonly discipline: Discipline;
}

/** What the tap on an `open` phase knows. Everything is optional; the elapsed count-up is the
 * `actual_work_seconds` and is measured, not passed. */
export interface OpenOutcome {
  /** `false` is the "Didn't finish it" control: advance the phase, mint no set. */
  readonly logged?: boolean;
  readonly actualReps?: number | null;
  readonly rpe?: number | null;
}

/** One row of the session's list, joined against the frozen timeline for its copy. */
export interface ItemView {
  readonly blockIndex: number;
  readonly label: string;
  readonly setCount: number;
  readonly status: ItemStatus;
}

/** The backup timeout lands just after the boundary, never before it: firing early would make
 * `tick()` a no-op and leave the phase change waiting for the next throttled frame. */
const BOUNDARY_BACKUP_MS = 30;

interface Anchor {
  readonly perf: number;
  readonly epoch: number;
}

function anchorNow(): Anchor {
  return { perf: performance.now(), epoch: Date.now() };
}

/** `M:SS`, rounded UP: a countdown must show `0:01` until the second is actually spent. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(total / 60))}:${String(total % 60).padStart(2, '0')}`;
}

/** `M:SS`, rounded DOWN: a count-up must show `0:00` for the whole first second. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60))}:${String(total % 60).padStart(2, '0')}`;
}

/** The instant the clock is READ at: the frozen one while the item is paused, the wall clock
 *  otherwise. One expression, so nothing that derives a number can forget the pause. */
export function clockAt(run: RunRecord, nowEpochMs: number): number {
  return run.pausedAtEpochMs ?? nowEpochMs;
}

/** The text the countdown node should be showing right now, countdown or count-up. Bounded to
 *  the running item, so nothing is shown once its last phase is spent. */
export function clockText(run: RunRecord, nowEpochMs: number): string {
  const timeline = activeTimeline(run);
  const phase = timeline[run.cursor.phaseIndex];
  if (phase === undefined) return formatCountdown(0);
  const at = clockAt(run, nowEpochMs);
  if (phase.durationMs === null) return formatElapsed(phaseElapsedMs(run.cursor, at));
  return formatCountdown(remainingMs(run.cursor, timeline, at) ?? 0);
}

/** The phases a single `advance` walked past, each with the wall-clock instant it ended.
 * Derived by ADDING durations, so a five-minute gap logs five sets with honest timestamps. */
function crossedPhases(
  run: RunRecord,
  from: Cursor,
  toPhaseIndex: number,
): { phase: CompiledPhase; endedAtEpochMs: number }[] {
  const walked: { phase: CompiledPhase; endedAtEpochMs: number }[] = [];
  let start = from.phaseStartedAtEpochMs;
  for (let index = from.phaseIndex; index < toPhaseIndex; index += 1) {
    const phase = run.timeline[index];
    if (phase === undefined) break;
    start += phase.durationMs ?? 0;
    walked.push({ phase, endedAtEpochMs: start });
  }
  return walked;
}

/** `completed_at` is optional on the wire, so an absent one is treated as "before the tab ever
 * went hidden" — the conservative answer, which keeps the set rather than dropping it. */
function completedAtEpochMs(set: LoggedSetInput): number {
  const parsed = set.completed_at == null ? NaN : Date.parse(set.completed_at);
  return Number.isNaN(parsed) ? -Infinity : parsed;
}

/** A timed set that ran to its boundary did the work the plan asked for; `repeaters` does it
 * `target_reps` times, and `targetWorkSeconds` is per rep. A tap-ended `open` set never gets
 * here — its elapsed count-up is measured instead. */
function autoWorkSeconds(phase: CompiledPhase): number | null {
  if (phase.targetWorkSeconds === null) return null;
  const reps = phase.protocolKind === 'repeaters' ? Math.max(1, phase.targetReps ?? 1) : 1;
  return phase.targetWorkSeconds * reps;
}

/**
 * The phases of the item that is running, and nothing after them.
 *
 * ⚠️ **The bound is a SLICE, so the indices are unchanged** — `clock.ts` walks off the end and
 * reports `done` instead of rolling the countdown into the next block, and it learns nothing
 * about blocks. Cached on identity because `tick()` reads it on every animation frame.
 */
let boundsCache: {
  timeline: readonly CompiledPhase[];
  blockIndex: number;
  bounded: readonly CompiledPhase[];
} | null = null;

export function activeTimeline(run: RunRecord | null): readonly CompiledPhase[] {
  const blockIndex = run?.activeBlockIndex ?? null;
  if (run === null || blockIndex === null) return [];
  const cached = boundsCache;
  if (cached !== null && cached.timeline === run.timeline && cached.blockIndex === blockIndex) {
    return cached.bounded;
  }
  const range = rangeFor(run.timeline, blockIndex);
  const bounded = range === undefined ? [] : run.timeline.slice(0, range.end);
  boundsCache = { timeline: run.timeline, blockIndex, bounded };
  return bounded;
}

function rangeFor(timeline: readonly CompiledPhase[], blockIndex: number): BlockRange | undefined {
  return blockRanges(timeline).find((entry) => entry.blockIndex === blockIndex);
}

function itemFor(run: RunRecord, blockIndex: number): RunItem | undefined {
  return run.items.find((entry) => entry.blockIndex === blockIndex);
}

/**
 * The index of the first phase of the set AFTER the one in play, or `null` when there is none.
 *
 * ⚠️ **A between-sets rest carries NO `setOfBlock`** — `protocol.ts::structural` leaves it null —
 * so the set in play has to be read BACKWARDS from the cursor, not forwards. Read forwards, the
 * rest after set 1 would report set 2 as current and "next set" would land on set 3, skipping
 * the one the climber asked for. The rest after a set belongs to that set, and standing in it is
 * exactly when this control is wanted.
 *
 * `null` before the first set has begun, which is also what keeps the control off a single-set
 * item: once its one set is in play there is no later ordinal to find.
 */
function nextSetStart(run: RunRecord): number | null {
  const timeline = activeTimeline(run);
  const current = timeline[run.cursor.phaseIndex];
  if (current === undefined) return null;

  let inPlay = 0;
  for (let index = run.cursor.phaseIndex; index >= 0; index -= 1) {
    const phase = timeline[index];
    if (phase === undefined || phase.blockIndex !== current.blockIndex) break;
    if (phase.setOfBlock !== null) {
      inPlay = phase.setOfBlock;
      break;
    }
  }
  if (inPlay === 0) return null;

  for (let index = run.cursor.phaseIndex + 1; index < timeline.length; index += 1) {
    const phase = timeline[index];
    if (phase === undefined || phase.blockIndex !== current.blockIndex) break;
    if (phase.setOfBlock !== null && phase.setOfBlock > inPlay) return index;
  }
  return null;
}

/** Record how an item ended, and stop its timer if it was the one running. A pause belongs to
 *  the item that was running, so closing that item takes it with them. */
function markItem(run: RunRecord, blockIndex: number, status: ItemStatus): RunRecord {
  const wasActive = run.activeBlockIndex === blockIndex;
  return {
    ...run,
    activeBlockIndex: wasActive ? null : run.activeBlockIndex,
    pausedAtEpochMs: wasActive ? null : run.pausedAtEpochMs,
    items: run.items.map((item) => (item.blockIndex === blockIndex ? { ...item, status } : item)),
  };
}

/** Whatever is running, closed. A no-op when nothing is. */
function closeActiveItem(run: RunRecord, status: ItemStatus): RunRecord {
  const blockIndex = run.activeBlockIndex;
  return blockIndex === null ? run : markItem(run, blockIndex, status);
}

/**
 * Forget the sets this attempt minted and never got acknowledged.
 *
 * ⚠️ **Acked sets are LEFT ALONE, and that is the honest half.** `logged_set` rows cannot be
 * deleted — there is no endpoint (issue #81) — so the server keeps them whatever this device
 * does, and dropping the local copy would make the summary describe a run the diary does not
 * have. Only `pending` goes, which is exactly the move "Restart this phase" already makes, and
 * for the same reason: an unacknowledged set is by construction one nothing else knows about.
 */
function dropUnflushed(run: RunRecord, blockIndex: number): RunRecord {
  const range = rangeFor(run.timeline, blockIndex);
  const item = itemFor(run, blockIndex);
  if (range?.firstSetIndex == null || range.lastSetIndex === null || item === undefined) {
    return run;
  }
  const low = range.firstSetIndex + item.setIndexOffset;
  const high = range.lastSetIndex + item.setIndexOffset;
  return {
    ...run,
    pending: run.pending.filter((set) => set.set_index < low || set.set_index > high),
  };
}

/** "I did this one myself": the item's prescribed sets, logged with NO measured value. Every
 *  `actual_*` field is optional on the wire, and inventing numbers nobody measured is worse. */
function logPrescribedSets(run: RunRecord, blockIndex: number, nowEpochMs: number): RunRecord {
  const range = rangeFor(run.timeline, blockIndex);
  if (range === undefined) return run;
  // ⚠️ The ceiling is read BEFORE anything is minted, exactly as `startItem` reads it before
  // its drop: an ordinal this run has ever issued is never handed out a second time.
  let ordinal = nextSetIndex(run);
  const already = new Set<number>();
  for (const set of [...run.logged, ...run.pending]) {
    if (set.prescribed_set_id != null) already.add(set.prescribed_set_id);
  }

  let next = run;
  for (const phase of run.timeline.slice(range.start, range.end)) {
    if (!phase.completesSet) continue;
    // A set this attempt already logged is not logged twice: the clock may have minted some of
    // them before the climber pressed the tick.
    if (phase.prescribedSetId !== null && already.has(phase.prescribedSetId)) continue;
    const set = mintSet({ ...phase, setIndex: ordinal }, { completedAtEpochMs: nowEpochMs });
    if (set === null) continue;
    ordinal += 1;
    next = recordSet(next, set);
  }
  return next;
}

/** The phase with its ordinal shifted by the item's current attempt — see `RunItem`. */
function offsetPhase(phase: CompiledPhase, run: RunRecord): CompiledPhase {
  const offset = itemFor(run, phase.blockIndex)?.setIndexOffset ?? 0;
  if (offset === 0 || phase.setIndex === null) return phase;
  return { ...phase, setIndex: phase.setIndex + offset };
}

export interface SessionRun {
  readonly status: RunStatus;
  /** The persisted record, or `null`. Re-rendered on commit points only. */
  readonly run: RunRecord | null;
  /** The phase the run is on, or `null` when the timeline is spent. Drives `data-phase`. */
  readonly phase: CompiledPhase | null;
  readonly phaseIndex: number;
  readonly phaseCount: number;
  /** ⚠️ **Attach this to the countdown node.** Its `textContent` is written per frame. */
  readonly countdownRef: React.RefObject<HTMLElement | null>;
  /** What that node should say right now — for the first paint, before rAF has run once. */
  readonly initialClockText: string;
  /** `true` when a cue could reach the climber at all — a tone, a buzz, or both. Gates the mute
   *  toggle and nothing else: a control over two channels that do not exist is a lie. */
  readonly cuesAvailable: boolean;
  /** The mute preference, persisted under `ct:sound`. Drives the toggle's icon and label. */
  readonly soundOn: boolean;
  /** ⚠️ **Call this straight out of the click.** Unmuting plays a cue, which is what folds the
   *  old "Test sound" button into the toggle — and the `AudioContext` it needs can only be
   *  built inside a gesture. */
  readonly toggleSound: () => void;
  /** Render the "Keep screen on" switch only when `available`; check it from `held`. */
  readonly wakeLock: WakeLockView;
  /** What the climber last asked for. The switch's `aria-checked` is `wakeLock.held`. */
  readonly keepScreenOn: boolean;
  readonly toggleKeepScreenOn: () => void;
  /** `true` while the running item is paused: the countdown is frozen, no phase advances and
   *  no cue fires. Survives a reload and a backgrounding — see `RunRecord.pausedAtEpochMs`. */
  readonly paused: boolean;
  /** Pause the running item, or resume it. A no-op when nothing is running. */
  readonly togglePause: () => void;
  /** `true` when the running item has a set after the one in progress. */
  readonly nextSetAvailable: boolean;
  /** Abandon the rest of the current set and land on the start of the next one, logging the
   *  sets the jump crossed. */
  readonly nextSet: () => void;
  /** Non-null while the banner is owed. Dismiss with `keepGoing` or `restartPhase`. */
  readonly resync: ResyncNotice | null;
  readonly keepGoing: () => void;
  readonly restartPhase: () => void;
  /** The session's items, in timeline order. Empty until the session is started. */
  readonly items: readonly ItemView[];
  /** Mints the run, arms audio inside your click handler, and sends the Tier-1 start PUT.
   *  **No timer starts** — see the item controls below. */
  readonly start: (options: StartOptions) => void;
  /** Enter an item, or re-enter one that was completed or skipped. Restarting appends new
   *  sets under new ordinals; it never rewrites what the server already has. */
  readonly startItem: (blockIndex: number) => void;
  /** "I did this" — with or without ever running its timer. It LOGS the item's prescribed sets
   *  with no measured values, so a manual completion counts toward the completion percentage. */
  readonly completeItem: (blockIndex: number) => void;
  /** "I did not do this." Drops the attempt's unflushed sets; acked ones stay. */
  readonly skipItem: (blockIndex: number) => void;
  /** The tap that ends an `open` phase. The elapsed count-up becomes `actual_work_seconds`. */
  readonly completeOpenPhase: (outcome?: OpenOutcome) => void;
  /** "Didn't finish it" — advance without logging. */
  readonly skipOpenPhase: () => void;
  readonly finish: () => void;
  /** "Done" on the summary. Persisted on the record — see `summaryClosedAtEpochMs`. */
  readonly closeSummary: () => void;
  /** Reopen a finished run LOCALLY. Sends nothing and un-finishes nothing server-side. */
  readonly resume: () => void;
  /** Discard the run. Nothing is sent; whatever the server already acked stays acked. */
  readonly abort: () => void;
  /** The second finishing PUT, so pressing Finish persists even if they walk away. */
  readonly setSessionRpe: (rpe: number) => void;
  /** The Retry control after a 5xx. The same flush the triggers run, on demand. */
  readonly retryFlush: () => void;
  /** Sets minted but not yet acknowledged. */
  readonly unsentCount: number;
  /** Sets a 4xx refused. **Never resent**; the summary says so. */
  readonly quarantinedCount: number;
  readonly isSaving: boolean;
  /** `false` in demo scope: the player runs in full and no PUT is ever issued. */
  readonly writes: boolean;
}

export function useSessionRun(): SessionRun {
  const run = useRun();
  const { scope } = useAuth();
  const canWrite = writesEnabled(scope);
  const put = useSessionLogPut();
  const putRef = useRef(put);
  useEffect(() => {
    putRef.current = put;
  }, [put]);

  const [cueBus] = useState<CueBus>(createCueBus);
  const soundOn = useSoundOn();
  const [resync, setResync] = useState<ResyncNotice | null>(null);
  const anchorRef = useRef<Anchor>(anchorNow());
  const countdownRef = useRef<HTMLElement | null>(null);
  const boundaryRef = useRef<{ id: number; at: number } | null>(null);
  const tickRef = useRef<() => void>(() => undefined);

  const keepScreenOn = useKeepScreenOn();
  const status: RunStatus =
    run === null ? 'idle' : run.finishedAtEpochMs === null ? 'running' : 'finished';
  const wakeLock = useWakeLock(keepScreenOn && status === 'running');

  /** The one clock. `Date.now()` never appears in elapsed maths — only in what gets stored. */
  const nowEpoch = useCallback((): number => {
    const anchor = anchorRef.current;
    return anchor.epoch + (performance.now() - anchor.perf);
  }, []);

  const clearBoundary = useCallback((): void => {
    if (boundaryRef.current !== null) window.clearTimeout(boundaryRef.current.id);
    boundaryRef.current = null;
  }, []);

  /** The backup for throttled rAF. Re-armed only when the boundary MOVES, so a 60 Hz loop does
   * not schedule sixty timeouts a second; `tick()` being idempotent makes the overlap free. */
  const armBoundary = useCallback(
    (current: RunRecord | null, now: number): void => {
      // A paused run has no next boundary: the backup timeout is what would advance a phase
      // behind a frozen countdown, which is precisely the bug pausing exists to prevent.
      const left =
        current === null || current.pausedAtEpochMs !== null
          ? null
          : remainingMs(current.cursor, activeTimeline(current), now);
      if (left === null) {
        clearBoundary();
        return;
      }
      const at = Math.round(now + left);
      if (boundaryRef.current?.at === at) return;
      clearBoundary();
      boundaryRef.current = {
        at,
        id: window.setTimeout(() => {
          boundaryRef.current = null;
          tickRef.current();
        }, left + BOUNDARY_BACKUP_MS),
      };
    },
    [clearBoundary],
  );

  const paint = useCallback((current: RunRecord | null, now: number): void => {
    const node = countdownRef.current;
    if (node === null || current === null) return;
    const text = clockText(current, now);
    if (node.textContent !== text) node.textContent = text;
  }, []);

  const tick = useCallback((): void => {
    const current = getRun();
    if (current === null || current.finishedAtEpochMs !== null) return;
    if (current.activeBlockIndex === null) return;
    // Paused: repaint the frozen number and advance nothing. `tick()` is reachable from the
    // `visibilitychange` re-anchor as well as from the loop, so the guard lives here rather
    // than only in the effect that owns the loop.
    if (current.pausedAtEpochMs !== null) {
      clearBoundary();
      paint(current, current.pausedAtEpochMs);
      return;
    }
    const timeline = activeTimeline(current);
    const now = nowEpoch();
    const result = advance(current.cursor, timeline, now);

    if (result.crossed > 0) {
      const walked = crossedPhases(current, current.cursor, result.cursor.phaseIndex);
      // The commit point: one write for the whole crossing, however many boundaries it spanned.
      updateRun((record) => {
        let next: RunRecord = { ...record, cursor: result.cursor };
        for (const { phase, endedAtEpochMs } of walked) {
          if (!phase.completesSet) continue;
          const set = mintSet(offsetPhase(phase, record), {
            completedAtEpochMs: Math.round(endedAtEpochMs),
            actualReps: phase.targetReps,
            actualWorkSeconds: autoWorkSeconds(phase),
          });
          if (set !== null) next = recordSet(next, set);
        }
        // The item ran out of phases: it is done, and the clock stops here rather than
        // rolling into a block the climber has not chosen to start.
        return result.done ? closeActiveItem(next, 'completed') : next;
      });
      if (result.skipped > 0) {
        setResync({
          skipped: result.skipped,
          awayMs: current.hiddenAtEpochMs === null ? null : now - current.hiddenAtEpochMs,
          landedOn: result.landedOn,
        });
      }
      // ONE cue, and only with the tab in front of the climber: a beep from a backgrounded tab
      // is for a phase that ended minutes ago.
      if (document.visibilityState === 'visible') {
        cueBus.play(cueForPhase(result.landedOn?.kind ?? null));
      }
    }

    const latest = getRun();
    paint(latest, now);
    armBoundary(latest, now);
  }, [armBoundary, clearBoundary, cueBus, nowEpoch, paint]);

  useEffect(() => {
    tickRef.current = tick;
  }, [tick]);

  /**
   * One flush, whatever triggered it.
   *
   * ⚠️ **The triggers are Start, Finish, `visibilitychange`→hidden and `online`. There is NO
   * debounce and NO item-count threshold**, and adding one is the well-meaning change that
   * undoes the design: the persisted run is authoritative and has exactly one writer, so a
   * periodic flush buys nothing and holds a serverless Postgres awake for the whole 45–90
   * minute session. "Add a debounce so we don't lose data" loses no data and costs real money.
   */
  const flush = useCallback(
    async (options: { finished?: boolean; force?: boolean } = {}): Promise<void> => {
      const current = getRun();
      if (current === null) return;
      const finished = options.finished ?? false;
      const batch = nextBatch(current);
      if (batch.length === 0 && !finished && options.force !== true) return;
      const body = buildPut(current, { sets: batch, finished, nowEpochMs: nowEpoch() });

      if (!canWrite) {
        // Demo scope: #65 satisfied by absence. Settled locally so the summary shows the run.
        updateRun((record) =>
          applyAck(
            record,
            batch.map((set: LoggedSetInput) => ({
              client_uuid: set.client_uuid,
              id: 0,
              set_index: set.set_index,
            })),
          ),
        );
        return;
      }

      try {
        const response = await putRef.current.mutateAsync({
          clientUuid: current.clientUuid,
          body,
        });
        updateRun((record) => ({
          ...applyAck(record, response?.sets ?? []),
          savedAtEpochMs: Date.now(),
        }));
      } catch (error) {
        updateRun((record) =>
          classifyFailure(error) === 'quarantine'
            ? quarantine(record, batch)
            : // Requeue is a no-op while the batch is still pending, which is the normal case:
              // a set leaves `pending` on its ACK and on nothing else.
              record,
        );
      }
    },
    [canWrite, nowEpoch],
  );

  const start = useCallback(
    (options: StartOptions): void => {
      // ⚠️ Inside the click gesture, synchronously. An AudioContext built anywhere else starts
      // suspended and, on iOS, never resumes.
      cueBus.arm();
      anchorRef.current = anchorNow();
      const startedAtEpochMs = Date.now();
      setRun(
        createRun({
          occurredOn: localIsoDate(new Date(startedAtEpochMs)),
          discipline: options.discipline,
          plannedSessionId: options.session.id ?? null,
          startedAtEpochMs,
          timeline: compileProtocol(options.session, options.exercises),
        }),
      );
      setResync(null);
      void flush({ force: true });
    },
    [cueBus, flush],
  );

  const completeOpenPhase = useCallback(
    (outcome: OpenOutcome = {}): void => {
      const current = getRun();
      if (current === null || current.finishedAtEpochMs !== null) return;
      const timeline = activeTimeline(current);
      const phase = timeline[current.cursor.phaseIndex];
      if (phase === undefined || phase.durationMs !== null) return;
      const now = Math.round(nowEpoch());
      // Measured at the FROZEN instant: a climber who paused mid-circuit and tapped Done ten
      // minutes later did not hang for ten minutes. Moving on ends the pause, because the next
      // phase is starting whether or not anyone says so.
      const workSeconds = Math.max(
        0,
        Math.round(phaseElapsedMs(current.cursor, clockAt(current, now)) / 1000),
      );

      updateRun((record) => {
        const cursor: Cursor = {
          phaseIndex: record.cursor.phaseIndex + 1,
          phaseStartedAtEpochMs: now,
        };
        let next: RunRecord = { ...record, cursor, pausedAtEpochMs: null };
        if (phase.completesSet && outcome.logged !== false) {
          const set = mintSet(offsetPhase(phase, record), {
            completedAtEpochMs: now,
            actualReps: outcome.actualReps ?? phase.targetReps,
            actualWorkSeconds: workSeconds,
            rpe: outcome.rpe ?? null,
          });
          if (set !== null) next = recordSet(next, set);
        }
        return timeline[cursor.phaseIndex] === undefined
          ? closeActiveItem(next, 'completed')
          : next;
      });

      const landed = timeline[current.cursor.phaseIndex + 1] ?? null;
      if (document.visibilityState === 'visible') {
        cueBus.play(cueForPhase(landed?.kind ?? null));
      }
      paint(getRun(), now);
    },
    [cueBus, nowEpoch, paint],
  );

  const skipOpenPhase = useCallback((): void => {
    completeOpenPhase({ logged: false });
  }, [completeOpenPhase]);

  /**
   * Enter an item — the deliberate press that Start on the session deliberately is not.
   *
   * ⚠️ **A RESTART APPENDS; it never rewrites.** The attempt's unflushed sets are dropped and
   * everything the server acknowledged is kept, so the new attempt has to mint ordinals nobody
   * has used: `nextSetIndex` picks the base and `RunItem.setIndexOffset` carries it. Reusing
   * the block's own 1..N would collide with the acked rows on `set_index`, which is a
   * `cardinality_violation` — a 422 that quarantines the whole flush.
   */
  const startItem = useCallback(
    (blockIndex: number): void => {
      const current = getRun();
      if (current === null || current.finishedAtEpochMs !== null) return;
      const range = rangeFor(current.timeline, blockIndex);
      if (range === undefined) return;
      // Inside the click, like `start` — an AudioContext built anywhere else never resumes.
      cueBus.arm();
      const now = Math.round(nowEpoch());

      updateRun((record) => {
        // Leaving one item for another COMPLETES it: it logged whatever it logged, and how
        // much of it got done is a derived query over those sets, never a status.
        const closed = closeActiveItem(record, 'completed');
        // ⚠️ The ceiling is read BEFORE the drop, so an ordinal this run has ever minted is
        // never handed out twice. A dropped set was unacknowledged, not provably unwritten —
        // a 5xx can arrive after the server committed — and reusing its ordinal under a new
        // `client_uuid` would be the `set_index` collision this offset exists to avoid.
        const ceiling = nextSetIndex(closed);
        const cleared = dropUnflushed(closed, blockIndex);
        const runs = (itemFor(cleared, blockIndex)?.runs ?? 0) + 1;
        // ⚠️ Read off the CEILING alone, never off `runs`: "I did this one myself" issues
        // ordinals without ever starting the item, so a FIRST start can walk into used ones.
        const offset =
          range.firstSetIndex === null ? 0 : Math.max(0, ceiling - range.firstSetIndex);
        return {
          ...cleared,
          activeBlockIndex: blockIndex,
          // A restart is a fresh attempt, so it can never inherit the previous one's pause.
          pausedAtEpochMs: null,
          cursor: { phaseIndex: range.start, phaseStartedAtEpochMs: now },
          items: cleared.items.map((item) =>
            item.blockIndex === blockIndex
              ? { ...item, status: 'running' as const, runs, setIndexOffset: offset }
              : item,
          ),
        };
      });

      setResync(null);
      paint(getRun(), now);
    },
    [cueBus, nowEpoch, paint],
  );

  const completeItem = useCallback(
    (blockIndex: number): void => {
      const current = getRun();
      if (current === null || current.finishedAtEpochMs !== null) return;
      const now = Math.round(nowEpoch());
      updateRun((record) =>
        markItem(
          // Pressing it twice logs once: the second press has nothing left to claim.
          itemFor(record, blockIndex)?.status === 'completed'
            ? record
            : logPrescribedSets(record, blockIndex, now),
          blockIndex,
          'completed',
        ),
      );
    },
    [nowEpoch],
  );

  const skipItem = useCallback((blockIndex: number): void => {
    const current = getRun();
    if (current === null || current.finishedAtEpochMs !== null) return;
    updateRun((record) => markItem(dropUnflushed(record, blockIndex), blockIndex, 'skipped'));
  }, []);

  /**
   * Pause the running item, or resume it — "sometimes you will need to pause in the middle of an
   * exercise because of a call".
   *
   * ⚠️ **Resuming SHIFTS `phaseStartedAtEpochMs` forward by the paused duration**, it does not
   * re-stamp it to now. Re-stamping would silently restart the phase and hand back time the
   * climber had already spent; shifting is what makes "paused at 0:04 left" resume at 0:04 left
   * however long the pause was, reload and backgrounding included.
   */
  const togglePause = useCallback((): void => {
    const current = getRun();
    if (current === null || current.finishedAtEpochMs !== null) return;
    if (current.activeBlockIndex === null) return;
    const now = Math.round(nowEpoch());
    const pausedAt = current.pausedAtEpochMs;

    if (pausedAt === null) {
      clearBoundary();
      updateRun((record) => ({ ...record, pausedAtEpochMs: now }));
      paint(getRun(), now);
      return;
    }

    const heldMs = Math.max(0, now - pausedAt);
    updateRun((record) => ({
      ...record,
      pausedAtEpochMs: null,
      cursor: {
        ...record.cursor,
        phaseStartedAtEpochMs: record.cursor.phaseStartedAtEpochMs + heldMs,
      },
    }));
    // Resuming is a click, which is the only place an `AudioContext` may be built — and a run
    // resumed after a reload has never had one.
    cueBus.arm();
    paint(getRun(), now);
    armBoundary(getRun(), now);
  }, [armBoundary, clearBoundary, cueBus, nowEpoch, paint]);

  /**
   * "I did the first set but I have to move on" — abandon the rest of the current set and land
   * on the start of the next one.
   *
   * ⚠️ **The sets the jump crosses are LOGGED, not dropped.** The usual case is a climber who
   * finished the hang and is cutting the rest short, so the work phase behind the cursor really
   * was done; a jump that dropped it would lose a set the climber performed. Anything already
   * minted by the clock is behind the cursor and is not re-minted, so no ordinal is issued twice.
   */
  const nextSet = useCallback((): void => {
    const current = getRun();
    if (current === null || current.finishedAtEpochMs !== null) return;
    if (current.activeBlockIndex === null) return;
    const target = nextSetStart(current);
    if (target === null) return;
    const now = Math.round(nowEpoch());

    updateRun((record) => {
      let next: RunRecord = {
        ...record,
        pausedAtEpochMs: null,
        cursor: { phaseIndex: target, phaseStartedAtEpochMs: now },
      };
      for (let index = record.cursor.phaseIndex; index < target; index += 1) {
        const phase = record.timeline[index];
        if (phase === undefined || !phase.completesSet) continue;
        const set = mintSet(offsetPhase(phase, record), {
          completedAtEpochMs: now,
          actualReps: phase.targetReps,
          actualWorkSeconds: autoWorkSeconds(phase),
        });
        if (set !== null) next = recordSet(next, set);
      }
      return next;
    });

    cueBus.arm();
    if (document.visibilityState === 'visible') {
      cueBus.play(cueForPhase(activeTimeline(getRun())[target]?.kind ?? null));
    }
    setResync(null);
    paint(getRun(), now);
    armBoundary(getRun(), now);
  }, [armBoundary, cueBus, nowEpoch, paint]);

  /** The mute toggle. Unmuting plays a cue: that is the old "Test sound" button, folded in. */
  const toggleSound = useCallback((): void => {
    const next = !getSoundOn();
    setSoundOn(next);
    // ⚠️ Straight out of the click, like `start` — a context built anywhere else never resumes.
    if (next) cueBus.testSound();
  }, [cueBus]);

  const finish = useCallback((): void => {
    updateRun((record) => ({
      ...closeActiveItem(record, 'completed'),
      pausedAtEpochMs: null,
      finishedAtEpochMs: Math.round(nowEpoch()),
    }));
    setResync(null);
    clearBoundary();
    void flush({ finished: true, force: true });
  }, [clearBoundary, flush, nowEpoch]);

  /** The summary has been read. On the RECORD, never in component state — see `runStore`. */
  const closeSummary = useCallback((): void => {
    updateRun((record) => ({ ...record, summaryClosedAtEpochMs: Math.round(nowEpoch()) }));
  }, [nowEpoch]);

  /** "Go back to the session", LOCAL only. ⚠️ Sends NOTHING: `finished: false` cannot move
   *  `planned_session.status` backwards, and `sets` is a delta, so re-finishing cannot re-log. */
  const resume = useCallback((): void => {
    updateRun((record) =>
      record.finishedAtEpochMs === null
        ? record
        : { ...record, finishedAtEpochMs: null, summaryClosedAtEpochMs: null },
    );
    setResync(null);
  }, []);

  const abort = useCallback((): void => {
    clearBoundary();
    cueBus.close();
    setRun(null);
    setResync(null);
  }, [clearBoundary, cueBus]);

  const setSessionRpe = useCallback(
    (rpe: number): void => {
      updateRun((record) => ({ ...record, sessionRpe: rpe }));
      void flush({ finished: true, force: true });
    },
    [flush],
  );

  const retryFlush = useCallback((): void => {
    void flush();
  }, [flush]);

  /** "Keep going" — the timer is right, the banner goes away. */
  const keepGoing = useCallback((): void => {
    setResync(null);
  }, []);

  /**
   * "Restart this phase" — re-stamp the phase's start to now and drop the sets the clock minted
   * while nobody was watching. Safe precisely because tab-hidden is itself a flush trigger: a
   * set logged after `hiddenAtEpochMs` is by construction still `pending`, never acknowledged.
   */
  const restartPhase = useCallback((): void => {
    const now = Math.round(nowEpoch());
    updateRun((record) => {
      const since = record.hiddenAtEpochMs;
      return {
        ...record,
        cursor: { ...record.cursor, phaseStartedAtEpochMs: now },
        pending: record.pending.filter((set) => completedAtEpochMs(set) <= (since ?? Infinity)),
      };
    });
    setResync(null);
    paint(getRun(), now);
  }, [nowEpoch, paint]);

  const activeBlockIndex = run?.activeBlockIndex ?? null;
  const paused = run?.pausedAtEpochMs != null;

  // The display loop. Nothing counts here — every frame re-derives from the wall clock, so a
  // dropped frame, a throttled tab and the backup timeout all produce the same answer. It runs
  // only while an ITEM is running and NOT paused: a started session with nothing entered has no
  // countdown, and a paused one has a number that must not move. `togglePause` paints both ends
  // of the pause, so stopping the loop costs no frame the climber would have seen.
  useEffect(() => {
    if (status !== 'running' || activeBlockIndex === null || paused) return;
    let frame = requestAnimationFrame(function loop() {
      tickRef.current();
      frame = requestAnimationFrame(loop);
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [activeBlockIndex, paused, status]);

  useEffect(() => clearBoundary, [clearBoundary]);

  // Re-anchoring is what makes the wake lock optional: whether or not a lock was ever held, the
  // run resyncs from wall-clock time the moment the tab is in front of the climber again.
  useEffect(() => {
    const reanchor = (): void => {
      anchorRef.current = anchorNow();
      tickRef.current();
    };
    const onVisibility = (): void => {
      if (document.visibilityState !== 'hidden') {
        cueBus.resume();
        reanchor();
        return;
      }
      updateRun((record) => ({ ...record, hiddenAtEpochMs: Date.now() }));
      void flush();
    };
    const onOnline = (): void => {
      void flush();
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pageshow', reanchor);
    window.addEventListener('online', onOnline);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pageshow', reanchor);
      window.removeEventListener('online', onOnline);
    };
  }, [cueBus, flush]);

  useEffect(() => {
    return () => {
      cueBus.close();
    };
  }, [cueBus]);

  const phase = run === null ? null : (activeTimeline(run)[run.cursor.phaseIndex] ?? null);

  const items = useMemo<ItemView[]>(() => {
    if (run === null) return [];
    const ranges = blockRanges(run.timeline);
    return run.items.map((item) => {
      const range = ranges.find((entry) => entry.blockIndex === item.blockIndex);
      return {
        blockIndex: item.blockIndex,
        label: range?.label ?? '',
        setCount: range?.setsInBlock ?? 0,
        status: item.status,
      };
    });
  }, [run]);

  return {
    status,
    run,
    phase,
    phaseIndex: run?.cursor.phaseIndex ?? 0,
    phaseCount: run?.timeline.length ?? 0,
    countdownRef,
    initialClockText: run === null ? formatCountdown(0) : clockText(run, nowEpoch()),
    cuesAvailable: audioCuesAvailable() || vibrationAvailable(),
    soundOn,
    toggleSound,
    wakeLock,
    keepScreenOn,
    toggleKeepScreenOn: () => {
      // ⚠️ The intent is read off WHAT IS SHOWN, not off the stored preference. The two are
      // allowed to disagree — the OS drops the lock on every backgrounding — and a click that
      // set the preference to a value `held` already showed did nothing the climber could see.
      const next = !wakeLock.held;
      setKeepScreenOn(next);
      // The preference may already be `true`, in which case `setKeepScreenOn` was a no-op and
      // only an explicit re-acquire can put the lock back.
      if (next && status === 'running') void acquireWakeLock();
      if (!next) void releaseWakeLock();
    },
    paused,
    togglePause,
    nextSetAvailable: run === null ? false : nextSetStart(run) !== null,
    nextSet,
    resync,
    keepGoing,
    restartPhase,
    items,
    start,
    startItem,
    completeItem,
    skipItem,
    completeOpenPhase,
    skipOpenPhase,
    finish,
    closeSummary,
    resume,
    abort,
    setSessionRpe,
    retryFlush,
    unsentCount: run?.pending.length ?? 0,
    quarantinedCount: run?.quarantined.length ?? 0,
    isSaving: put.isPending,
    writes: canWrite,
  };
}
