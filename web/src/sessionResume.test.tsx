import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { ExerciseLibrary, LoggedSetInput } from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';
import { makeBlock, makePlan, makeSession, makeSet, makeVocabulary } from './session/fixtures';
import { mintSet } from './session/outbox';
import { compileProtocol } from './session/protocol';
import type { RunRecord } from './session/runStore';
import { createRun, getRun, setRun } from './session/runStore';
import { localIsoDate } from './session/today';
import { getKeepScreenOn, setKeepScreenOn } from './session/wakeLock';
import { FakeWakeLockSentinel } from './test/setup';

/**
 * **Coming back to a run that was already going**, which on a phone is the normal case rather
 * than the exception: the screen locks between sets, the tab is throttled, and the wall clock
 * keeps moving whether or not JavaScript did.
 *
 * 1. **A multi-phase gap resumes on the right phase, with ONE cue and a banner.** Four beeps at
 *    once for four boundaries crossed in a pocket is the classic bug; the phases that elapsed
 *    unseen are gone, and the climber is told so in words instead.
 * 2. **"Restart this phase" drops only what was logged AFTER the tab went hidden.** It is safe
 *    precisely because tab-hidden is itself a flush trigger, so a set minted after it is by
 *    construction still pending — and a set minted before it must survive.
 * 3. **The toggle reads the SENTINEL, not the click.** The OS releases a wake lock silently
 *    when the tab is backgrounded; a control that still says "on" is a lie the climber discovers
 *    when the screen dies mid-set.
 * 4. **…and pressing it always DOES something** — the bug Kilian saw, in two halves. `held` and
 *    the stored preference are allowed to disagree, and once they do, a press that only flipped
 *    the preference changed nothing on screen; and an acquire still in flight when a release
 *    landed published its sentinel anyway, which is how they came to disagree in the first
 *    place. Both are below, and both were watched to fail against the code they fix.
 *
 * Cues are counted through `navigator.vibrate`, the one channel `CueBus.play` drives that is
 * observable without reaching into the audio graph — and the only one on a resumed run, whose
 * `AudioContext` was never armed because there was no Start click.
 */
const TODAY = localIsoDate(new Date());
const START = new Date(`${TODAY}T09:00:00`).getTime();
const SECOND = 1000;

/** Three 10-second hangs, 20 seconds apart, behind the 15-second lead-in.
 *  Boundaries at 15, 25, 45, 55, 75 and 85 seconds. */
function session() {
  return makeSession(
    [
      makeBlock({
        protocol_kind: 'max_hang',
        exercise_id: 11,
        rest_between_sets_seconds: 20,
        sets: [1, 2, 3].map((index) =>
          makeSet({ id: 500 + index, set_index: index, target_work_seconds: 10 }),
        ),
      }),
    ],
    TODAY,
  );
}

const LIBRARY: ExerciseLibrary = { exercises: [] };

let clock = START;
let vibrate: ReturnType<typeof vi.fn>;
let sentinels: FakeWakeLockSentinel[] = [];

/** A run already in progress, written to `ct:run` exactly as the player would have left it. */
function persistRun(overrides: Partial<RunRecord>): RunRecord {
  const base = createRun({
    occurredOn: TODAY,
    discipline: 'sport',
    plannedSessionId: 5001,
    startedAtEpochMs: START,
    timeline: compileProtocol(session(), new Map()),
    preDoneBlockIndexes: [],
  });
  // Item one entered: a resumed run is a run that was RUNNING something, and since the
  // rework a session with no active item has no clock to resync.
  const record = {
    ...base,
    activeBlockIndex: 0,
    items: base.items.map((item) => ({ ...item, status: 'running' as const, runs: 1 })),
    ...overrides,
  };
  setRun(record);
  return record;
}

/** The set the clock minted at the end of `work` phase `n`, as the run would have stored it. */
function loggedSet(record: RunRecord, phaseIndex: number, atSeconds: number): LoggedSetInput {
  const phase = record.timeline[phaseIndex];
  if (phase === undefined) throw new Error('no such phase in the fixture timeline');
  const set = mintSet(phase, { completedAtEpochMs: START + atSeconds * SECOND });
  if (set === null) throw new Error('the fixture phase does not complete a set');
  return set;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown) => {
      const path = new URL(urlOf(input), 'http://localhost').pathname;
      if (path === '/api/library') return Promise.resolve(json(LIBRARY));
      if (path === '/api/vocabulary') return Promise.resolve(json(makeVocabulary()));
      if (path === '/api/plans/active')
        return Promise.resolve(json({ plan: makePlan([session()]) }));
      // #82, and BEFORE the PUT answer below, whose prefix would otherwise swallow it.
      if (path === '/api/sessions/completion')
        return Promise.resolve(json({ as_of: TODAY, sessions: [] }));
      if (path.startsWith('/api/sessions/'))
        return Promise.resolve(json({ client_uuid: 'x', sets: [] }));
      return Promise.reject(new Error(`unexpected request: ${path}`));
    }),
  );
}

/** See `sessionPlayer.test.tsx`: `findBy*` cannot be used with these fake frames. */
async function settle(): Promise<void> {
  await act(async () => {
    for (let step = 0; step < 3; step += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1));
      vi.advanceTimersByTime(20);
    }
  });
}

async function until(ready: () => boolean, tries = 200): Promise<void> {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (ready()) return;
    await settle();
  }
  throw new Error('the screen never reached the expected state');
}

function renderSession() {
  const auth = createAuth();
  auth.session.set('user-token', 'user');
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/session'] }), {
    auth,
    queryClient,
  });
  render(
    <AuthProvider auth={auth}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthProvider>,
  );
}

beforeEach(() => {
  clock = START;
  sentinels = [];
  window.localStorage.clear();
  setRun(null);
  setKeepScreenOn(false);
  vibrate = vi.fn(() => true);
  Object.defineProperty(navigator, 'vibrate', { value: vibrate, configurable: true });
  Object.defineProperty(navigator, 'wakeLock', {
    configurable: true,
    value: {
      request: () => {
        const sentinel = new FakeWakeLockSentinel();
        sentinels.push(sentinel);
        return Promise.resolve(sentinel);
      },
    },
  });
  vi.spyOn(Date, 'now').mockImplementation(() => clock);
  vi.spyOn(performance, 'now').mockImplementation(() => clock);
  vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame'] });
  stubFetch();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setKeepScreenOn(false);
  setRun(null);
});

it('resumes on the phase the wall clock says, with ONE cue and a banner', async () => {
  // Hidden five seconds in, back at seventy-six: boundaries at 15, 25, 45, 55 and 75 all
  // elapsed unseen, so the run is five phases on and owes four cues it will never play.
  persistRun({ hiddenAtEpochMs: START + 5 * SECOND });
  clock = START + 76 * SECOND;

  renderSession();
  await until(() => screen.queryByRole('status') !== null);

  const banner = screen.getByRole('status');
  expect(banner).toHaveTextContent('You were away for 1:11');
  expect(banner).toHaveTextContent('set 3 of 3');
  // ⚠️ ONE. Five boundaries were crossed by a single tick; a cue per boundary is four beeps at
  // once for phases that ended minutes ago.
  expect(vibrate).toHaveBeenCalledTimes(1);
  // The run really did move — this is not a banner over a stalled timer.
  expect(getRun()?.cursor.phaseIndex).toBe(5);
  expect(getRun()?.pending.map((set) => set.set_index)).toEqual([1, 2]);
});

it('drops ONLY the sets logged after the tab went hidden when the phase is restarted', async () => {
  // Set 1 landed at 25 s, while the climber was watching. The tab went hidden at 30 s; set 2 is
  // minted by the clock at 55 s, with nobody in front of the screen.
  const seeded = persistRun({ hiddenAtEpochMs: START + 30 * SECOND });
  setRun({
    ...seeded,
    cursor: { phaseIndex: 2, phaseStartedAtEpochMs: START + 25 * SECOND },
    pending: [loggedSet(seeded, 1, 25)],
  });
  clock = START + 76 * SECOND;

  renderSession();
  await until(() => screen.queryByRole('status') !== null);
  expect(getRun()?.pending.map((set) => set.set_index)).toEqual([1, 2]);

  fireEvent.click(screen.getByRole('button', { name: 'Restart this phase' }));
  await settle();

  // Set 2 was invented by the clock after the tab went away; set 1 was real and survives.
  expect(getRun()?.pending.map((set) => set.set_index)).toEqual([1]);
  expect(screen.queryByRole('status')).toBeNull();
  // The phase restarted where the climber is now, not where the clock had got to.
  expect(getRun()?.cursor.phaseStartedAtEpochMs).toBe(clock);
});

const ON = 'Keep the screen on';
const OFF = 'Let the screen turn off';

it('renders the toggle from the SENTINEL, not from the boolean the climber clicked', async () => {
  persistRun({});
  clock = START + 5 * SECOND;

  renderSession();
  await until(() => screen.queryByRole('button', { name: ON }) !== null);
  expect(screen.getByText('Screen: turning off as usual')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: ON }));
  await settle();
  expect(sentinels).toHaveLength(1);
  // The label says what the NEXT press does, and the state is announced separately.
  expect(screen.getByRole('button', { name: OFF })).toBeInTheDocument();
  expect(screen.getByText('Screen: staying on')).toBeInTheDocument();

  // ⚠️ What the OS does every time the tab is backgrounded. The climber's preference has not
  // changed — and the control must still stop claiming the screen is being held.
  await act(async () => {
    sentinels[0]?.osRelease();
    await Promise.resolve();
  });

  expect(getKeepScreenOn()).toBe(true);
  expect(screen.getByRole('button', { name: ON })).toBeInTheDocument();
});

it('⚠️ REGRESSION: one press still does something after the OS drops the lock', async () => {
  persistRun({});
  clock = START + 5 * SECOND;

  renderSession();
  await until(() => screen.queryByRole('button', { name: ON }) !== null);
  fireEvent.click(screen.getByRole('button', { name: ON }));
  await settle();
  await act(async () => {
    sentinels[0]?.osRelease();
    await Promise.resolve();
  });

  // The preference is still `true` and `held` is `false`, which is the state the OS leaves
  // behind on every backgrounding. Pressing used to set the preference to a value it already
  // had — a no-op — so the control sat there looking broken until it was pressed twice.
  expect(getKeepScreenOn()).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: ON }));
  await settle();

  expect(sentinels).toHaveLength(2);
  expect(screen.getByRole('button', { name: OFF })).toBeInTheDocument();
});

it('⚠️ REGRESSION: a release during an in-flight acquire does not leave a lock nobody wants', async () => {
  persistRun({});
  clock = START + 5 * SECOND;

  // The real API is a round trip to the browser process; this one resolves when the test says.
  let settleRequest = (): void => undefined;
  Object.defineProperty(navigator, 'wakeLock', {
    configurable: true,
    value: {
      request: () =>
        new Promise<FakeWakeLockSentinel>((resolve) => {
          settleRequest = () => {
            const sentinel = new FakeWakeLockSentinel();
            sentinels.push(sentinel);
            resolve(sentinel);
          };
        }),
    },
  });

  renderSession();
  await until(() => screen.queryByRole('button', { name: ON }) !== null);

  fireEvent.click(screen.getByRole('button', { name: ON }));
  // …and the climber changes their mind before the browser has answered.
  act(() => {
    setKeepScreenOn(false);
  });
  await settle();
  expect(getKeepScreenOn()).toBe(false);

  await act(async () => {
    settleRequest();
    await Promise.resolve();
    await Promise.resolve();
  });

  // Published, this sentinel would have made `held` true over a preference of `false` — and
  // nothing would ever have released it, because the effect only re-runs when `wanted` moves.
  expect(sentinels[0]?.released).toBe(true);
  expect(screen.getByRole('button', { name: ON })).toBeInTheDocument();
  expect(screen.getByText('Screen: turning off as usual')).toBeInTheDocument();
});
