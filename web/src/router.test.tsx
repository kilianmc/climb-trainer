import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserHistory, createMemoryHistory } from '@tanstack/react-router';
import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, createAuth, type Auth } from './auth/AuthProvider';
import { ApiError, NotJsonError } from './api/client';
import { SessionUnavailableError } from './auth/refresh';
import { createAppRouter, createQueryClient } from './router';

/**
 * Memory history is what makes these nearly free: no jsdom URL plumbing, and it is the
 * same history the federated mount runs on.
 *
 * These also guard a build-level invariant: vitest.config.ts REPLACES vite.config.ts,
 * so the router plugin is not running here. If `src/routeTree.gen.ts` ever stops being
 * committed, this file is what fails.
 */
function renderWith(auth: Auth, path: string, browser = false) {
  const queryClient = createQueryClient();
  const router = createAppRouter(
    browser ? createBrowserHistory() : createMemoryHistory({ initialEntries: [path] }),
    { auth, queryClient },
  );
  render(
    <AuthProvider auth={auth}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthProvider>,
  );
  return router;
}

/** Signed in, so the guarded leaves and the authenticated nav are reachable. */
function signedIn(): Auth {
  const auth = createAuth();
  auth.session.set('live-token', 'user');
  return auth;
}

beforeEach(() => {
  // Nothing in the tree fetches on mount any more (the dashboard's /api/health probe went
  // with PR #6), but an unstubbed fetch would still turn any regression into a network error
  // rather than a readable assertion failure.
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => vi.unstubAllGlobals());

describe('createAppRouter', () => {
  it('renders the public landing page at /', async () => {
    renderWith(createAuth(), '/');
    expect(await screen.findByRole('heading', { name: 'climb-trainer' })).toBeInTheDocument();
  });

  it('navigates to a lazy leaf, loading its chunk on demand', async () => {
    const router = renderWith(signedIn(), '/dashboard');
    await screen.findByRole('heading', { name: 'Dashboard' });

    await router.navigate({ to: '/plan' });

    expect(await screen.findByRole('heading', { name: 'Plan' })).toBeInTheDocument();
    // The shell survives the hop — the nav is outside the outlet.
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });

  /**
   * The standalone mount serves its own origin, so its hrefs stay relative. The federated
   * mount rewrites them to absolute standalone URLs (`remote.guard.test.tsx`); that must
   * never leak into this entry, which is the one `main.tsx` uses. Issue #16.
   *
   * Asserted on the authenticated nav: it is the longer of the two and the one that carries
   * the in-app destinations, so it is where an absolute href would do the damage.
   */
  it('keeps hrefs relative on the standalone (browser-history) mount', async () => {
    window.history.replaceState({}, '', '/dashboard');
    renderWith(signedIn(), '/dashboard', true);

    const nav = await screen.findByRole('navigation', { name: 'Main' });
    const hrefs = within(nav)
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'));

    expect(hrefs).toEqual(['/dashboard', '/plan', '/session', '/diary', '/profile']);
  });

  /**
   * Asserted on `/login`, not `/`: the landing page deliberately renders no nav (its hero carries
   * the same two destinations), so `/` cannot host this guard any more. The nav itself is
   * unchanged — every other anonymous route shows the same three links — so what is being
   * asserted is identical.
   */
  it('keeps the anonymous nav relative too', async () => {
    window.history.replaceState({}, '', '/login');
    renderWith(createAuth(), '/login', true);

    const nav = await screen.findByRole('navigation', { name: 'Main' });
    const hrefs = within(nav)
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'));

    expect(hrefs).toEqual(['/', '/login', '/register']);
  });

  it('lands an unmatched path on the catch-all rather than a blank outlet', async () => {
    renderWith(createAuth(), '/no-such-page');
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument();
  });
});

/**
 * Every retry here is another Neon wake-up, and one error class is far more expensive than the
 * rest: a `SessionUnavailableError` already represents a refresh attempt, so retrying it multiplies
 * refresh POSTs and Postgres writes on top of the cap `auth/refresh.ts` keeps. It is not an
 * `ApiError`, so it fell through to the generic "retry twice" arm until issue #28 named it — the
 * auth layer owns the refresh retry policy and Query must not add a second one.
 */
describe('the query retry predicate', () => {
  const retry = createQueryClient().getDefaultOptions().queries?.retry;

  function retries(error: Error): boolean {
    return typeof retry === 'function' ? retry(0, error) === true : true;
  }

  it.each([
    ['a session that could not be checked', new SessionUnavailableError('unanswered'), false],
    ['a rewrite serving the SPA shell', new NotJsonError(200, 'text/html'), false],
    ['a 4xx', new ApiError('nope', 404), false],
    ['a 5xx, which a second try can survive', new ApiError('upstream', 503), true],
  ])('%s -> %s', (_label, error, expected) => {
    expect(retries(error)).toBe(expected);
  });
});
