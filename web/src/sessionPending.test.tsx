import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { ExerciseLibrary, PlanSession, SessionLogRequest } from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';
import { makeBlock, makePlan, makeSession, makeSet, makeVocabulary } from './session/fixtures';
import { getRun, setRun } from './session/runStore';

/* A session owed from earlier this week (#82), and the two things here that can lose data: the
   run must be dated TODAY against the PAST session's id, and an offer closes only at 100%. */
const WEDNESDAY = new Date(2026, 8, 2, 9, 0);
const MONDAY_ISO = '2026-08-31';
const TODAY_ISO = '2026-09-02';
const LIBRARY: ExerciseLibrary = { exercises: [] };

/** `exerciseLabel` falls back to a humanised key, and the fixture library is empty. */
const PARTS = ['Max hangs', 'Front lever', 'Lock offs'] as const;
const KEYS = ['max_hangs', 'front_lever', 'lock_offs'];

/** `session_block.id`, distinct per block. */
const blockId = (sessionId: number, index: number) => sessionId * 100 + index + 1;

/** `blocks` one-set blocks, each with a prescribed-set id, so a part done is a clean 1/blocks —
 *  without those ids nothing joins back and every run would read 0%. */
function session(id: number, scheduledOn: string, weekday: number, blocks = 1): PlanSession {
  return {
    ...makeSession(
      Array.from({ length: blocks }, (_, index) => ({
        ...makeBlock({
          order_index: index,
          exercise_key: KEYS[index] ?? 'max_hangs',
          exercise_id: 11 + index,
          sets: [makeSet({ id: 501 + index * 100, target_work_seconds: 10 })],
        }),
        // ⚠️ `session_block.id`, and DISTINCT per block: it is the key `done_block_ids` joins
        // on, and the fixture's shared default would mark every part off one logged block.
        id: blockId(id, index),
      })),
      scheduledOn,
    ),
    id,
    title: `Session ${String(id)}`,
    weekday,
  };
}

/** THREE parts each, so "finished at a third" is expressible: a one-block session is 0 or 100. */
const MONDAY = session(1, MONDAY_ISO, 0, 3);
const TODAY = session(3, TODAY_ISO, 2, 3);
/** Thursday and Friday, for the ONE test about which session is offered NEXT. Empty everywhere
 *  else: a plan with days ahead of it puts a second card on every screen below. */
const THURSDAY = session(4, '2026-09-03', 3, 3);
const FRIDAY = session(5, '2026-09-04', 4, 3);
let ahead: PlanSession[] = [];

/** Monday came to 66%: a real result, under 100, so it is still owed. */
const MONDAY_ROW = {
  block_count: 3,
  blocks_done: 2,
  done_block_ids: [],
  percent: 66,
  planned_session_id: 1,
  scheduled_on: MONDAY_ISO,
  state: 'completed',
  status: 'completed',
};

/** TODAY's row, as the server hands it back after a reload: `done` of its three blocks logged,
 *  and `state` whatever the Finish button left behind — which must decide nothing. */
function todayRow(done: number, state = 'pending') {
  return {
    block_count: 3,
    blocks_done: done,
    done_block_ids: Array.from({ length: done }, (_, index) => blockId(3, index)),
    percent: Math.round((done * 100) / 3),
    planned_session_id: 3,
    scheduled_on: TODAY_ISO,
    state,
    status: state === 'pending' ? 'planned' : 'completed',
  };
}

/** The completion response this render will serve. Reset per test. */
let completionRows: unknown[] = [MONDAY_ROW];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

/** 500 on every PUT: a 5xx requeues rather than quarantines, so the sets stay unsent. */
let putFails = false;

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown, init?: RequestInit) => {
      const path = new URL(urlOf(input), 'http://localhost').pathname;
      if (path === '/api/library') return Promise.resolve(json(LIBRARY));
      if (path === '/api/vocabulary') return Promise.resolve(json(makeVocabulary()));
      if (path === '/api/plans/active')
        return Promise.resolve(json({ plan: makePlan([MONDAY, TODAY, ...ahead]) }));
      if (path === '/api/sessions/completion')
        return Promise.resolve(json({ as_of: TODAY_ISO, sessions: completionRows }));
      if (path.startsWith('/api/sessions/')) {
        if (putFails) return Promise.resolve(json({ detail: 'nope' }, 500));
        // ⚠️ The ack per set, not an empty list: a set leaves `pending` on its ACK and on
        // nothing else, so an unacked flush leaves the offer holding unsent sets.
        const body = JSON.parse(
          typeof init?.body === 'string' ? init.body : '{}',
        ) as SessionLogRequest;
        return Promise.resolve(
          json({
            client_uuid: 'x',
            planned_session_id: 1,
            sets: body.sets.map((set, index) => ({
              client_uuid: set.client_uuid,
              id: index + 1,
              set_index: set.set_index,
            })),
          }),
        );
      }
      return Promise.reject(new Error(`unexpected request: ${path}`));
    }),
  );
}

/** Every `PUT /api/sessions/*` body, in order. */
function puts(): SessionLogRequest[] {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([, init]) => (init?.method ?? 'GET') === 'PUT')
    .map(
      ([, init]) =>
        JSON.parse(typeof init?.body === 'string' ? init.body : '{}') as SessionLogRequest,
    );
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
  putFails = false;
  ahead = [];
  completionRows = [MONDAY_ROW];
  window.localStorage.clear();
  // `runStore` caches the record in module scope, so clearing storage alone leaves a run from
  // the previous test standing — and a standing run shows the PLAYER instead of the brief.
  setRun(null);
  vi.setSystemTime(WEDNESDAY);
  stubFetch();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('offers Monday’s unfinished session with its band and its WORD, above today’s', async () => {
  renderSession();

  expect(await screen.findByText('Pending from previous days')).toBeTruthy();
  // Twice on the screen: the card's badge, and the week strip's own clipped label.
  const badge = screen.getAllByText('66% done').find((node) => node.closest('.ct-app__card'));
  expect(badge).toBeTruthy();
  expect(badge?.getAttribute('data-completion')).toBe('partial');
  // The card wears the band too, and it is the card's OWN attribute that decides its edge.
  expect(badge?.closest('.ct-app__card')?.getAttribute('data-completion')).toBe('partial');
  expect(screen.getByRole('button', { name: 'Start it now' })).toBeTruthy();
});

/** ⚠️ `occurred_on` is the diary's day and `activity.srpe_load` is generated from it, so a
 *  backdated run files today's training under a day the climber did nothing. */
it('⚠️ starts it dated TODAY, against the PAST session’s id', async () => {
  renderSession();

  fireEvent.click(await screen.findByRole('button', { name: 'Start it now' }));
  await waitFor(() => {
    expect(puts()).toHaveLength(1);
  });

  const [start] = puts();
  expect(start?.occurred_on).toBe(TODAY_ISO);
  expect(start?.planned_session_id).toBe(1);
  expect(start?.duration_minutes).toBe(1);
});

it('tints Monday in the week strip and marks today, both in words', async () => {
  renderSession();

  // The strip is on screen before the completion read lands, so wait for the figures.
  await screen.findByText('Pending from previous days');
  const strip = screen.getByRole('table', { name: 'This week' });
  expect(strip.querySelector('[data-completion="partial"] .ct-app__weekmark')?.textContent).toBe(
    '66% done66%',
  );
  // One day marked, and the mark is a WORD as well as a fill — the "Today" heading below is a
  // different element, which is why this is scoped to the strip.
  expect(strip.querySelectorAll('[data-today]')).toHaveLength(1);
  expect(strip.querySelector('[data-today] .ct-app__weekdate')?.textContent).toBe('Today');
});

/** Run Monday's owed session, marking `parts` of its three items done by hand — no timer, which
 *  is the "I did this away from the phone" path — then Finish and dismiss the summary. */
async function ranMonday(parts: readonly string[]): Promise<void> {
  await screen.findByText('Pending from previous days');
  fireEvent.click(screen.getByRole('button', { name: 'Start it now' }));
  for (const part of parts) {
    fireEvent.click(await screen.findByRole('button', { name: `I did ${part} myself` }));
  }
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Done' }));
}

/** Monday's card. `document.querySelector` because a card is a section, not a role, and the
 *  pending one is the first on the screen — the week strip above it is a table. */
function mondayCard(): HTMLElement {
  const card = document.querySelector<HTMLElement>('.ct-app__card');
  if (card === null) throw new Error('no session card on screen');
  return card;
}

it('⚠️ still OFFERS a session finished at a third, and does not paint it finished', async () => {
  renderSession();
  await ranMonday(['Max hangs']);

  // Kilian: "if i open a pending session, and click on Finish, it is still unfinished but i
  // cannot click again to completed."
  expect(await screen.findByRole('button', { name: 'Start it again' })).toBeTruthy();
  expect(mondayCard()).not.toHaveAttribute('data-state');
  expect(screen.queryByText(/already finished this session/i)).toBeNull();
  // The word beside the tint says the same thing, because colour is never the only channel.
  expect(screen.getByText(/still unlogged, so it is not done yet/i)).toBeTruthy();
  // ⚠️ And the badge is the RUN's figure, not the 66% the completion read still holds: a card
  // that contradicts the summary just closed is the same defect in another channel.
  expect(mondayCard().querySelector('.ct-app__completion')?.textContent).toBe('33% done');
  expect(mondayCard()).toHaveTextContent(/1 of 3 parts fully logged/);
});

/** ⚠️ Kilian, #82: a session with every item done "does not appear in past / current / next
 *  session and does not let you restart" — so the whole section goes, card and all. */
it('takes a session done in FULL off the offer sections entirely, card included', async () => {
  renderSession();
  await ranMonday(PARTS);

  await waitFor(() => {
    expect(screen.queryByText('Pending from previous days')).toBeNull();
  });
  expect(screen.queryByRole('button', { name: 'Start it again' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Start it now' })).toBeNull();
  // Today's is the only card left, and Monday's heading is gone with its card.
  expect(document.querySelectorAll('.ct-app__card')).toHaveLength(1);
  expect(screen.queryByRole('heading', { name: /Session 1/ })).toBeNull();
});

/** ⚠️ …and the WEEK STRIP is the exception: it is the calendar, so a finished day stays on it
 *  with its own percentage. "Does not appear" is about the three offer sections only. */
it('KEEPS the finished day in the week strip, with its figure and its word', async () => {
  renderSession();
  await ranMonday(PARTS);

  const strip = screen.getByRole('table', { name: 'This week' });
  // Seven cells, whatever any of them came to — a rest day renders `&__rest` in its own.
  expect(strip.querySelectorAll('[role="cell"]')).toHaveLength(7);
  // The server row is still the stale 66% here; what matters is that the DAY is not hidden.
  await waitFor(() => {
    expect(strip.querySelector('[data-completion] .ct-app__weekmark')?.textContent).toBe(
      '66% done66%',
    );
  });
});

it('⚠️ routes a run with UNSENT SETS to Save, never to a restart that would replace them', async () => {
  putFails = true;
  renderSession();
  await ranMonday(['Max hangs']);

  // Starting mints a run under a new key and overwrites `ct:run`, so an offered Start here is
  // one press away from losing a set the server never got.
  expect(await screen.findByRole('button', { name: 'Save it now' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Start it again' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Start it now' })).toBeNull();
  expect(screen.getByText(/Save those sets first/i)).toBeTruthy();
});

/** Today's card, found by its own heading: two cards are on screen and only one is today's. */
function todayCard(): HTMLElement {
  const card = screen
    .getByRole('heading', { name: /Session 3/ })
    .closest<HTMLElement>('.ct-app__card');
  if (card === null) throw new Error('today’s session card is not on screen');
  return card;
}

/** The parts list on a card: the mark each row carries, `null` where it carries none. */
function partMarks(card: HTMLElement): (string | null)[] {
  return [...card.querySelectorAll<HTMLElement>('.ct-app__terms > li')].map((part) =>
    part.getAttribute('data-done'),
  );
}

/** ⚠️ THE RELOAD CASE, and why `sessionReport` exists. Kilian: "we say what you logged already
 *  counts towards it but it is not true — when we reload, the whole session is unmarked". */
it('⚠️ shows which parts of TODAY’S session are logged, with no run record at all', async () => {
  completionRows = [MONDAY_ROW, todayRow(2)];
  renderSession();

  await screen.findByText('Pending from previous days');
  await waitFor(() => {
    expect(partMarks(todayCard())).toEqual(['done', 'done', null]);
  });
  // The word beside the tint, and NO word on the part nobody reached: an unreached block is
  // not a missed one, which is the whole difference between today and a day that is over.
  const parts = todayCard().querySelectorAll('.ct-app__terms > li');
  expect(parts[0]?.querySelector('.ct-app__mark')?.textContent).toBe('Done');
  expect(parts[2]?.querySelector('.ct-app__mark')).toBeNull();
  // Still startable, because two parts of three is not done — and the badge says which two.
  expect(todayCard().querySelector('.ct-app__completion')?.textContent).toBe('67% done');
  expect(screen.getByRole('button', { name: 'Start session' })).toBeTruthy();
});

/** ⚠️ #82's last defect, in Kilian's words: "when I click on start again, it shows all 4 of them
 *  as 'not started'. That is wrong — the first 3 should be shown in green and as 'completed'." */
it('⚠️ STARTS today’s session with its already-logged parts completed, word and tone alike', async () => {
  completionRows = [MONDAY_ROW, todayRow(2)];
  renderSession();

  // Waited for: the brief renders before the completion read lands, and a Start pressed first
  // would seed the run from no marks at all.
  await waitFor(() => {
    expect(partMarks(todayCard())).toEqual(['done', 'done', null]);
  });
  fireEvent.click(screen.getByRole('button', { name: 'Start session' }));

  const rows = () => [...document.querySelectorAll<HTMLElement>('.ct-app__item')];
  await waitFor(() => {
    expect(rows()).toHaveLength(3);
  });
  expect(rows().map((row) => row.getAttribute('data-state'))).toEqual([
    'completed',
    'completed',
    'pending',
  ]);
  // ⚠️ Colour is never the only channel: the row's word is the same one a live completion gets.
  expect(rows().map((row) => row.querySelector('.ct-app__item-state')?.textContent)).toEqual([
    'Completed',
    'Completed',
    'Not started',
  ]);
  // …and no set was fabricated to say so — those rows are on the server under an earlier run.
  expect(getRun()?.logged).toEqual([]);
  expect(getRun()?.pending).toEqual([]);
});

/** A pre-done part stays RE-ENTERABLE — redoing one is fine (Kilian) — and the summary describes
 *  the WHOLE session: two parts the server held plus the one logged in this attempt. */
it('re-enters a pre-done part, and the summary counts the parts it never re-logged', async () => {
  completionRows = [MONDAY_ROW, todayRow(2)];
  renderSession();

  await waitFor(() => {
    expect(partMarks(todayCard())).toEqual(['done', 'done', null]);
  });
  fireEvent.click(screen.getByRole('button', { name: 'Start session' }));
  // "Restart", not "Start": the row already reads completed, so its own control says so.
  fireEvent.click(await screen.findByRole('button', { name: `Restart ${PARTS[0]}` }));
  fireEvent.click(await screen.findByRole('button', { name: `Mark ${PARTS[0]} completed` }));
  fireEvent.click(await screen.findByRole('button', { name: `I did ${PARTS[2]} myself` }));
  fireEvent.click(await screen.findByRole('button', { name: 'Finish' }));

  // 3 of 3, not 2 of 3: the part the server held and nobody re-ran is counted all the same.
  expect(await screen.findByText(/100% of the session/i)).toBeTruthy();
  expect(screen.getByText(/3 of 3 parts fully logged/i)).toBeTruthy();
  // Only what THIS attempt did was sent, under ordinals it minted itself.
  await waitFor(() => {
    expect(puts().length).toBeGreaterThan(1);
  });
  const sets = puts().flatMap((body) => body.sets);
  expect(sets.map((set) => set.prescribed_set_id)).toEqual([501, 701]);
  expect(sets.map((set) => set.set_index)).toEqual([1, 2]);
});

it('⚠️ offers NO CARD for today at 100% of its PARTS — the rest note instead', async () => {
  completionRows = [MONDAY_ROW, todayRow(3)];
  renderSession();

  // Kilian asked for exactly this copy: it says the session is over AND what to do instead.
  await screen.findByText(/already finished this session/i);
  expect(screen.queryByRole('heading', { name: /Session 3/ })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Start session' })).toBeNull();
  // The day is still on the calendar, word and percentage alike.
  const strip = screen.getByRole('table', { name: 'This week' });
  expect(strip.querySelector('[data-completion="full"] .ct-app__weekmark')?.textContent).toBe(
    'Completed100%',
  );
});

/** ⚠️ Pulled forward and finished, so it is over: the NEXT session offered is the one after it,
 *  never a closed card standing where Friday's should be. */
it('SKIPS OVER a next session already completed and offers the one after it', async () => {
  ahead = [THURSDAY, FRIDAY];
  completionRows = [
    MONDAY_ROW,
    { ...todayRow(3), planned_session_id: 4, scheduled_on: '2026-09-03' },
  ];
  renderSession();

  await screen.findByText('Next session');
  // The section renders before the completion read lands, so Thursday leaves it on the ANSWER.
  await waitFor(() => {
    expect(screen.queryByRole('heading', { name: /Session 4/ })).toBeNull();
  });
  const next = screen.getByRole('button', { name: 'Start it anyway' }).closest('.ct-app__offer');
  expect(next?.querySelector('h2')?.textContent).toContain('Session 5');
});

/** ⚠️ Kilian's actual #82 defect, in the card's channel: the Finish button is not completion.
 *  "Finish just finishes. What says it is completed is the inside items." */
it('⚠️ leaves today’s card unbadged and untinted when Finish was pressed with nothing logged', async () => {
  completionRows = [MONDAY_ROW, todayRow(0, 'completed')];
  renderSession();

  await screen.findByText('Pending from previous days');
  // No word, no band on the card and no mark on any part: 0% on a day still in reach would
  // read as a failure the climber has not had yet.
  expect(todayCard().querySelector('.ct-app__completion')).toBeNull();
  expect(todayCard()).not.toHaveAttribute('data-completion');
  expect(todayCard()).not.toHaveAttribute('data-state');
  expect(partMarks(todayCard())).toEqual([null, null, null]);
  expect(screen.getByRole('button', { name: 'Start session' })).toBeTruthy();
});
