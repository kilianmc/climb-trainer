import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { ExerciseLibrary, LoggedSetInput, SessionLogRequest } from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';
import { makeBlock, makePlan, makeSession, makeSet, makeVocabulary } from './session/fixtures';
import { getRun, setRun } from './session/runStore';
import { localIsoDate } from './session/today';

/**
 * **The session player's write path, through the real router, the real query client and the
 * real API client.** Everything here is a compute-budget or data-loss rule made executable; the
 * timing machine itself is covered by `session/useSessionRun.test.ts`.
 *
 * 1. **Start sends exactly ONE PUT, and `duration_minutes` is 1.** The server merges duration
 *    with `GREATEST` into a *stored generated* `srpe_load`, so sending `estimated_minutes` would
 *    pin the session at 90 minutes permanently — and issue #12's editor cannot repair it.
 * 2. **Running through several sets sends ZERO further requests.** Neon bills awake time, so a
 *    45–90 minute session must not hold it up; the persisted run is authoritative until a
 *    trigger fires. This is the "add a debounce so we don't lose data" change, refused.
 * 3. **Finish sends every set once**, no gaps and no duplicate `set_index` — a duplicate inside
 *    one payload is a 422 that rejects the whole flush.
 * 4. **A 500 offers Retry, a 422 quarantines** and the next flush omits the refused sets.
 *    Retrying a 422 can only ever fail again.
 * 5. **Demo scope writes nothing at all** (issue #65), while the player still runs in full.
 * 6. **The session is a LIST OF ITEMS.** Start starts no timer; an item is run on its own
 *    controls. 7. **FOCUS MODE, which reaches the CONTROL BAR too**: while an item runs the
 *    others are absent, the settings are in the top corners, and no session action is reachable.
 * 8. **The summary stays closed across a remount, and going back from it sends nothing.**
 */
const TODAY = localIsoDate(new Date());
/** 09:00 local, today: `occurred_on` is the LOCAL date, so a UTC instant would drift the run
 *  onto another day for half the world and take the summary off the screen with it. */
const START = new Date(`${TODAY}T09:00:00`).getTime();
const SECOND = 1000;

/** A second block, for the focus-mode test only: every other test wants ONE item, so that the
 *  set ordinals it asserts belong to the block it is watching. */
let blockCount = 1;
/** `session_block.id` per block, DISTINCT: `done_block_ids` joins on it, so the fixture's
 *  shared default would mark every part done off one. */
const BLOCK_IDS = [101, 102, 103] as const;
/** Which of those blocks the SERVER already holds every set of. Empty for every test but the
 *  two about a restart, which is the only place the completion read matters here. */
let doneBlockIds: readonly number[] = [];

/** One UNTIMED item instead — a circuit ends when the climber falls off, so its effort compiles
 *  to an `open` phase, which is the only phase "Didn't finish it" exists for. */
let openItem = false;

/** Three 10-second hangs, 20 seconds apart, behind the 15-second lead-in: 85 seconds total. */
function plan() {
  if (openItem) {
    return makePlan([
      makeSession(
        [
          makeBlock({
            id: BLOCK_IDS[0],
            protocol_kind: 'circuit',
            sets: [makeSet({ id: 500, set_index: 1 })],
          }),
        ],
        TODAY,
      ),
    ]);
  }
  const blocks = [
    makeBlock({
      id: BLOCK_IDS[0],
      protocol_kind: 'max_hang',
      exercise_id: 11,
      rest_between_sets_seconds: 20,
      sets: [1, 2, 3].map((index) =>
        makeSet({ id: 500 + index, set_index: index, target_work_seconds: 10 }),
      ),
    }),
  ];
  if (blockCount > 1) {
    blocks.push(
      makeBlock({
        id: BLOCK_IDS[1],
        order_index: 1,
        exercise_key: 'front_lever',
        exercise_id: 12,
        sets: [makeSet({ id: 600, set_index: 1, target_work_seconds: 10 })],
      }),
    );
  }
  if (blockCount > 2) {
    blocks.push(
      makeBlock({
        id: BLOCK_IDS[2],
        order_index: 2,
        exercise_key: 'lock_offs',
        exercise_id: 13,
        sets: [makeSet({ id: 700, set_index: 1, target_work_seconds: 10 })],
      }),
    );
  }
  return makePlan([makeSession(blocks, TODAY)]);
}

const LIBRARY: ExerciseLibrary = { exercises: [] };

let clock = START;

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

/** The PUT answers, in order; the last one is reused once the list runs out. */
type PutAnswer = (body: SessionLogRequest, uuid: string) => Response;

/** The honest default: the server echoes an ack per set it accepted. */
const acked: PutAnswer = (body, uuid) =>
  json({
    client_uuid: uuid,
    sets: body.sets.map((set: LoggedSetInput, index: number) => ({
      client_uuid: set.client_uuid,
      id: index + 1,
      set_index: set.set_index,
    })),
  });

function stubFetch(answers: PutAnswer[] = []) {
  let call = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown, init?: RequestInit) => {
      const path = new URL(urlOf(input), 'http://localhost').pathname;
      const method = init?.method ?? 'GET';
      if (path === '/api/library') return Promise.resolve(json(LIBRARY));
      if (path === '/api/vocabulary') return Promise.resolve(json(makeVocabulary()));
      if (path === '/api/plans/active') return Promise.resolve(json({ plan: plan() }));
      // #82: the brief's week strip and pending list read this, and a restart seeds its items
      // from `done_block_ids`. Empty unless a test set one — one session, on today.
      if (path === '/api/sessions/completion')
        return Promise.resolve(json({ as_of: TODAY, sessions: completionRows() }));
      if (path.startsWith('/api/sessions/') && method === 'PUT') {
        const uuid = path.slice('/api/sessions/'.length);
        const body = JSON.parse(bodyText(init)) as SessionLogRequest;
        const answer = answers[call] ?? answers.at(-1) ?? acked;
        call += 1;
        return Promise.resolve(answer(body, uuid));
      }
      return Promise.reject(new Error(`unexpected request: ${method} ${path}`));
    }),
  );
}

/** ⚠️ `percent` stays UNDER 100 whatever is pre-done: at 100% the offer closes and there is no
 *  Start button left to press (`week.ts::sessionClosed`). */
function completionRows() {
  if (doneBlockIds.length === 0) return [];
  return [
    {
      block_count: blockCount,
      blocks_done: doneBlockIds.length,
      done_block_ids: doneBlockIds,
      percent: Math.round((doneBlockIds.length * 100) / blockCount),
      planned_session_id: 5001,
      scheduled_on: TODAY,
      state: 'pending',
      status: 'planned',
    },
  ];
}

/** A request body as the client actually serialised it. */
function bodyText(init: RequestInit | undefined): string {
  return typeof init?.body === 'string' ? init.body : '{}';
}

/** Every `PUT /api/sessions/*` body, in order. */
function puts(): SessionLogRequest[] {
  return vi
    .mocked(fetch)
    .mock.calls.filter(
      ([input, init]) =>
        (init?.method ?? 'GET') === 'PUT' &&
        new URL(urlOf(input), 'http://localhost').pathname.startsWith('/api/sessions/'),
    )
    .map(([, init]) => JSON.parse(bodyText(init)) as SessionLogRequest);
}

/** ⚠️ ONLY `requestAnimationFrame` is faked: faking `setTimeout` too deadlocks the first mount,
 *  because React's scheduler resumes on a `MessageChannel` no fake clock ever yields to. */
async function settle(): Promise<void> {
  await act(async () => {
    for (let step = 0; step < 3; step += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1));
      vi.advanceTimersByTime(20);
    }
  });
}

/** ⚠️ `findBy*` cannot be used: Testing Library looks for a global `jest` to detect fake timers,
 *  which vitest does not define, so its `waitFor` would poll on the frame clock we froze. */
async function until(ready: () => boolean, tries = 200): Promise<void> {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (ready()) return;
    await settle();
  }
  throw new Error('the screen never reached the expected state');
}

/** Move the wall clock, then let the rAF loop see it. `tick()` is timestamp-derived, so this is
 * the same code path a real 60 Hz frame takes. */
async function at(seconds: number): Promise<void> {
  clock = START + seconds * SECOND;
  await settle();
}

function renderSession(scope: 'user' | 'demo' = 'user') {
  const auth = createAuth();
  auth.session.set(`${scope}-token`, scope);
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/session'] }), {
    auth,
    queryClient,
  });
  // Returned so a test can UNMOUNT it: navigating away from `/session` is what tore the
  // route's own state down, and that is the state bug 1 lived in.
  return render(
    <AuthProvider auth={auth}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthProvider>,
  );
}

/** The session started — and NO timer with it. `until` + `getBy`, never `findBy` — see `until`. */
async function startedSession(scope: 'user' | 'demo' = 'user') {
  const view = renderSession(scope);
  await until(() => screen.queryByRole('button', { name: 'Start session' }) !== null);
  fireEvent.click(screen.getByRole('button', { name: 'Start session' }));
  await settle();
  return view;
}

/** ⚠️ Started only ONCE the completion read has landed: the brief renders before it, and a
 *  Start pressed first would seed the run from no marks at all — see `doneBlockIds`. */
async function startedSessionWithServerParts() {
  const view = renderSession();
  await until(() => document.querySelector('.ct-app__terms > li[data-done="done"]') !== null);
  fireEvent.click(screen.getByRole('button', { name: 'Start session' }));
  await settle();
  return view;
}

/** …plus the one item entered, which is what puts a clock on the screen. */
async function started(scope: 'user' | 'demo' = 'user') {
  const view = await startedSession(scope);
  fireEvent.click(screen.getByRole('button', { name: `Start ${ITEM}` }));
  await settle();
  return view;
}

/** `exerciseLabel` falls back to a humanised key, and the fixture library is empty. */
const ITEM = 'Max hangs';
const OTHER = 'Front lever';
/** Third item, for the completion-percentage test: two of three parts is the 67% case. */
const THIRD = 'Lock offs';

beforeEach(() => {
  clock = START;
  blockCount = 1;
  doneBlockIds = [];
  openItem = false;
  window.localStorage.clear();
  setRun(null);
  vi.spyOn(Date, 'now').mockImplementation(() => clock);
  vi.spyOn(performance, 'now').mockImplementation(() => clock);
  vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame'] });
  stubFetch();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setRun(null);
});

it('sends ONE PUT on Start, with duration_minutes 1 and no sets', async () => {
  await started();

  const bodies = puts();
  expect(bodies).toHaveLength(1);
  const [start] = bodies;
  // ⚠️ The floor, never `estimated_minutes` (90 on this fixture). `srpe_load` is a stored
  // generated column merged with GREATEST, so the wrong value here is permanent.
  expect(start?.duration_minutes).toBe(1);
  // …and it is not the plan's own estimate, which is 90 on this fixture and would be permanent.
  expect(start?.duration_minutes).not.toBe(90);
  expect(start?.sets).toEqual([]);
  expect(start?.finished).toBe(false);
  expect(start?.occurred_on).toBe(TODAY);
  // Without it the server's `planned_session_status` comes back null on every response.
  expect(start?.planned_session_id).toBe(5001);
});

it('sends ZERO further requests while the climber works through several sets', async () => {
  await started();
  expect(puts()).toHaveLength(1);

  // 15 lead-in + work/rest/work/rest/work: the whole 85-second timeline.
  await at(90);

  // The rule, made executable: three sets were minted and NOTHING went to the server. A
  // debounce or an item-count trigger here would hold Neon awake for the whole session.
  expect(getRun()?.pending.map((set) => set.set_index)).toEqual([1, 2, 3]);
  expect(puts()).toHaveLength(1);
});

it('sends every set exactly once on Finish, with no gaps and no duplicates', async () => {
  await started();
  await at(90);

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  const bodies = puts();
  expect(bodies).toHaveLength(2);
  const sets = bodies[1]?.sets ?? [];
  expect(sets.map((set) => set.set_index)).toEqual([1, 2, 3]);
  expect(new Set(sets.map((set) => set.client_uuid)).size).toBe(3);
  expect(bodies[1]?.finished).toBe(true);
  // Every request carries the whole envelope — the RPE follow-up included.
  expect(bodies[1]?.discipline).toBe('sport');
  expect(bodies[1]?.occurred_on).toBe(TODAY);
  // The summary is the end of every run, never the last set.
  expect(screen.getByRole('heading', { name: 'Session done' })).toBeInTheDocument();
  expect(screen.getByText('Saved to your diary.')).toBeInTheDocument();
});

it('offers Retry after a 500 and keeps the sets', async () => {
  stubFetch([acked, () => json({ detail: 'boom' }, 500), acked]);
  await started();
  await at(90);

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  // Requeued, not quarantined: a 5xx never reached the handler, so the sets are still owed.
  expect(screen.getByRole('alert')).toHaveTextContent(/3 sets have not reached the server/i);
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await settle();

  expect(puts()[2]?.sets.map((set) => set.set_index)).toEqual([1, 2, 3]);
  expect(screen.getByText('Saved to your diary.')).toBeInTheDocument();
});

it('QUARANTINES a 422 and omits the refused sets from the next flush', async () => {
  stubFetch([acked, () => json({ detail: 'duplicate set_index' }, 422), acked]);
  await started();
  await at(90);

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  expect(screen.getByRole('alert')).toHaveTextContent(/3 sets the server refused/i);
  expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();

  // ⚠️ THE ASSERTION: the RPE follow-up is the next flush, and the refused sets are NOT in it.
  // Every refusal on the route is a fixed string, so resending could only be refused again.
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '7' } });
  await settle();

  const bodies = puts();
  expect(bodies).toHaveLength(3);
  expect(bodies[2]?.sets).toEqual([]);
  expect(bodies[2]?.rpe).toBe(7);
  expect(bodies[2]?.finished).toBe(true);
});

it('writes NOTHING in demo scope, and the player still runs the whole session', async () => {
  await started('demo');
  await at(90);

  fireEvent.click(screen.getByRole('button', { name: 'End session' }));
  await settle();

  // Issue #65 by absence, not by a greyed-out control: no request, no disabled button.
  expect(puts()).toEqual([]);
  expect(screen.queryAllByRole('button').filter((b) => b.hasAttribute('disabled'))).toEqual([]);
  expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
  expect(screen.getByRole('heading', { name: 'Session done' })).toBeInTheDocument();
  expect(screen.getByText(/Nothing was written down/i)).toBeInTheDocument();
  // The run really ran: three sets were settled locally so the summary can show them.
  expect(screen.getByText(/3 sets in/i)).toBeInTheDocument();
});

it('starts NO timer when the session starts — the item does that', async () => {
  renderSession();
  await until(() => screen.queryByRole('button', { name: 'Start session' }) !== null);
  // ⚠️ The brief renders NO wake-lock control at all: there is no session to keep a screen on
  // for, and the one that used to sit here rendered a preference rather than a held lock.
  expect(screen.queryByRole('button', { name: /screen/i })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Start session' }));
  await settle();
  await at(90);

  // The whole timeline would have elapsed by now if Start had begun counting.
  expect(getRun()?.pending).toEqual([]);
  expect(getRun()?.activeBlockIndex).toBeNull();
  expect(screen.getByRole('button', { name: `Start ${ITEM}` })).toBeInTheDocument();
  // The elapsed session clock still ran: that is what `duration_minutes` is made of.
  expect(puts()).toHaveLength(1);
});

it('LOGS an item completed by hand, with no measured values invented', async () => {
  await startedSession();
  // The forgot-to-press-start affordance, and it says so: on an item that is NOT running the
  // tick means "I did this one myself", not "stop it there".
  fireEvent.click(screen.getByRole('button', { name: `I did ${ITEM} myself` }));
  await at(90);

  expect(getRun()?.items[0]?.status).toBe('completed');
  // ⚠️ It has to log SOMETHING. Completion is a derived query over `logged_set`, so an item that
  // logged nothing scores zero and the percentage would contradict what the climber just said.
  expect(getRun()?.pending.map((set) => set.set_index)).toEqual([1, 2, 3]);

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  const sets = puts()[1]?.sets ?? [];
  expect(sets.map((set) => set.prescribed_set_id)).toEqual([501, 502, 503]);
  // Fresh uuids, and NOT ONE measured number: it records that the set was done, nothing more.
  expect(new Set(sets.map((set) => set.client_uuid)).size).toBe(3);
  for (const set of sets) {
    expect(set.actual_reps).toBeNull();
    expect(set.actual_work_seconds).toBeNull();
    expect(set.rpe).toBeNull();
    expect(set.completed_at).toEqual(expect.any(String));
  }
});

it('shows the completion percentage, and a skipped part does not count toward it', async () => {
  blockCount = 3;
  await startedSession();

  fireEvent.click(screen.getByRole('button', { name: `I did ${ITEM} myself` }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: `I did ${OTHER} myself` }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: `Mark ${THIRD} skipped` }));
  await settle();

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  // ⚠️ Kilian: "if i skipped one part, it should not be 100%." Two of three blocks logged a set,
  // which is the server's own join — so #64's plan-screen figure will agree with this one.
  expect(screen.getByText(/67% of the session/i)).toBeInTheDocument();
  expect(screen.getByText(/2 of 3 parts fully logged/i)).toBeInTheDocument();
  // The skipped item logged nothing at all, which is what keeps the number honest.
  expect(puts().flatMap((body) => body.sets.map((set) => set.prescribed_set_id))).toEqual([
    501, 502, 503, 600,
  ]);
});

it('never reuses a set ordinal across a manual completion and a restart', async () => {
  await startedSession();
  fireEvent.click(screen.getByRole('button', { name: `I did ${ITEM} myself` }));
  await settle();

  // Tab-hidden is a flush trigger, so the server now holds 1, 2 and 3 — and `logged_set` rows
  // cannot be deleted (#81), so the restart may not reuse them.
  await act(async () => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
  });
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  await settle();
  expect(getRun()?.logged.map((set) => set.set_index)).toEqual([1, 2, 3]);

  fireEvent.click(screen.getByRole('button', { name: `Restart ${ITEM}` }));
  await settle();
  await at(180);
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  const sent = puts().flatMap((body) => body.sets.map((set) => set.set_index));
  expect(sent).toEqual([1, 2, 3, 4, 5, 6]);
  expect(new Set(sent).size).toBe(6);
});

/** ⚠️ #82's last defect, in Kilian's words: "when I click on start again, it shows all 4 of them
 *  as 'not started'. That is wrong — the first 3 should be shown in green and as 'completed'." */
it('SEEDS an item the server already holds as COMPLETED, and the summary counts it', async () => {
  blockCount = 3;
  doneBlockIds = [BLOCK_IDS[0]];
  await startedSessionWithServerParts();

  const rows = [...document.querySelectorAll<HTMLElement>('.ct-app__item')];
  // The tone is `data-state`'s, and the WORD is the same `STATE_LABEL` a live completion reads.
  expect(rows.map((row) => row.getAttribute('data-state'))).toEqual([
    'completed',
    'pending',
    'pending',
  ]);
  expect(within(rows[0] as HTMLElement).getByText('Completed')).toBeInTheDocument();
  // Nothing was fabricated to make that state: the sets are on the server under an earlier run.
  expect(getRun()?.logged).toEqual([]);
  expect(getRun()?.pending).toEqual([]);

  fireEvent.click(screen.getByRole('button', { name: `I did ${THIRD} myself` }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  // ⚠️ The WHOLE session, not this attempt: one part logged here plus the one already held.
  expect(screen.getByText(/67% of the session/i)).toBeInTheDocument();
  expect(screen.getByText(/2 of 3 parts fully logged/i)).toBeInTheDocument();
  expect(puts().flatMap((body) => body.sets.map((set) => set.prescribed_set_id))).toEqual([700]);
});

/** A pre-done part stays RE-ENTERABLE — redoing one is fine (Kilian) — and behaves exactly as a
 *  restart does: `runs` is still 0 on it, so the offset has to come off the CEILING alone. */
it('RE-ENTERS a pre-done item, minting an ordinal no set in the run holds', async () => {
  blockCount = 3;
  doneBlockIds = [BLOCK_IDS[0]];
  await startedSessionWithServerParts();

  // An ordinal is minted BEFORE the redo, so a first entry that walked the block's own 1..N
  // would collide with it — the bug `setIndexOffset` exists for.
  fireEvent.click(screen.getByRole('button', { name: `I did ${THIRD} myself` }));
  await settle();
  // ⚠️ …and that ordinal, 1, sits inside the FIRST block's own natural range, which is exactly
  // the set an ordinal window deleted on this press. `prescribed_set_id` is what says whose.
  fireEvent.click(screen.getByRole('button', { name: `Restart ${ITEM}` }));
  await settle();
  expect(getRun()?.items[0]?.status).toBe('running');
  // Past all three of its hangs, which is what puts the session-level Finish back on screen.
  await at(90);
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  const sent = puts().flatMap((body) => body.sets.map((set) => set.set_index));
  expect(sent).toEqual([1, 2, 3, 4]);
  expect(new Set(sent).size).toBe(4);
  // Two parts of three: the one re-run (which the server already held) and the one done by
  // hand. The redo re-sent nothing the server has.
  expect(screen.getByText(/2 of 3 parts fully logged/i)).toBeInTheDocument();
});

it('⚠️ takes the whole session card away once every item is done, and says to rest', async () => {
  renderSession();
  await until(() => screen.queryByRole('button', { name: 'Start session' }) !== null);
  const card = () => document.querySelector('.ct-app__card');
  expect(card()).not.toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Start session' }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: `Start ${ITEM}` }));
  await settle();
  // Past the whole block: the clock logs all three sets, which is what makes the item DONE.
  await at(90);
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: 'Done' }));
  await settle();

  // Kilian, #82: a session done in full "does not appear in past / current / next session and
  // does not let you restart". The note in its place says what to do instead.
  expect(card()).toBeNull();
  expect(screen.queryByRole('button', { name: 'Start session' })).toBeNull();
  expect(screen.getByText(/already finished this session/i)).toBeInTheDocument();
});

/** The one session card on screen. `document.querySelector` because the card is a section, not
 *  a role, and the finished one is deliberately unreachable by any accessible name. */
function sessionCard(): HTMLElement {
  const card = document.querySelector<HTMLElement>('.ct-app__card');
  if (card === null) throw new Error('no session card on screen');
  return card;
}

/** The completion figure wherever it is on screen. The summary and the finished card word it
 *  identically, which is what makes "the same run reads the same number" assertable. */
function percent(): string | undefined {
  // ⚠️ The innermost element, not `document.body.textContent`: concatenated siblings put the
  // digits of "wk 1–4" straight onto the figure and the scan read 67% as 467%.
  const line = screen.queryAllByText(/% of the session/).at(-1)?.textContent ?? '';
  return /(\d+)% of the session/.exec(line)?.[1];
}

/** Two of three parts done by hand, the third skipped, Finish, then Done. Returns the figure the
 *  SUMMARY showed, read before Done dismisses it. */
async function finishedSession(): Promise<string | undefined> {
  blockCount = 3;
  await startedSession();
  for (const name of [`I did ${ITEM} myself`, `I did ${OTHER} myself`, `Mark ${THIRD} skipped`]) {
    fireEvent.click(screen.getByRole('button', { name }));
    await settle();
  }
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();
  const summary = percent();
  fireEvent.click(screen.getByRole('button', { name: 'Done' }));
  await settle();
  return summary;
}

it('shows the completion percentage on the FINISHED CARD, matching the summary', async () => {
  const summary = await finishedSession();

  // ⚠️ Kilian: "i am still missing the % when the user has clicked done". It rendered on the
  // summary alone — the one screen the climber has just dismissed to get here.
  expect(summary).toBe('67');
  expect(screen.queryByRole('heading', { name: 'Session done' })).toBeNull();
  expect(percent()).toBe(summary);
  expect(sessionCard()).toHaveTextContent(/2 of 3 parts fully logged/);
  // ⚠️ …and 67% is NOT finished (#82): the card is still on screen, still startable. Only 100%
  // takes it away, so a card can never look done over two thirds nobody did.
  expect(screen.getByRole('button', { name: 'Start it again' })).toBeInTheDocument();
});

it('lists every item with its final state on the finished card, and offers it again', async () => {
  await finishedSession();

  const rows = [...sessionCard().querySelectorAll('.ct-app__item')];
  expect(rows.map((row) => row.getAttribute('data-state'))).toEqual([
    'completed',
    'completed',
    'skipped',
  ]);
  // ⚠️ Kilian: "so i can see at a glance what i missed (push ups)". The skipped row is told apart
  // by its WORD as well as by its tone, because colour is never the only channel.
  expect(rows[0]).toHaveTextContent(new RegExp(`${ITEM}.*Completed`, 's'));
  expect(rows[2]).toHaveTextContent(new RegExp(`${THIRD}.*Skipped`, 's'));
  expect(rows[2]?.getAttribute('data-state')).not.toBe(rows[0]?.getAttribute('data-state'));

  // Read-only INSIDE the card: the rows are a record of the run, not controls on it, and the
  // run itself is over. Whether the SESSION is over is a different question — see below.
  expect(within(sessionCard()).queryAllByRole('button')).toEqual([]);
  for (const name of ['Start session', `Start ${THIRD}`, `Restart ${ITEM}`, 'Finish']) {
    expect(screen.queryByRole('button', { name })).toBeNull();
  }
  // ⚠️ The one control that IS there: at 67% the session is still owed, so it can be run again.
  expect(screen.getByRole('button', { name: 'Start it again' })).toBeInTheDocument();
});

it('marks an item skipped, and a skipped item logs no sets at all', async () => {
  await startedSession();
  fireEvent.click(screen.getByRole('button', { name: `Mark ${ITEM} skipped` }));
  await settle();

  expect(getRun()?.items[0]?.status).toBe('skipped');
  expect(getRun()?.pending).toEqual([]);
  expect(getRun()?.activeBlockIndex).toBeNull();
});

it('RESTARTS a completed item under fresh set_index values, appending to the acked ones', async () => {
  await started();
  await at(90);
  expect(getRun()?.items[0]?.status).toBe('completed');

  // Tab-hidden is a flush trigger, so the server now holds set_index 1, 2 and 3 — and
  // `logged_set` rows cannot be deleted (#81), so the re-run may not reuse them.
  await act(async () => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
  });
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  await settle();
  expect(getRun()?.logged.map((set) => set.set_index)).toEqual([1, 2, 3]);

  fireEvent.click(screen.getByRole('button', { name: `Restart ${ITEM}` }));
  await settle();
  await at(180);

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  const sent = puts().flatMap((body) => body.sets.map((set) => set.set_index));
  expect(sent).toEqual([1, 2, 3, 4, 5, 6]);
  expect(new Set(sent).size).toBe(6);
});

it('cannot be started again once it is finished', async () => {
  await started();
  await at(90);
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: 'Done' }));
  await settle();

  // Absent, not disabled: a greyed-out Start invites the press it is refusing.
  expect(screen.queryByRole('button', { name: 'Start session' })).toBeNull();
  expect(screen.getByText(/already finished this session/i)).toBeInTheDocument();
});

it('FOCUS MODE: the other items are ABSENT while one is running', async () => {
  blockCount = 2;
  await startedSession();

  // Nothing running, so the session is the list of things it is.
  expect(screen.getByRole('button', { name: `Start ${ITEM}` })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: `Start ${OTHER}` })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: `Start ${ITEM}` }));
  await settle();

  // ⚠️ Absent, not dimmed and not collapsed: a climber mid-hang has one decision to make, and
  // five other blocks under the countdown are five wrong buttons within reach.
  expect(screen.queryByRole('button', { name: `Start ${OTHER}` })).toBeNull();
  expect(screen.queryByText(OTHER)).toBeNull();
  expect(document.querySelector('.ct-app__items')).toBeNull();

  // The running item keeps its own controls, icon-only and never disabled.
  expect(screen.getByRole('button', { name: `Pause ${ITEM}` })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: `Restart ${ITEM}` })).toBeInTheDocument();

  // …and the list comes back the moment nothing is running, which is the only moment another
  // item can be entered.
  fireEvent.click(screen.getByRole('button', { name: `Mark ${ITEM} skipped` }));
  await settle();
  expect(screen.getByRole('button', { name: `Start ${OTHER}` })).toBeInTheDocument();
});

it('carries each item state in `data-state`, alongside the word and never instead of it', async () => {
  blockCount = 2;
  await startedSession();

  const states = () =>
    [...document.querySelectorAll('.ct-app__item')].map((row) => row.getAttribute('data-state'));

  expect(states()).toEqual(['pending', 'pending']);

  fireEvent.click(screen.getByRole('button', { name: `I did ${ITEM} myself` }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: `Mark ${OTHER} skipped` }));
  await settle();

  // The attribute is what `_session.scss` colours off — green for one, red for the other —
  // rather than an interpolated modifier class, which is `markupCss.test.ts`'s blind spot.
  expect(states()).toEqual(['completed', 'skipped']);

  // ⚠️ COLOUR IS NEVER THE ONLY CHANNEL. The word stays and `aria-pressed` still says which
  // control is current, so the row reads the same to a screen reader and in monochrome.
  expect(screen.getByText('Completed')).toBeInTheDocument();
  expect(screen.getByText('Skipped')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: `I did ${ITEM} myself` })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(screen.getByRole('button', { name: `Mark ${OTHER} skipped` })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  // …and the two that are not the current state say so, rather than being absent.
  expect(screen.getByRole('button', { name: `Mark ${ITEM} skipped` })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
});

it('puts the two settings in the TOP CORNERS, and there is no Test sound button left', async () => {
  renderSession();
  await until(() => screen.queryByRole('button', { name: 'Start session' }) !== null);
  // It used to sit on the brief beside Start. The mute toggle plays a cue on the way ON, which
  // is the same proof in the state where it matters.
  expect(screen.queryByRole('button', { name: 'Test sound' })).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Start session' }));
  await settle();

  const top = document.querySelector('.ct-app__player-top');
  const bar = document.querySelector('.ct-app__player-bar');
  const corners = [...(top?.querySelectorAll('.ct-app__player-corner') ?? [])];
  const wake = screen.getByRole('button', { name: 'Keep the screen on' });
  const sound = screen.getByRole('button', { name: 'Mute the cues' });

  // ⚠️ Kilian's note: "Keep screen on" next to Finish is wrong. It is a setting, not a step.
  expect(bar?.contains(wake)).toBe(false);
  expect(corners).toHaveLength(2);
  expect(corners[0]?.contains(sound)).toBe(true);
  expect(corners[1]?.contains(wake)).toBe(true);
  // Finish stays where a thumb reaches it.
  expect(bar?.contains(screen.getByRole('button', { name: 'Finish' }))).toBe(true);
});

it('pauses and resumes the running item from its own control', async () => {
  await started();
  await at(20);

  fireEvent.click(screen.getByRole('button', { name: `Pause ${ITEM}` }));
  await settle();
  expect(getRun()?.pausedAtEpochMs).toBe(START + 20 * SECOND);
  expect(screen.getByText('Paused')).toBeInTheDocument();

  // Three minutes of wall clock, which would have run the whole timeline out.
  await at(200);
  expect(getRun()?.pending).toEqual([]);
  expect(getRun()?.cursor.phaseIndex).toBe(1);

  fireEvent.click(screen.getByRole('button', { name: `Resume ${ITEM}` }));
  await settle();
  expect(getRun()?.pausedAtEpochMs).toBeNull();
  // Five seconds were left when it was paused, and five seconds are left now.
  await at(204);
  expect(getRun()?.cursor.phaseIndex).toBe(1);
  await at(206);
  expect(getRun()?.pending.map((set) => set.set_index)).toEqual([1]);
});

it('does NOT ask for the session RPE again after the screen is left and come back to', async () => {
  const view = await started();
  await at(90);
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '7' } });
  await settle();
  fireEvent.click(screen.getByRole('button', { name: 'Done' }));
  await settle();
  expect(screen.queryByRole('combobox')).toBeNull();

  // ⚠️ Kilian's repro: navigating to `/plan` unmounts this route, and the acknowledgement was
  // a `useState` flag — so the summary came back asking for an RPE already answered and sent.
  view.unmount();
  renderSession();
  // Either screen settles the reads; which one arrived is the assertion below, not the wait.
  await until(
    () =>
      screen.queryByText(/already finished this session/i) !== null ||
      screen.queryByRole('heading', { name: 'Session done' }) !== null,
  );

  expect(screen.queryByRole('heading', { name: 'Session done' })).toBeNull();
  expect(screen.queryByRole('combobox')).toBeNull();
  // It survived because it is on the RECORD, next to the RPE it was answered beside.
  expect(getRun()?.sessionRpe).toBe(7);
  expect(getRun()?.summaryClosedAtEpochMs).not.toBeNull();
});

it('GOES BACK from the finish screen, sending nothing, and re-finishing does not double-log', async () => {
  await started();
  await at(90);
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();
  expect(puts()).toHaveLength(2);

  fireEvent.click(screen.getByRole('button', { name: 'Go back to the session' }));
  await settle();

  // ⚠️ NOTHING was sent. `finished: false` cannot un-finish a session — `planned_session.status`
  // never moves backwards — so the response would be byte-identical to not asking.
  expect(puts()).toHaveLength(2);
  expect(getRun()?.finishedAtEpochMs).toBeNull();
  // …and the session is workable again: the item list is back, with its controls.
  expect(screen.queryByRole('heading', { name: 'Session done' })).toBeNull();
  expect(screen.getByRole('button', { name: `Restart ${ITEM}` })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: `Restart ${ITEM}` }));
  await settle();
  await at(180);
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  await settle();

  // `sets` is a delta of what is still pending, so the first three go once and the second
  // attempt appends under fresh ordinals. Nothing is sent twice.
  const sent = puts().flatMap((body) => body.sets.map((set) => set.set_index));
  expect(sent).toEqual([1, 2, 3, 4, 5, 6]);
  expect(new Set(sent).size).toBe(6);
  expect(puts().at(-1)?.finished).toBe(true);
});

it('keeps SESSION-LEVEL actions out of a running item and puts them back on the item list', async () => {
  await startedSession();
  expect(screen.getByRole('button', { name: 'Finish' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: `Start ${ITEM}` }));
  await settle();

  // ⚠️ Kilian, with the timer running: "i saw at the bottom of the page 2 buttons, 1 of them was
  // to finish the whole session, that should not be there."
  expect(screen.queryByRole('button', { name: 'Finish' })).toBeNull();
  expect(document.querySelector('.ct-app__player-bar')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: `Mark ${ITEM} skipped` }));
  await settle();
  expect(screen.getByRole('button', { name: 'Finish' })).toBeInTheDocument();
});

it('offers “Didn’t finish it” on the RUNNING ITEM’s own controls, not in the session bar', async () => {
  openItem = true;
  await started();
  // Past the lead-in and into the untimed effort, which is the only phase this control exists on.
  await at(20);

  const bail = screen.getByRole('button', { name: `Didn’t finish ${ITEM}` });
  expect(document.querySelector('.ct-app__player-controls')?.contains(bail)).toBe(true);
  expect(document.querySelector('.ct-app__player-bar')).toBeNull();

  fireEvent.click(bail);
  await settle();

  // It advanced and minted nothing: that is the difference between it and "next set", which
  // logs the sets it crosses.
  expect(getRun()?.pending).toEqual([]);
  expect(getRun()?.logged).toEqual([]);
  expect(getRun()?.activeBlockIndex).toBeNull();
});
