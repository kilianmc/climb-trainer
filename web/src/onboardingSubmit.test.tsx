import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { Profile, Vocabulary } from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';

/**
 * **A step whose write FAILS must not be credited.** This is the regression test for the
 * worst bug in PR #9's first draft, and it is a core-user-path test under CLAUDE.md's
 * policy ("anything that saves or submits", and above all anything that can lose user
 * data).
 *
 * The bug: `advance()` fired the mutation and navigated in the same handler, so on the
 * LAST step the component unmounted before the request settled. A visitor could flag
 * "elbow — still sore on crimps", click Finish, have the PATCH fail, and land on a
 * dashboard showing **100% complete** with no injury in the database and no error anywhere
 * — and the next thing to read that profile is the plan generator, which would prescribe
 * crimp loading on an injured elbow. Every unit test of the injuries step passed.
 *
 * It is asserted through the real router, the real query client and the real API client,
 * because the bug lived in the seam between them: any harness that stubbed the mutation
 * would have reproduced the intended behaviour rather than the shipped one.
 */
const GRADE_ID = 11;
const ELBOW_ID = 8;

const VOCABULARY: Vocabulary = {
  grade_systems: [{ id: 1, key: 'font', name: 'Fontainebleau', discipline: 'boulder' }],
  grades: [{ id: GRADE_ID, grade_system_id: 1, label: '6B', ordinal: 1012 }],
  climbing_aspects: [
    { id: 1, key: 'finger_strength', name: 'Finger strength', description: 'Force.' },
  ],
  equipment: [{ id: 5, key: 'hangboard', name: 'Hangboard', description: 'Edges.' }],
  injury_areas: [{ id: ELBOW_ID, key: 'elbow', name: 'Elbow', description: 'Tendons.' }],
  enums: {
    disciplines: ['boulder', 'sport'],
    activity_kinds: ['climbing'],
    ascent_styles: ['redpoint'],
    protocol_kinds: ['max_hang'],
    phases: ['base'],
    session_statuses: ['planned'],
  },
};

/** Four steps answered, the injuries step not: 6 of 7 units, i.e. 86%. */
const FOUR_OF_FIVE: Profile = {
  target_grade_id: GRADE_ID,
  primary_discipline: 'boulder',
  sessions_per_week: 3,
  available_weekdays: 0b0010101,
  show_body_metrics: true,
  equipment_reviewed_at: '2026-08-21T09:00:00Z',
  injuries_reviewed_at: null,
  equipment_ids: [5],
  aspect_ratings: [{ climbing_aspect_id: 1, score: 3, rated_at: '2026-08-21T00:00:00Z' }],
  injuries: [],
};

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

/** The one PATCH body, or a failure that names what happened instead of stringifying it. */
function patchRequestBody(): unknown {
  const call = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PATCH');
  if (call === undefined) throw new Error('no PATCH was made to /api/profile');
  const body = call[1]?.body;
  if (typeof body !== 'string') throw new Error(`the patch carried no JSON body: ${typeof body}`);
  return JSON.parse(body);
}

/** Drain the microtask queue and React's work, inside `act` so no update is unbatched. */
async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function renderOnboarding() {
  const auth = createAuth();
  // Signed in, or `_authed`'s guard redirects to /login and the wizard never renders.
  auth.session.set('live-token', 'user');
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/onboarding'] }), {
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
  return { router, queryClient };
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown, init?: RequestInit) => {
      const url = urlOf(input);
      if (url.endsWith('/api/vocabulary')) return Promise.resolve(json(VOCABULARY));
      if (url.endsWith('/api/profile') && (init?.method ?? 'GET') === 'GET') {
        return Promise.resolve(json(FOUR_OF_FIVE));
      }
      if (url.endsWith('/api/profile')) {
        // The failure under test. 500 rather than 422 so nothing can be blamed on the
        // payload, and because a mutation does not retry a 5xx.
        return Promise.resolve(json({ detail: 'The server could not save that.' }, 500));
      }
      return Promise.reject(new Error(`unexpected request: ${url}`));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it('leaves the last step uncredited and on screen when its write fails', async () => {
  const { router } = renderOnboarding();

  // It resumes on the first unanswered step — the fifth — rather than at step 1.
  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '86');

  fireEvent.click(screen.getByLabelText('Elbow'));
  fireEvent.change(screen.getByLabelText(/^Elbow —/), {
    target: { value: 'still sore on crimps' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));

  expect(await screen.findByRole('alert')).toHaveTextContent(/could not be saved/);

  // The three things the first draft got wrong, in one place.
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '86');
  expect(screen.getByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/onboarding');

  // And the note the user typed is still in the field, so retrying costs no retyping.
  expect(screen.getByLabelText(/^Elbow —/)).toHaveValue('still sore on crimps');
});

it('sends exactly the injuries step and advances only after the server accepts it', async () => {
  // ⚠️ This does NOT guard the entry-snapshot redirect. Reverting that check to read the
  // live profile leaves every test in this file green — measured — because jsdom never
  // renders the intermediate state: the router visits only /onboarding and /dashboard. The
  // ordering is prevented structurally (`onboarding.lazy.tsx` decides from a `useState`
  // snapshot taken on entry) and is deliberately recorded here as UNGUARDED rather than
  // left with a comment claiming a guarantee these assertions do not provide.
  vi.mocked(fetch).mockImplementation((input: unknown, init?: RequestInit) => {
    const url = urlOf(input);
    if (url.endsWith('/api/vocabulary')) return Promise.resolve(json(VOCABULARY));
    if (url.endsWith('/api/profile') && (init?.method ?? 'GET') === 'GET') {
      return Promise.resolve(json(FOUR_OF_FIVE));
    }
    return Promise.resolve(json({ ...FOUR_OF_FIVE, injuries_reviewed_at: '2026-08-21T10:00:00Z' }));
  });

  const { router } = renderOnboarding();
  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));

  // Waited on the RENDERED destination, not on `location.pathname`: `vi.waitFor` passes on
  // a transient value. This is worth keeping — it is a real assertion that the finish path
  // lands on the dashboard and stays there — it just is not a test of the snapshot.
  expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
  // …and it is still there once every queued microtask and cache write has drained, which
  // is what makes the assertion non-transient rather than merely lucky.
  await settle();
  expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/dashboard');

  // `toEqual` pins the key SET: `ProfilePatchRequest` is `extra="forbid"`, so one extra
  // key is a 422 for the whole step. "No injuries" is a real answer and sends an empty
  // list, which is what stamps `injuries_reviewed_at` server-side.
  expect(patchRequestBody()).toEqual({ injuries: [] });
});

/**
 * Two steps submitted in the same tick, the first failing.
 *
 * ⚠️ **This is the case optimistic-plus-rollback does NOT handle, and the round-3 review
 * said it did.** Two facts about query-core 5.101.4 combine badly:
 *
 * - `onMutate` runs BEFORE the retryer, while the `scope` gate lives inside it — so
 *   `scope: { id: 'profile' }` serialises the network call only. The second `mutate()`
 *   snapshots `context.previous` from a cache that already carries the FIRST mutation's
 *   optimistic state, so rolling back to that snapshot restores a fabrication.
 * - `mutate()` calls `removeObserver` on the in-flight mutation, so a superseded mutation
 *   never notifies: `isError` never flips for it and a per-call `onError` never fires.
 *
 * Round 3's own change is what made this reachable in two clicks: neither the equipment
 * step nor the aspects step needs any input, so Continue is live on both immediately.
 *
 * The fix is not a snapshot, and not an invalidation either (round 4 tried that and moved the
 * bug — see `profile/api.ts`). The cache holds server responses ONLY; the optimism is an
 * overlay derived from the pending mutation, so a failure leaves nothing behind to undo. The
 * handlers live in `useMutation` rather than in the per-call options, so observer removal
 * cannot swallow them.
 */
const TWO_STEPS_DONE: Profile = {
  ...FOUR_OF_FIVE,
  equipment_ids: [],
  equipment_reviewed_at: null,
  aspect_ratings: [],
  injuries_reviewed_at: null,
};

/** 2 endowed + target grade + availability = 4 of 7. */
const TRUTH_PERCENT = '57';

/**
 * `patchResponses` and `getResponses` are consumed in order; the last entry repeats. The
 * GET list starts with the successful page load, so a later entry models the network going
 * bad AFTER the user has something on screen — which is the only shape in which a refetch
 * failure can destroy a draft.
 */
function stubProfile(
  patchResponses: (() => Response)[],
  options: {
    profile?: Profile;
    getDelayMs?: number;
    getResponses?: (() => Response)[];
    patchDelayMs?: number;
  } = {},
) {
  let patchCount = 0;
  let getCount = 0;
  const gets = options.getResponses ?? [() => json(options.profile ?? TWO_STEPS_DONE)];
  vi.mocked(fetch).mockImplementation((input: unknown, init?: RequestInit) => {
    const url = urlOf(input);
    if (url.endsWith('/api/vocabulary')) return Promise.resolve(json(VOCABULARY));
    if (url.endsWith('/api/profile') && (init?.method ?? 'GET') === 'GET') {
      const responder = gets[Math.min(getCount, gets.length - 1)];
      getCount += 1;
      const respond = () => responder?.() ?? json(options.profile ?? TWO_STEPS_DONE);
      return options.getDelayMs === undefined
        ? Promise.resolve(respond())
        : new Promise<Response>((resolve) =>
            setTimeout(() => resolve(respond()), options.getDelayMs),
          );
    }
    const responder = patchResponses[Math.min(patchCount, patchResponses.length - 1)];
    patchCount += 1;
    const respond = () => responder?.() ?? json({ detail: 'unexpected' }, 500);
    return options.patchDelayMs === undefined
      ? Promise.resolve(respond())
      : new Promise<Response>((resolve) =>
          setTimeout(() => resolve(respond()), options.patchDelayMs),
        );
  });
}

/**
 * The SPA shell, which is what a misrouted `/api/*` actually returns (CLAUDE.md deployment
 * trap 2, and the reason `apiFetch` guards the content-type). Used for the failing REFETCH
 * rather than a 500: `NotJsonError` is not retried (`router.tsx` — a rewrite
 * misconfiguration is unwinnable), so the query reaches `error` immediately instead of
 * after the 1 s + 2 s backoff a 5xx would take.
 */
const shell = () =>
  new Response('<!doctype html><title>climb</title>', {
    status: 200,
    headers: { 'content-type': 'text/html' },
  });

const failed = () => json({ detail: 'The server could not save that.' }, 500);
const saved = () => json(TWO_STEPS_DONE);
const saved4 = () => json(FOUR_OF_FIVE);

it('does not credit a step when a CONCURRENT earlier write has failed', async () => {
  stubProfile([failed, failed]);
  renderOnboarding();

  // Resumes on the equipment step, and both it and the next one are submittable as they
  // stand — so two clicks in one tick is an ordinary thing for a user to do.
  expect(await screen.findByRole('heading', { name: 'What you train on' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', TRUTH_PERCENT);

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

  expect(await screen.findByRole('alert')).toBeInTheDocument();
  await settle();

  // The bar must converge on what the database holds. Rolling back to the second
  // mutation's snapshot left it at 71% — crediting a fabricated `equipment_reviewed_at`
  // that no request ever persisted, for ten minutes, on a screen whose own alert said the
  // answer had not been counted.
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', TRUTH_PERCENT);
  // And BOTH failures are reported, naming their own steps.
  expect(screen.getByRole('alert')).toHaveTextContent(/what you train on/i);
  expect(screen.getByRole('alert')).toHaveTextContent(/self-rating/i);
});

it('still reports an earlier failure after a later step SUCCEEDS', async () => {
  stubProfile([failed, saved]);
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'What you train on' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

  await settle();

  // The superseded mutation notified nobody, so this produced NO message at all and the
  // step was silently lost. A later success must not erase a different step's failure.
  expect(await screen.findByRole('alert')).toHaveTextContent(/what you train on/i);
});

/**
 * ⚠️ **A write failure must never destroy unsaved input, and must never remove the retry.**
 *
 * ⚠️ **This test exercises the WRITE half only, and its name used to claim more.** It said
 * "and the reload" — but the error path issues no request at all now, so the failing-reload
 * entry in its stub was never consumed and the round-4 bug it described could not reproduce
 * here. Proven by mutation testing: reintroducing that bug leaves this test green. The
 * route-guard half is guarded by the next test, alone.
 */
it('keeps the wizard, the draft and the retry when a write fails', async () => {
  stubProfile([failed], { profile: FOUR_OF_FIVE });
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('Elbow'));
  fireEvent.change(screen.getByLabelText(/^Elbow —/), {
    target: { value: 'still sore on crimps' },
  });

  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not be saved/);
  await settle();

  // Everything the user needs in order to try again must still be here.
  expect(screen.getByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toBeInTheDocument();
  expect(screen.getByLabelText(/^Elbow —/)).toHaveValue('still sore on crimps');
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Finish' })).toBeEnabled();
});

/**
 * ⚠️ **The only guard on the route gate**, so read the assertions as load-bearing.
 *
 * A background refetch can fail for any reason — a ten-minute `staleTime` expiring across a
 * navigation, a rewrite serving the SPA shell, a dropped connection — and
 * `query.js`'s `case "error"` reducer sets `status: "error"` **unconditionally**, even with
 * data present ("flag existing data as invalidated if we get a background error",
 * query-core 5.101.4). Gating the route on `isError` therefore swapped the whole `Wizard`
 * for its load-error paragraph and took `draft` — `useState` INSIDE `Wizard`, including a
 * typed injury note — with it, with no way back because `refetchOnWindowFocus` is off.
 *
 * It is driven directly rather than through a write, because the write path issues no GET.
 * Mutation-tested: this is the test that fails when the guard goes back to `isError`.
 */
it('survives a background refetch failure with data already in the cache', async () => {
  stubProfile([saved], { profile: FOUR_OF_FIVE, getResponses: [saved4, shell] });
  const { queryClient } = renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  await act(async () => {
    await queryClient.invalidateQueries({ queryKey: ['profile'] });
  });

  await settle();
  // `isRefetchError`, not `isLoadingError` — the data is still there, so the screen is too.
  expect(screen.getByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toBeInTheDocument();
});

/**
 * ⚠️ **The cache must converge on the newest COMMITTED state, never on an older read.**
 *
 * Round 4 issued the invalidation refetch from the failing mutation's `onError`, then the
 * scope gate released and the next mutation ran. That GET was in flight before the second
 * write committed, so it resolved second and overwrote the newer `onSuccess`. Measured with
 * a 30 ms GET: the bar read **71 at +5 ms and 57 once the GET landed**, then stayed 57 for
 * the full ten-minute `staleTime` — a write that really did persist reading as unanswered,
 * with the dashboard nagging for it.
 *
 * The success response therefore has to carry REAL progress, or the test is vacuous: round
 * 4's own concurrent test returned an unchanged profile from its successful PATCH and could
 * not see this at all.
 *
 * ⚠️ **Renamed, because the failure mode it was named for is now structurally unreachable**:
 * no read is issued on the error path, so there is no stale read to overwrite anything. What
 * it still proves is the invariant — the bar settles on the newest COMMITTED state and stays
 * there — which is worth an assertion in its own right. Note it also survives deleting
 * `mutationKey`, so it is not a guard on the overlay; that is the last test in this file.
 */
const ASPECTS_SAVED: Profile = {
  ...TWO_STEPS_DONE,
  aspect_ratings: [{ climbing_aspect_id: 1, score: 4, rated_at: '2026-08-21T10:00:00Z' }],
};

it('installs the newest committed profile and keeps it', async () => {
  // Equipment fails, aspects succeeds. 2 endowed + target grade + availability + aspects.
  stubProfile([failed, () => json(ASPECTS_SAVED)], { getDelayMs: 30 });
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'What you train on' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

  await vi.waitFor(() =>
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '71'),
  );

  // Over TIME, not once: the clobbering read landed ~30 ms later and undid it.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 80));
  });
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '71');
  // The failure is still reported, against its own step.
  expect(screen.getByRole('alert')).toHaveTextContent(/what you train on/i);
});

/**
 * ⚠️ **The optimistic overlay itself.** Deleting one line — `mutationKey: PROFILE_PATCH_KEY`
 * in `profile/api.ts` — silently disables the whole mechanism: `matchMutation`
 * (query-core `utils.js`) returns false for a mutation that declares no key, so `pending` is
 * always `[]` and the bar stops moving until the response lands. Every other test in the
 * suite stayed green through that deletion, which is exactly the vacuity this repo keeps
 * paying for; this is the test that fails.
 *
 * It asserts the bar WHILE the PATCH is still in flight, which is the only window in which
 * the overlay is the thing on screen. Note the flush: the `pending` dispatch is synchronous
 * (`mutation.js:94`) but `useMutationState` delivers through
 * `notifyManager.schedule` -> `systemSetTimeoutZero`, so the render lands on the next tick,
 * not in the click handler.
 */
const EQUIPMENT_SAVED: Profile = {
  ...TWO_STEPS_DONE,
  equipment_reviewed_at: '2026-08-21T10:00:00Z',
};

it('moves the bar from the PENDING write, before any response has arrived', async () => {
  stubProfile([() => json(EQUIPMENT_SAVED)], { patchDelayMs: 200 });
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'What you train on' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', TRUTH_PERCENT);

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await settle();

  // 200 ms of PATCH still to run: nothing has answered, and the bar has already moved.
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '71');

  // And when the response does land it replaces the guess with the same number, so there is
  // no visible step backwards: `mutation.js` awaits `onSuccess` BEFORE dispatching `success`.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 260));
  });
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '71');
});
