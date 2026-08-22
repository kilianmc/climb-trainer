import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { Profile } from './api/types';
import { AuthProvider } from './auth/AuthProvider';
import { completionPercent, stepCompletion } from './profile/completion';
import { createAppContext, createAppRouter } from './router';

/**
 * ⚠️ **One tab, two accounts: the second must not see or overwrite the first's profile.**
 *
 * Both session transitions are client-side — `logOut()` in `routes/__root.tsx` navigates with
 * the router, and `login.tsx` uses `router.history.push` — so **there is no page reload to
 * throw the query cache away**, and `PROFILE_KEY` is `['profile']` with no user identity in
 * it. Measured before the fix: user A's dashboard at 86%, log out, log in as B, and B's
 * dashboard rendered **86%** with `GET /api/profile` having been called exactly **once,
 * ever** — `staleTime` is ten minutes, so nothing refetched. The same cache entry feeds
 * `draftFrom()` in the wizard and the editor, so B's form came prefilled with A's target
 * grade, availability and self-ratings, and one Continue would have written A's answers into
 * B's row.
 *
 * Two accounts in one tab is the dev and demo path, not a contrived setup.
 *
 * The fix is `queryClient.clear()` on the credential transitions, wired next to the
 * `session.clear()` that already guards them in `auth/authClient.ts`. It cannot be hooked on
 * the session store's token going null: `auth/refresh.ts:533` clears the token before EVERY
 * refresh POST (the documented "drop the token before every `POST /api/auth/*`" rule), so a
 * store-level hook would wipe the cache on every silent token rotation.
 *
 * ⚠️ The measured numbers above are the five-step flow's. Issue #54 left four steps and a 20%
 * floor, so the percentages these fixtures produce are different — and they are **derived
 * from the fixtures below** rather than written in, because a hand-computed constant that
 * happens to agree with a broken `completionPercent` is not an assertion.
 */
const A_HAS_TWO_STEPS: Profile = {
  email: 'a@example.com',
  display_name: null,
  target_grade_id: 11,
  current_grade_id: null,
  primary_discipline: 'boulder',
  sessions_per_week: 3,
  available_weekdays: 0b0010101,
  strength_aspect_id: null,
  weakness_aspect_id: null,
  show_body_metrics: true,
  injuries_reviewed_at: null,
  aspect_ratings: [],
  injuries: [],
};

/** Nothing answered: the endowed floor. */
const B_IS_NEW: Profile = {
  email: 'b@example.com',
  display_name: null,
  target_grade_id: null,
  current_grade_id: null,
  primary_discipline: null,
  sessions_per_week: null,
  available_weekdays: null,
  strength_aspect_id: null,
  weakness_aspect_id: null,
  show_body_metrics: true,
  injuries_reviewed_at: null,
  aspect_ratings: [],
  injuries: [],
};

/**
 * What the bar must read for a given profile, from the same function the screen uses.
 *
 * ⚠️ **Not a literal, and that is the point of the helper.** The two numbers this test cares
 * about are "A's" and "B's", not "60" and "20" — pinning the digits would make the test fail
 * on a deliberate change to the floor while still passing if the cache leaked one account's
 * profile into the other and both numbers moved together. `completion.test.ts` is what pins
 * the arithmetic itself.
 */
const percentFor = (profile: Profile) => String(completionPercent(stepCompletion(profile)));

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const profileGets = () =>
  vi
    .mocked(fetch)
    .mock.calls.filter(
      ([input, init]) => urlOf(input).endsWith('/api/profile') && (init?.method ?? 'GET') === 'GET',
    ).length;

beforeEach(() => {
  let profileReads = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown, init?: RequestInit) => {
      const url = urlOf(input);
      if (url.endsWith('/api/vocabulary')) {
        return Promise.resolve(
          json({
            grade_systems: [],
            grades: [],
            climbing_aspects: [],
            equipment: [],
            injury_areas: [],
            enums: {
              disciplines: [],
              activity_kinds: [],
              ascent_styles: [],
              protocol_kinds: [],
              phases: [],
              session_statuses: [],
            },
          }),
        );
      }
      if (url.endsWith('/api/auth/logout')) return Promise.resolve(json({ status: 'ok' }));
      if (url.endsWith('/api/auth/login')) {
        return Promise.resolve(
          json({
            access_token: 'token-for-b',
            token_type: 'bearer',
            expires_in: 10_800,
            scope: 'user',
          }),
        );
      }
      if (url.endsWith('/api/profile') && (init?.method ?? 'GET') === 'GET') {
        profileReads += 1;
        return Promise.resolve(json(profileReads === 1 ? A_HAS_TWO_STEPS : B_IS_NEW));
      }
      return Promise.reject(new Error(`unexpected request: ${url}`));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it('does not show one account the previous account cached profile', async () => {
  // The two fixtures have to DISAGREE or the test cannot see a leak at all — the round-1
  // version of this file could have been written with two identical profiles and passed.
  expect(percentFor(A_HAS_TWO_STEPS)).not.toBe(percentFor(B_IS_NEW));

  // `createAppContext`, not a hand-built pair: the link between the two IS what is under
  // test, and a harness that wired it itself would prove nothing about the real entries.
  const { auth, queryClient } = createAppContext();
  auth.session.set('token-for-a', 'user');
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/dashboard'] }), {
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

  // A: the target grade and availability answered, the other two steps not.
  expect(await screen.findByRole('progressbar')).toHaveAttribute(
    'aria-valuenow',
    percentFor(A_HAS_TWO_STEPS),
  );
  expect(profileGets()).toBe(1);

  // The real credential calls, which is where the cache reset has to live.
  await act(async () => {
    await auth.client.logout();
    await auth.client.login({ email: 'b@example.com', password: 'a-long-enough-passphrase' });
    await router.navigate({ to: '/dashboard' });
  });

  // B is a new account: the endowed floor, from a read that actually happened. The count is
  // asserted as "more than before" rather than pinned: how many times a cleared cache is
  // re-read depends on how many render cycles a mounted observer gets, and the invariant is
  // that B's screen came from B's own fetch.
  expect(await screen.findByRole('progressbar')).toHaveAttribute(
    'aria-valuenow',
    percentFor(B_IS_NEW),
  );
  expect(profileGets()).toBeGreaterThan(1);
});
