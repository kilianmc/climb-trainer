import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { Profile, Vocabulary } from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { completionPercent, stepCompletion } from './profile/completion';
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
 * ⚠️ **Issue #54 changed where the last step LANDS, not what it waits for.** A resolved
 * final write no longer navigates: it replaces the wizard with `OnboardingComplete`. So the
 * unmount-before-settle shape is gone, and what is left to guard is the half that always
 * mattered — a REJECTED final write must leave the form on screen, the step uncredited and
 * the celebration unreached. `finish()` awaits `mutateAsync` and only then sets `finished`;
 * remove the await and the first test below fails.
 *
 * It is asserted through the real router, the real query client and the real API client,
 * because the bug lived in the seam between them: any harness that stubbed the mutation
 * would have reproduced the intended behaviour rather than the shipped one.
 */
const TARGET_GRADE_ID = 11;
const CURRENT_GRADE_ID = 10;
const ELBOW_ID = 8;
const FINGERS_ID = 1;
const CORE_ID = 2;

const VOCABULARY: Vocabulary = {
  grade_systems: [{ id: 1, key: 'font', name: 'Fontainebleau', discipline: 'boulder' }],
  grades: [
    { id: CURRENT_GRADE_ID, grade_system_id: 1, label: '6A', ordinal: 1010 },
    { id: TARGET_GRADE_ID, grade_system_id: 1, label: '6B', ordinal: 1012 },
  ],
  climbing_aspects: [
    { id: FINGERS_ID, key: 'finger_strength', name: 'Finger strength', description: 'Force.' },
    { id: CORE_ID, key: 'core', name: 'Core tension', description: 'Tension.' },
  ],
  // Still in the vocabulary payload and read by nobody in this flow: issue #54 removed the
  // equipment STEP, and PR #10 decides what an owned-vs-lacked flag means.
  equipment: [{ id: 5, key: 'hangboard', name: 'Hangboard', description: 'Edges.' }],
  injury_areas: [{ id: ELBOW_ID, key: 'elbow', name: 'Elbow', description: 'Tendons.' }],
  // Irrelevant to this fixture; the phase copy is covered by tests/test_phase_guide.py.
  plan_goal: '',
  phase_guide: [],
  enums: {
    disciplines: ['boulder', 'sport'],
    activity_kinds: ['climbing'],
    ascent_styles: ['redpoint'],
    protocol_kinds: ['max_hang'],
    phases: ['base'],
    session_statuses: ['planned'],
  },
};

/**
 * Three of the four steps answered, the injuries step not: `20 + 80 × 3/4` = **80%**.
 *
 * ⚠️ The percentages changed with issue #54 and the arithmetic is the whole reason they are
 * written out: four steps and a 20% floor give 20/40/60/80/100, where five steps and a 29%
 * floor gave 29/43/57/71/86. `equipment_ids` and `equipment_reviewed_at` are gone from
 * `ProfileResponse` altogether, and the aspect step is now three real columns rather than a
 * row count.
 */
const THREE_OF_FOUR: Profile = {
  email: 'a@example.com',
  display_name: null,
  target_grade_id: TARGET_GRADE_ID,
  current_grade_id: CURRENT_GRADE_ID,
  primary_discipline: 'boulder',
  sessions_per_week: 3,
  available_weekdays: 0b0010101,
  strength_aspect_id: FINGERS_ID,
  weakness_aspect_id: CORE_ID,
  show_body_metrics: true,
  injuries_reviewed_at: null,
  aspect_ratings: [{ climbing_aspect_id: FINGERS_ID, score: 5, rated_at: '2026-08-21T00:00:00Z' }],
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

/**
 * What the bar must read for a given profile, from the same function the screen uses.
 *
 * ⚠️ **Derived, not a literal, and that is deliberate.** What these tests assert is that the
 * bar converges on the profile the SERVER committed and never on a step nobody persisted —
 * a relation between two fixtures, not a particular pair of digits. Pinning the digits made
 * every test in this file fail on a change to `ENDOWED_FLOOR_PERCENT` that has nothing to do
 * with any of them, while still passing if the cache had installed the wrong profile and both
 * numbers had moved together. `profile/completion.test.ts` is what pins the arithmetic.
 *
 * The non-vacuity guard is that the two profiles a test compares must disagree — asserted at
 * the top of each test that uses more than one.
 */
const percentFor = (profile: Profile) => String(completionPercent(stepCompletion(profile)));

/** Every PATCH body, in the order they were sent. */
function patchBodies(): unknown[] {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([, init]) => init?.method === 'PATCH')
    .map(([, init]) => {
      const body = init?.body;
      if (typeof body !== 'string') throw new Error(`a patch carried no JSON body: ${typeof body}`);
      return JSON.parse(body) as unknown;
    });
}

/** The one PATCH body, or a failure that names what happened instead of stringifying it. */
function patchRequestBody(): unknown {
  const [first] = patchBodies();
  if (first === undefined) throw new Error('no PATCH was made to /api/profile');
  return first;
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
        return Promise.resolve(json(THREE_OF_FOUR));
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

  // It resumes on the first unanswered step — the fourth — rather than at step 1.
  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute(
    'aria-valuenow',
    percentFor(THREE_OF_FOUR),
  );

  // Ticking an area is also what un-ticks the default "nothing is hurting" answer, which is
  // what makes the note field appear at all.
  fireEvent.click(screen.getByLabelText('Elbow'));
  fireEvent.change(screen.getByLabelText(/^Elbow —/), {
    target: { value: 'still sore on crimps' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save and finish' }));

  expect(await screen.findByRole('alert')).toHaveTextContent(/could not be saved/);

  // The things the first draft got wrong, in one place. The last one replaced the
  // navigation assertion when issue #54 replaced the navigation: "we told you it saved" is
  // now the completion screen, and a rejected write must not reach it.
  expect(screen.getByRole('progressbar')).toHaveAttribute(
    'aria-valuenow',
    percentFor(THREE_OF_FOUR),
  );
  expect(screen.getByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/onboarding');
  expect(screen.queryByRole('link', { name: 'Go to your dashboard' })).not.toBeInTheDocument();

  // And the note the user typed is still in the field, so retrying costs no retyping.
  expect(screen.getByLabelText(/^Elbow —/)).toHaveValue('still sore on crimps');
});

it('sends exactly the injuries step and celebrates only after the server accepts it', async () => {
  // ⚠️ This does NOT guard the entry-snapshot redirect. Reverting that check to read the
  // live profile leaves every test in this file green — measured — because the `finished`
  // gate above it returns the completion screen first, and nothing renders the intermediate
  // state. The ordering is prevented structurally (`onboarding.lazy.tsx` decides from a
  // `useState` snapshot taken on entry) and is deliberately recorded here as UNGUARDED
  // rather than left with a comment claiming a guarantee these assertions do not provide.
  vi.mocked(fetch).mockImplementation((input: unknown, init?: RequestInit) => {
    const url = urlOf(input);
    if (url.endsWith('/api/vocabulary')) return Promise.resolve(json(VOCABULARY));
    if (url.endsWith('/api/profile') && (init?.method ?? 'GET') === 'GET') {
      return Promise.resolve(json(THREE_OF_FOUR));
    }
    return Promise.resolve(
      json({ ...THREE_OF_FOUR, injuries_reviewed_at: '2026-08-21T10:00:00Z' }),
    );
  });

  const { router } = renderOnboarding();
  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Save and finish' }));

  // Waited on the RENDERED destination, not on a flag: `vi.waitFor` passes on a transient
  // value. The celebration replaces the wizard in place — so the assertion that it did NOT
  // navigate is as load-bearing as the one that it arrived.
  expect(
    await screen.findByRole('heading', { name: 'Ready to start your training' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Go to your dashboard' })).toHaveAttribute(
    'href',
    '/dashboard',
  );
  // …and it is still there once every queued microtask and cache write has drained, which
  // is what makes the assertion non-transient rather than merely lucky.
  await settle();
  expect(screen.getByRole('heading', { name: 'Ready to start your training' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/onboarding');
  // The wizard is gone, not hidden behind the celebration.
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();

  // `toEqual` pins the key SET: `ProfilePatchRequest` is `extra="forbid"`, so one extra
  // key is a 422 for the whole step. "No injuries" is a real answer and sends an empty
  // list, which is what stamps `injuries_reviewed_at` server-side.
  expect(patchRequestBody()).toEqual({ injuries: [] });
  expect(patchBodies()).toHaveLength(1);
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
 * ⚠️ **The two steps that reach it changed with issue #54, the shape did not.** It used to be
 * the equipment step followed by the aspects step, neither of which needed any input. The
 * equipment step is gone and the aspect step now demands three answers, so the two clicks
 * come from a profile that is HALF-answered on availability: `sessions_per_week` is stored and
 * `available_weekdays` is not (a legal partial `PATCH` result — the column is nullable
 * precisely so "unanswered" is expressible). The step is therefore submittable as it stands —
 * the frequency is chosen and "any day" is the offered default — while `completion.ts`
 * correctly refuses to credit it, and the step after it is answered already. Two Continues in
 * one tick is an ordinary thing for that user to do.
 *
 * The fix is not a snapshot, and not an invalidation either (round 4 tried that and moved the
 * bug — see `profile/api.ts`). The cache holds server responses ONLY; the optimism is an
 * overlay derived from the pending mutation, so a failure leaves nothing behind to undo. The
 * handlers live in `useMutation` rather than in the per-call options, so observer removal
 * cannot swallow them.
 */
const HALF_AVAILABILITY: Profile = { ...THREE_OF_FOUR, available_weekdays: null };

/** Target grade + aspects, and neither availability nor injuries: 2 of the 4 steps. */
const TRUTH_PERCENT = percentFor(HALF_AVAILABILITY);

/** Availability answered as well: 3 of 4. What a successful availability write commits. */
const AVAILABILITY_SAVED: Profile = { ...HALF_AVAILABILITY, available_weekdays: 0b111_1111 };
const SAVED_PERCENT = percentFor(AVAILABILITY_SAVED);

/**
 * ⚠️ **The non-vacuity guard for every derived percentage below.** The tests that follow all
 * say "the bar reads the committed truth and not the guess"; if those two readings were the
 * same string, each of them would pass no matter which profile the cache held.
 */
it('distinguishes the committed truth from the optimistic guess', () => {
  expect(TRUTH_PERCENT).not.toBe(SAVED_PERCENT);
  expect(percentFor(THREE_OF_FOUR)).not.toBe(TRUTH_PERCENT);
});

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
  const gets = options.getResponses ?? [() => json(options.profile ?? HALF_AVAILABILITY)];
  vi.mocked(fetch).mockImplementation((input: unknown, init?: RequestInit) => {
    const url = urlOf(input);
    if (url.endsWith('/api/vocabulary')) return Promise.resolve(json(VOCABULARY));
    if (url.endsWith('/api/profile') && (init?.method ?? 'GET') === 'GET') {
      const responder = gets[Math.min(getCount, gets.length - 1)];
      getCount += 1;
      const respond = () => responder?.() ?? json(options.profile ?? HALF_AVAILABILITY);
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
const savedHalf = () => json(HALF_AVAILABILITY);
const savedAvailability = () => json(AVAILABILITY_SAVED);
const savedThree = () => json(THREE_OF_FOUR);

it('does not credit a step when a CONCURRENT earlier write has failed', async () => {
  stubProfile([failed, failed]);
  renderOnboarding();

  // Resumes on the availability step, and both it and the next one are submittable as they
  // stand — so two clicks in one tick is an ordinary thing for a user to do.
  expect(await screen.findByRole('heading', { name: 'Availability' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', TRUTH_PERCENT);

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

  expect(await screen.findByRole('alert')).toBeInTheDocument();
  await settle();

  // The bar must converge on what the database holds. Rolling back to the second
  // mutation's snapshot left it one step high — crediting an `available_weekdays` that no
  // request ever persisted, for ten minutes, on a screen whose own alert said the answer
  // had not been counted. (Measured on the five-step flow as 71% against a truth of 57%.)
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', TRUTH_PERCENT);
  // And BOTH failures are reported, naming their own steps.
  expect(screen.getByRole('alert')).toHaveTextContent(/availability/i);
  expect(screen.getByRole('alert')).toHaveTextContent(/where you are now/i);
});

it('still reports an earlier failure after a later step SUCCEEDS', async () => {
  stubProfile([failed, savedHalf]);
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'Availability' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

  await settle();

  // The superseded mutation notified nobody, so this produced NO message at all and the
  // step was silently lost. A later success must not erase a different step's failure.
  expect(await screen.findByRole('alert')).toHaveTextContent(/availability/i);
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
  stubProfile([failed], { profile: THREE_OF_FOUR });
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('Elbow'));
  fireEvent.change(screen.getByLabelText(/^Elbow —/), {
    target: { value: 'still sore on crimps' },
  });

  fireEvent.click(screen.getByRole('button', { name: 'Save and finish' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not be saved/);
  await settle();

  // Everything the user needs in order to try again must still be here.
  expect(screen.getByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toBeInTheDocument();
  expect(screen.getByLabelText(/^Elbow —/)).toHaveValue('still sore on crimps');
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save and finish' })).toBeEnabled();
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
  stubProfile([savedThree], { profile: THREE_OF_FOUR, getResponses: [savedThree, shell] });
  const { queryClient } = renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('Elbow'));
  fireEvent.change(screen.getByLabelText(/^Elbow —/), {
    target: { value: 'still sore on crimps' },
  });

  await act(async () => {
    await queryClient.invalidateQueries({ queryKey: ['profile'] });
  });

  await settle();
  // `isRefetchError`, not `isLoadingError` — the data is still there, so the screen is too,
  // and so is the draft that lives inside it.
  expect(screen.getByRole('heading', { name: 'Injuries' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toBeInTheDocument();
  expect(screen.getByLabelText(/^Elbow —/)).toHaveValue('still sore on crimps');
});

/**
 * ⚠️ **The cache must converge on the newest COMMITTED state, never on an older read.**
 *
 * Round 4 issued the invalidation refetch from the failing mutation's `onError`, then the
 * scope gate released and the next mutation ran. That GET was in flight before the other
 * write committed, so it resolved second and overwrote the newer `onSuccess`. Measured with
 * a 30 ms GET on the five-step flow: the bar read **71 at +5 ms and 57 once the GET
 * landed**, then stayed 57 for the full ten-minute `staleTime` — a write that really did
 * persist reading as unanswered, with the dashboard nagging for it.
 *
 * The SUCCESSFUL response therefore has to carry REAL progress, or the test is vacuous:
 * round 4's own concurrent test returned an unchanged profile from its successful PATCH and
 * could not see this at all. So here the availability write is the one that succeeds (60 →
 * 80) and the aspect write is the one that fails; a stale read would drag the bar back to 60
 * and leave it there.
 *
 * ⚠️ **Renamed, because the failure mode it was named for is now structurally unreachable**:
 * no read is issued on the error path, so there is no stale read to overwrite anything. What
 * it still proves is the invariant — the bar settles on the newest COMMITTED state and stays
 * there — which is worth an assertion in its own right. Note it also survives deleting
 * `mutationKey`, so it is not a guard on the overlay; that is the last test in this file.
 */
it('installs the newest committed profile and keeps it', async () => {
  // Availability succeeds and carries real progress, the aspect write that follows it fails.
  stubProfile([savedAvailability, failed], { getDelayMs: 30 });
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'Availability' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

  await vi.waitFor(() =>
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', SAVED_PERCENT),
  );

  // Over TIME, not once: the clobbering read landed ~30 ms later and undid it.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 80));
  });
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', SAVED_PERCENT);
  // The failure is still reported, against its own step.
  expect(screen.getByRole('alert')).toHaveTextContent(/where you are now/i);
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
 * the overlay is the thing on screen. Note the flush: `mutation.js` dispatches
 * `type: "pending",` synchronously, but `useMutationState` delivers through
 * `notifyManager.schedule` -> `systemSetTimeoutZero`, so the render lands on the next tick,
 * not in the click handler.
 */
it('moves the bar from the PENDING write, before any response has arrived', async () => {
  stubProfile([savedAvailability], { patchDelayMs: 200 });
  renderOnboarding();

  expect(await screen.findByRole('heading', { name: 'Availability' })).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', TRUTH_PERCENT);

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await settle();

  // 200 ms of PATCH still to run: nothing has answered, and the bar has already moved.
  expect(patchBodies()).toEqual([{ sessions_per_week: 3, available_weekdays: 0b111_1111 }]);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', SAVED_PERCENT);

  // And when the response does land it replaces the guess with the same number, so there is
  // no visible step backwards: `mutation.js` awaits `onSuccess` BEFORE dispatching `success`.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 260));
  });
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', SAVED_PERCENT);
});
