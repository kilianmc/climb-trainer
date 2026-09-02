import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { createElement } from 'react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setSoundOn } from './cues';
import { makeBlock, makeLibrary, makeSession, makeSet } from './fixtures';
import { RUN_STORAGE_KEY, parseRun, setRun } from './runStore';
import { useSessionRun } from './useSessionRun';

/**
 * The machine, driven by a clock the test owns. Four named bugs, each made executable:
 *
 * 1. **Advance WHILE overdue.** A backgrounded phone returns minutes late; advancing once per
 *    tick would leave the run five phases behind and never catch up.
 * 2. **Suppress missed cues.** Those five boundaries must produce ONE cue, not five.
 * 3. **`tick()` is idempotent.** rAF and the backup `setTimeout` both fire; the second must be
 *    a no-op rather than a second advance.
 * 4. **No `setState` and no persistence per frame.** Sixty frames inside one phase write the
 *    countdown to the DOM and touch `localStorage` exactly never.
 *
 * Cues are counted through `navigator.vibrate`, which `CueBus.play` calls once per cue — the
 * one channel that is observable without reaching into the audio graph.
 *
 * ⚠️ **`start` no longer starts a timer**, so every clock test enters the first item explicitly.
 * That IS the interaction model: pressing Start on the session says "I am doing this session".
 *
 * 5. **A pause survives.** Every number here is derived from the wall clock, so a pause that
 *    only stopped the loop would resume having silently advanced. It is backgrounded for ten
 *    minutes and reloaded out of `ct:run` before it is resumed.
 */

const request = vi.fn();

vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => ({ request, scope: 'user' }),
}));

const START = Date.UTC(2026, 7, 28, 17, 0, 0);
const SECOND = 1000;

let clock = START;
let vibrate: ReturnType<typeof vi.fn>;

/** Six 10-second hangs with 20 seconds between them, behind a 15-second lead-in. */
function session() {
  return makeSession([
    makeBlock({
      protocol_kind: 'max_hang',
      exercise_id: 11,
      rest_between_sets_seconds: 20,
      sets: [1, 2, 3, 4, 5, 6].map((index) =>
        makeSet({ id: 500 + index, set_index: index, target_work_seconds: 10 }),
      ),
    }),
  ]);
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

function mount() {
  const view = renderHook(() => useSessionRun(), { wrapper });
  view.result.current.countdownRef.current = document.createElement('div');
  return view;
}

/** Run the rAF loop and any due backup timeout, without moving the wall clock. */
function pump(ms = 20): void {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

function at(seconds: number): void {
  clock = START + seconds * SECOND;
}

beforeEach(() => {
  clock = START;
  window.localStorage.clear();
  setRun(null);
  request.mockReset();
  request.mockImplementation(() =>
    Promise.resolve({ client_uuid: '00000000-0000-4000-8000-000000000000', sets: [] }),
  );
  vibrate = vi.fn(() => true);
  // The mute preference is a MODULE value, so a test that mutes leaks into the next one.
  setSoundOn(true);
  Object.defineProperty(navigator, 'vibrate', { value: vibrate, configurable: true });
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  vi.spyOn(Date, 'now').mockImplementation(() => clock);
  vi.spyOn(performance, 'now').mockImplementation(() => clock);
  vi.useFakeTimers({
    toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'setTimeout', 'clearTimeout'],
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  setRun(null);
});

async function startedSession() {
  const view = mount();
  await act(async () => {
    view.result.current.start({
      session: session(),
      exercises: makeLibrary(),
      discipline: 'sport',
      // Nothing pre-done: the timing machine is what this suite covers. See `sessionPlayer`.
      marks: null,
    });
    await Promise.resolve();
  });
  return view;
}

/** The session, plus its one item entered — which is what makes a clock run at all. */
async function startedRun() {
  const view = await startedSession();
  act(() => {
    view.result.current.startItem(0);
  });
  return view;
}

describe('the item machine', () => {
  it('starts NO timer when the session starts', async () => {
    const view = await startedSession();
    at(75);
    pump();

    expect(view.result.current.phase).toBeNull();
    expect(view.result.current.run?.activeBlockIndex).toBeNull();
    expect(view.result.current.items.map((item) => item.status)).toEqual(['pending']);
    // Nothing ran, so nothing was logged — the elapsed clock is the only thing moving.
    expect(view.result.current.unsentCount).toBe(0);
  });

  it('completes the item on its own once the last phase is spent', async () => {
    const view = await startedRun();
    at(300);
    pump();

    expect(view.result.current.items[0]?.status).toBe('completed');
    expect(view.result.current.run?.activeBlockIndex).toBeNull();
    expect(view.result.current.phase).toBeNull();
    expect(view.result.current.run?.pending.map((set) => set.set_index)).toEqual([
      1, 2, 3, 4, 5, 6,
    ]);
  });

  it('RESTARTS with ordinals nobody has used, and keeps what the server acked', async () => {
    const view = await startedRun();
    at(300);
    pump();

    // Two of the six reached the server; four are still only on this device.
    act(() => {
      setRun({
        ...view.result.current.run!,
        logged: view.result.current.run!.pending.slice(0, 2),
        pending: view.result.current.run!.pending.slice(2),
      });
    });

    act(() => {
      view.result.current.startItem(0);
    });

    // ⚠️ The four unflushed sets are gone and the two acked ones are UNTOUCHED: `logged_set`
    // rows cannot be deleted (#81), so the record must not claim they never happened.
    expect(view.result.current.run?.logged.map((set) => set.set_index)).toEqual([1, 2]);
    expect(view.result.current.unsentCount).toBe(0);
    expect(view.result.current.run?.items[0]?.runs).toBe(2);

    at(600);
    pump();
    // 7..12: one past the highest ordinal the run has ever used, so no `set_index` collides.
    expect(view.result.current.run?.pending.map((set) => set.set_index)).toEqual([
      7, 8, 9, 10, 11, 12,
    ]);
  });

  it('marks an item completed or skipped without ever running its timer', async () => {
    const view = await startedSession();
    act(() => {
      view.result.current.completeItem(0);
    });
    expect(view.result.current.items[0]?.status).toBe('completed');
    // ⚠️ A manual completion LOGS the item's prescribed sets — with no measured value on any of
    // them. Logging nothing would score the item zero in the completion percentage.
    expect(view.result.current.run?.pending.map((set) => set.set_index)).toEqual([
      1, 2, 3, 4, 5, 6,
    ]);
    expect(view.result.current.run?.pending.every((set) => set.actual_work_seconds === null)).toBe(
      true,
    );

    // Pressing it a second time claims nothing further: the sets are already outboxed.
    act(() => {
      view.result.current.completeItem(0);
    });
    expect(view.result.current.unsentCount).toBe(6);

    act(() => {
      view.result.current.skipItem(0);
    });
    expect(view.result.current.items[0]?.status).toBe('skipped');
    // …and a SKIPPED item logs nothing at all, which is how partial completion stays honest.
    expect(view.result.current.unsentCount).toBe(0);
    expect(view.result.current.run?.activeBlockIndex).toBeNull();
  });
});

describe('dropping the sets an item never sent', () => {
  /** Three blocks: the first prescribes three sets, the other two one each. One exercise per
   *  block, so a set names the part it belongs to. */
  function threeBlocks() {
    return makeSession([
      makeBlock({
        protocol_kind: 'max_hang',
        exercise_id: 11,
        rest_between_sets_seconds: 20,
        sets: [1, 2, 3].map((index) =>
          makeSet({ id: 500 + index, set_index: index, target_work_seconds: 10 }),
        ),
      }),
      makeBlock({
        id: 102,
        order_index: 1,
        exercise_key: 'front_lever',
        exercise_id: 12,
        sets: [makeSet({ id: 600, target_work_seconds: 10 })],
      }),
      makeBlock({
        id: 103,
        order_index: 2,
        exercise_key: 'lock_offs',
        exercise_id: 13,
        sets: [makeSet({ id: 700, target_work_seconds: 10 })],
      }),
    ]);
  }

  async function threeBlockSession() {
    const view = mount();
    await act(async () => {
      view.result.current.start({
        session: threeBlocks(),
        exercises: makeLibrary(),
        discipline: 'sport',
        marks: null,
      });
      await Promise.resolve();
    });
    return view;
  }

  /** Which PRESCRIPTION each unsent set was written against — the only thing that says whose
   *  set it is. `set_index` cannot: it is allocated from the run's global ceiling. */
  function unsent(view: Awaited<ReturnType<typeof threeBlockSession>>) {
    return view.result.current.run?.pending.map((set) => set.prescribed_set_id);
  }

  it('KEEPS a LATER block’s unsent sets when an EARLIER one is entered', async () => {
    const view = await threeBlockSession();
    // "I did this one myself" on the LAST part, before anything else: `nextSetIndex` reads a
    // global ceiling, so its set takes ordinal 1 — block 0's own natural range.
    act(() => {
      view.result.current.completeItem(2);
    });
    expect(view.result.current.run?.pending.map((set) => set.set_index)).toEqual([1]);

    act(() => {
      view.result.current.startItem(0);
    });

    // ⚠️ Sets the climber really recorded, on a part this one is not: an ordinal window dropped
    // them silently, and only while they were unsent — i.e. offline or on a slow network.
    expect(unsent(view)).toEqual([700]);
    expect(view.result.current.unsentCount).toBe(1);
  });

  it('drops the entered block’s OWN unsent sets, whatever ordinals they hold', async () => {
    const view = await threeBlockSession();
    act(() => {
      view.result.current.completeItem(2);
    });
    act(() => {
      view.result.current.completeItem(0);
    });
    expect(unsent(view)).toEqual([700, 501, 502, 503]);

    act(() => {
      view.result.current.skipItem(0);
    });
    expect(unsent(view)).toEqual([700]);
  });

  it('never drops an OFF-PLAN set, which belongs to no block at all', async () => {
    const view = await threeBlockSession();
    act(() => {
      setRun({
        ...view.result.current.run!,
        pending: [
          {
            client_uuid: '00000000-0000-4000-8000-0000000000ff',
            set_index: 1,
            exercise_id: 11,
            prescribed_set_id: null,
            actual_reps: null,
            actual_work_seconds: null,
            rpe: null,
            completed_at: new Date(START).toISOString(),
          },
        ],
      });
    });

    act(() => {
      view.result.current.skipItem(0);
    });
    expect(unsent(view)).toEqual([null]);
  });
});

describe('a phone that was backgrounded', () => {
  it('advances while overdue, fires ONE cue, and reports the phases it skipped', async () => {
    const view = await startedRun();
    pump();
    expect(vibrate).not.toHaveBeenCalled();

    // 15 lead-in + work/rest/work/rest = five boundaries crossed by a single tick.
    at(75);
    pump();

    expect(view.result.current.phaseIndex).toBe(5);
    expect(view.result.current.phase?.kind).toBe('work');
    expect(view.result.current.phase?.setIndex).toBe(3);
    expect(vibrate).toHaveBeenCalledTimes(1);
    expect(view.result.current.resync?.skipped).toBe(4);
  });

  it('logs every set the clock crossed — cues are suppressed, DATA never is', async () => {
    const view = await startedRun();
    at(75);
    pump();

    const pending = view.result.current.run?.pending ?? [];
    expect(pending.map((set) => set.set_index)).toEqual([1, 2]);
    // Ended by the clock, not by the tap, so the timestamps are the boundaries themselves.
    expect(pending.map((set) => set.completed_at)).toEqual([
      new Date(START + 25 * SECOND).toISOString(),
      new Date(START + 55 * SECOND).toISOString(),
    ]);
    expect(view.result.current.unsentCount).toBe(2);
  });

  it('is idempotent: the backup timeout firing after rAF advances nothing twice', async () => {
    const view = await startedRun();
    at(75);
    pump();
    const settled = view.result.current.run?.cursor;

    // Every remaining timer, including the boundary backup, on the same wall clock.
    pump(5000);
    expect(view.result.current.run?.cursor).toEqual(settled);
    expect(vibrate).toHaveBeenCalledTimes(1);
    expect(view.result.current.run?.pending).toHaveLength(2);
  });

  it('lets "Restart this phase" drop the sets minted while nobody was watching', async () => {
    const view = await startedRun();
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    at(75);
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(view.result.current.resync?.skipped).toBe(4);

    act(() => {
      view.result.current.restartPhase();
    });
    expect(view.result.current.resync).toBeNull();
    expect(view.result.current.unsentCount).toBe(0);
    expect(view.result.current.run?.cursor.phaseStartedAtEpochMs).toBe(clock);
  });
});

describe('pausing', () => {
  /** Hidden, then visible again, which is what a pocket does to a tab. */
  async function background(): Promise<void> {
    await act(async () => {
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
    });
    await act(async () => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
    });
  }

  it('freezes the countdown through a ten-minute backgrounding AND a reload', async () => {
    const view = await startedRun();
    // Five seconds into the first ten-second hang.
    at(20);
    pump();
    const node = view.result.current.countdownRef.current;
    expect(node?.textContent).toBe('0:05');

    act(() => {
      view.result.current.togglePause();
    });
    expect(view.result.current.paused).toBe(true);
    expect(node?.textContent).toBe('0:05');

    // Ten minutes in a pocket. The rAF loop is stopped, the boundary backup was cleared, and
    // the visibility re-anchor still runs `tick()` — which must advance nothing.
    at(620);
    await background();
    pump(60_000);

    expect(node?.textContent).toBe('0:05');
    expect(view.result.current.phaseIndex).toBe(1);
    expect(view.result.current.unsentCount).toBe(0);

    // …and a reload: the persisted record is all that survives, so the frozen instant has to
    // be part of it.
    view.unmount();
    const stored = parseRun(window.localStorage.getItem(RUN_STORAGE_KEY));
    expect(stored?.pausedAtEpochMs).toBe(START + 20 * SECOND);
    act(() => {
      setRun(stored);
    });
    const revived = mount();
    const revivedNode = revived.result.current.countdownRef.current;
    expect(revived.result.current.paused).toBe(true);

    // Resuming fifteen minutes after the pause began: the phase start shifts by the whole
    // pause, so what is left is what was left.
    at(900);
    act(() => {
      revived.result.current.togglePause();
    });
    expect(revived.result.current.paused).toBe(false);
    expect(revivedNode?.textContent).toBe('0:05');

    at(904);
    pump();
    expect(revivedNode?.textContent).toBe('0:01');

    at(906);
    pump();
    expect(revived.result.current.phaseIndex).toBe(2);
    expect(revived.result.current.run?.pending.map((set) => set.set_index)).toEqual([1]);
  });

  it('fires no cue while paused, and the session clock keeps running underneath', async () => {
    const view = await startedRun();
    at(20);
    pump();
    vibrate.mockClear();

    act(() => {
      view.result.current.togglePause();
    });
    at(620);
    pump(60_000);

    // Not one boundary crossed and not one cue, over ten minutes that would have crossed
    // twenty of them.
    expect(vibrate).not.toHaveBeenCalled();
    expect(view.result.current.run?.pending).toEqual([]);
    // ⚠️ The SESSION's elapsed clock is untouched by the pause — it is the wall duration and
    // the only source of `duration_minutes`, which the server merges with `GREATEST`.
    expect(view.result.current.run?.startedAtEpochMs).toBe(START);
  });
});

describe('the next-set control', () => {
  it('is hidden until a set is in play, and on the last set of the item', async () => {
    const view = await startedRun();
    // The block's fifteen-second lead-in: nothing to abandon yet.
    expect(view.result.current.nextSetAvailable).toBe(false);

    at(20);
    pump();
    expect(view.result.current.nextSetAvailable).toBe(true);

    // The sixth and last set of the fixture: 15 s lead-in + 6 hangs + 5 rests = 175 s, so its
    // work phase is the stretch from 165 to 175.
    at(170);
    pump();
    expect(view.result.current.phase?.setIndex).toBe(6);
    expect(view.result.current.nextSetAvailable).toBe(false);
  });

  it('logs the set it abandons and lands on the next set’s first phase', async () => {
    const view = await startedRun();
    // 30 s: set 1 is logged and the twenty-second rest after it is running.
    at(30);
    pump();
    expect(view.result.current.run?.pending.map((set) => set.set_index)).toEqual([1]);

    act(() => {
      view.result.current.nextSet();
    });

    // Set 2's work phase, started NOW — not set 3, which is where reading `setOfBlock` forwards
    // out of a structural rest would have landed.
    expect(view.result.current.phase?.kind).toBe('work');
    expect(view.result.current.phase?.setIndex).toBe(2);
    expect(view.result.current.run?.cursor.phaseStartedAtEpochMs).toBe(clock);
    // Nothing double-minted: set 1 was already logged by the clock crossing its boundary.
    expect(view.result.current.run?.pending.map((set) => set.set_index)).toEqual([1]);
  });

  it('logs the set it cuts short when the jump is made mid-work', async () => {
    const view = await startedRun();
    // Three seconds into set 1's hang — the set has NOT ended on its own.
    at(18);
    pump();
    expect(view.result.current.run?.pending).toEqual([]);

    act(() => {
      view.result.current.nextSet();
    });

    // "I did that one, I just have to move on": the set is logged rather than lost.
    expect(view.result.current.run?.pending.map((set) => set.set_index)).toEqual([1]);
    expect(view.result.current.phase?.setIndex).toBe(2);
  });
});

describe('the mute toggle', () => {
  it('silences every cue, and unmuting plays one so the climber hears it', async () => {
    const view = await startedRun();
    expect(view.result.current.soundOn).toBe(true);

    act(() => {
      view.result.current.toggleSound();
    });
    expect(view.result.current.soundOn).toBe(false);
    vibrate.mockClear();

    // Five boundaries crossed in one tick, and not a sound out of any of them.
    at(75);
    pump();
    expect(vibrate).not.toHaveBeenCalled();
    // Muted, never stalled: the run advanced exactly as it does with the cues on.
    expect(view.result.current.phaseIndex).toBe(5);

    act(() => {
      view.result.current.toggleSound();
    });
    // ⚠️ This IS the old "Test sound" button: unmuting proves itself with one cue.
    expect(vibrate).toHaveBeenCalledTimes(1);
  });
});

describe('the display loop', () => {
  it('writes the countdown to the DOM and never to localStorage', async () => {
    const view = await startedRun();
    const node = view.result.current.countdownRef.current;
    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    for (let second = 1; second <= 10; second += 1) {
      at(second);
      pump();
    }

    expect(node?.textContent).toBe('0:05');
    expect(setItem).not.toHaveBeenCalled();
  });

  it('persists on the phase change, and only there', async () => {
    const view = await startedRun();
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    at(10);
    pump();
    expect(setItem).not.toHaveBeenCalled();

    at(16);
    pump();
    expect(setItem).toHaveBeenCalledTimes(1);
    expect(view.result.current.phase?.kind).toBe('work');
  });
});

describe('the flush triggers', () => {
  it('sends the start PUT and then nothing at all while the run plays out', async () => {
    await startedRun();
    expect(request).toHaveBeenCalledTimes(1);
    const [, options] = request.mock.calls[0] as [string, { json: { duration_minutes: number } }];
    expect(options.json.duration_minutes).toBe(1);

    for (let second = 5; second <= 200; second += 5) {
      at(second);
      pump();
    }
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('flushes when the tab goes hidden, and again when the network comes back', async () => {
    await startedRun();
    at(75);
    pump();
    expect(request).toHaveBeenCalledTimes(1);

    await act(async () => {
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
    });
    expect(request).toHaveBeenCalledTimes(2);

    await act(async () => {
      window.dispatchEvent(new Event('online'));
      await Promise.resolve();
    });
    expect(request).toHaveBeenCalledTimes(3);
  });
});
