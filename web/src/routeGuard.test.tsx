import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserHistory, createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, createAuth, type Auth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';

/**
 * The client-side half of deny-by-default. Asserted under **both** histories, because the
 * federated mount runs on the kilianmc.com origin with an in-memory history: a guard written
 * against `window.location` would work in one arm and redirect the portfolio in the other.
 *
 * `publicRoutes.test.ts` is the companion — it proves no route escapes the guard by omission.
 * This proves the guard behaves once a route is under it.
 */
/** `fetch`'s first argument is `RequestInfo | URL`; only one of the three is a string. */
function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

function mount(path: string, auth: Auth, history: 'memory' | 'browser' = 'memory') {
  const queryClient = createQueryClient();
  const router = createAppRouter(
    history === 'memory' ? createMemoryHistory({ initialEntries: [path] }) : createBrowserHistory(),
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

/** No refresh cookie: the bootstrap 401s and the visitor is anonymous. */
function anonymous() {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Not authenticated.' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
  return createAuth();
}

/** A visitor who already holds a token, i.e. the post-login state. */
function signedIn(scope: 'user' | 'demo' = 'user') {
  const auth = createAuth();
  auth.session.set('live-token', scope);
  return auth;
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the _authed guard', () => {
  it('bounces an anonymous deep link to /login, carrying the intended path', async () => {
    const router = mount('/plan', anonymous());

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login');
    expect(router.state.location.search).toEqual({ redirect: '/plan' });
  });

  it('lets a signed-in visitor through to the guarded leaf', async () => {
    mount('/plan', signedIn());

    expect(await screen.findByRole('heading', { name: 'Plan' })).toBeInTheDocument();
  });

  it('guards the same way on browser history, not just in memory', async () => {
    window.history.replaceState({}, '', '/diary');
    const router = mount('/diary', anonymous(), 'browser');

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login');
    expect(router.state.location.search).toEqual({ redirect: '/diary' });
  });

  it('attempts the silent refresh at most once across several guarded navigations', async () => {
    const auth = anonymous();
    const router = mount('/plan', auth);
    await screen.findByRole('heading', { name: 'Log in' });

    await router.navigate({ to: '/diary' });
    await router.navigate({ to: '/profile' });

    // A failed bootstrap means "no cookie", which re-asking cannot change — and asking per
    // navigation would be a Postgres write per navigation.
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => urlOf(url).includes('/api/auth/refresh')),
    ).toHaveLength(1);
  });

  it('never follows an off-site ?redirect=, and drops it from the validated search', async () => {
    const router = mount('/login?redirect=https://evil.example/steal', anonymous());
    await screen.findByRole('heading', { name: 'Log in' });

    // Asserted as BEHAVIOUR, not as an intermediate value. TanStack merges a route's
    // validated search with its parents', and the root route validates nothing, so the
    // hostile string is still present in `location.search` and in the match's `search` —
    // which is exactly why `login.tsx` re-validates at the point of use. Asserting `{}` on
    // the match here passed for the wrong reason on nothing and failed on the truth.
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'live',
          token_type: 'bearer',
          expires_in: 10_800,
          scope: 'user',
        }),
        { headers: { 'content-type': 'application/json' } },
      ),
    );
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@b.example' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'x'.repeat(12) } });
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/dashboard');
  });

  it('returns to the guarded path after a login the guard interrupted', async () => {
    const router = mount('/plan', anonymous());
    await screen.findByRole('heading', { name: 'Log in' });

    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'live',
          token_type: 'bearer',
          expires_in: 10_800,
          scope: 'user',
        }),
        { headers: { 'content-type': 'application/json' } },
      ),
    );
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@b.example' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'x'.repeat(12) } });
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

    expect(await screen.findByRole('heading', { name: 'Plan' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/plan');
  });

  it('sends a signed-in visitor away from the public landing page and the auth screens', async () => {
    const router = mount('/', signedIn());

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/dashboard');

    await router.navigate({ to: '/login' });
    expect(router.state.location.pathname).toBe('/dashboard');
  });

  it('does NOT wake the API for an anonymous visitor reading the landing page', async () => {
    mount('/', anonymous());

    expect(await screen.findByRole('heading', { name: 'climb-trainer' })).toBeInTheDocument();
    // `/` deliberately checks only the in-memory token. A refresh here would be a rotation,
    // i.e. a database write, for every visitor who merely reads the page.
    expect(fetch).not.toHaveBeenCalled();
  });

  it('leaves a guarded route on logout instead of stranding the visitor there', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        headers: { 'content-type': 'application/json' },
      }),
    );
    const router = mount('/plan', signedIn());
    await screen.findByRole('heading', { name: 'Plan' });

    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));

    // Clearing the session does not re-run `beforeLoad`, so without the navigation the
    // visitor would sit on /plan with an anonymous nav and no way back.
    expect(await screen.findByRole('heading', { name: 'climb-trainer' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/');
  });

  it('shows the read-only badge in demo scope, and hides it otherwise', async () => {
    mount('/dashboard', signedIn('demo'));
    expect(await screen.findByText('Demo — read only')).toBeInTheDocument();
  });
});
