import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserHistory, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen } from '@testing-library/react';
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

/**
 * The refresh connects and nothing ever comes back. With no signal on the request this promise
 * never settles — which is issue #28 exactly: `bootstrap()` is awaited in `_authed`'s
 * `beforeLoad`, so the guarded route stayed on the pending component with no way out.
 */
function hangingRefresh() {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: unknown, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          // `RequestInit.signal` is nullable, and `reason` is `any` in lib.dom — the platform
          // puts a DOMException there. No signal at all means this promise never settles.
          const signal = init?.signal ?? null;
          if (signal === null) return;
          if (signal.aborted) {
            reject(signal.reason as Error);
            return;
          }
          signal.addEventListener('abort', () => {
            reject(signal.reason as Error);
          });
        }),
    ),
  );
  return createAuth();
}

/**
 * The HARD tier, made instant. `AbortSignal.timeout` runs on a platform timer Vitest's fake timers
 * cannot reach, and no test should sit out 30 real seconds — so this stands in for it and records
 * the duration the auth path asked for. What this file proves is **where the failure surfaces**;
 * `auth/refresh.test.ts` is where the two durations and the clock are asserted.
 */
function instantDeadlines(): { readonly requested: number[] } {
  const requested: number[] = [];
  vi.spyOn(AbortSignal, 'timeout').mockImplementation((ms: number) => {
    requested.push(ms);
    return AbortSignal.abort(new DOMException('The operation timed out.', 'TimeoutError'));
  });
  return { requested };
}

/**
 * A refresh that answers eventually, on the fake clock. This is the honest model of the live
 * server — sync `def`, threadpool, commits before it answers — and the reason the 8 s tier stops
 * awaiting rather than aborting: this request finishes whether or not anyone is still listening.
 */
function slowRefresh(afterMs: number) {
  const calls = vi.fn(
    (_url: unknown, init?: RequestInit) =>
      new Promise<Response>((resolve, reject) => {
        // Honours the request's signal, so an abort really would end this — otherwise the test
        // below would pass with the two tiers collapsed and prove nothing about them.
        const signal = init?.signal ?? null;
        const timer = setTimeout(() => {
          resolve(tokenResponse('landed-late', 'user'));
        }, afterMs);
        signal?.addEventListener('abort', () => {
          clearTimeout(timer);
          reject(signal.reason as Error);
        });
      }),
  );
  vi.stubGlobal('fetch', calls);
  return { auth: createAuth(), calls };
}

/** A visitor who already holds a token, i.e. the post-login state. */
function signedIn(scope: 'user' | 'demo' = 'user') {
  const auth = createAuth();
  auth.session.set('live-token', scope);
  return auth;
}

function tokenResponse(token: string, scope: 'user' | 'demo') {
  return new Response(
    JSON.stringify({ access_token: token, token_type: 'bearer', expires_in: 10_800, scope }),
    { headers: { 'content-type': 'application/json' } },
  );
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
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

  /**
   * Issue #28's visible symptom, and the two wrong endings it could have instead. **Pending** was
   * the bug: no timeout, so the `await` in `beforeLoad` never returned. **`/login`** is the
   * tempting fix and is also wrong — a timeout establishes nothing about the visitor's session,
   * so bouncing them to a form they cannot get past hides the fault and blames them for it.
   */
  it('ends a timed-out guarded route in the ERROR state, not on pending and not at /login', async () => {
    const deadlines = instantDeadlines();
    const router = mount('/plan', hangingRefresh());

    expect(await screen.findByRole('heading', { name: 'Something broke' })).toBeInTheDocument();
    expect(screen.getByText(/took too long to answer/)).toBeInTheDocument();

    expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Log in' })).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/plan');
    expect(deadlines.requested).toEqual([30_000]);
  });

  /**
   * The 8 s tier, end to end, and the retry it exists to make cheap.
   *
   * The route leaves the pending component while the refresh is **still running** — nothing was
   * aborted, so the rotation the server may already have committed still delivers. Clicking "Try
   * again" then re-joins that same attempt: one `POST /api/auth/refresh` for the whole episode,
   * which is the assertion at the end and the reason the button is `router.invalidate()` rather
   * than a fresh refresh.
   */
  it('leaves pending at the UI deadline, then the retry re-joins the SAME refresh', async () => {
    vi.useFakeTimers();
    const { auth, calls } = slowRefresh(12_000);
    mount('/plan', auth);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_000);
    });

    expect(screen.getByRole('heading', { name: 'Something broke' })).toBeInTheDocument();
    expect(screen.getByText(/still running/)).toBeInTheDocument();
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Log in' })).not.toBeInTheDocument();

    // Clicked while the original POST is in the air — the case that distinguishes re-joining
    // from re-sending.
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_001);
    });

    expect(screen.getByRole('heading', { name: 'Plan' })).toBeInTheDocument();
    expect(auth.session.get().token).toBe('landed-late');
    expect(calls).toHaveBeenCalledTimes(1);
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

  /**
   * The badge test below injects the token directly, so it says nothing about the path a
   * visitor actually takes. This drives the real one: the click, the `POST /api/auth/demo`,
   * the navigation and the read-only state — issue #24's acceptance criterion.
   */
  it('mints a demo token from the landing page and arrives read-only on the dashboard', async () => {
    vi.mocked(fetch).mockResolvedValue(tokenResponse('demo-token', 'demo'));
    const auth = createAuth();
    const router = mount('/', auth);
    await screen.findByRole('heading', { name: 'climb-trainer' });

    fireEvent.click(screen.getByRole('button', { name: 'Explore the demo' }));

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/dashboard');
    expect(auth.session.get().scope).toBe('demo');
    expect(screen.getByText('Demo — read only')).toBeInTheDocument();
    expect(screen.getByText(/Everything is read-only/)).toBeInTheDocument();

    // Exactly one call, to the one mutating auth route a demo token is exempt from — and with
    // no bearer on it, because the store is cleared before every POST /api/auth/*.
    const [url, init] = vi.mocked(fetch).mock.calls[0] ?? [];
    expect(urlOf(url)).toContain('/api/auth/demo');
    expect((init?.headers ?? {}) as Record<string, string>).not.toHaveProperty('authorization');
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it('surfaces a failed demo mint on the landing page instead of navigating', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'nope' }), {
        status: 429,
        headers: { 'content-type': 'application/json' },
      }),
    );
    const router = mount('/', createAuth());
    await screen.findByRole('heading', { name: 'climb-trainer' });

    fireEvent.click(screen.getByRole('button', { name: 'Explore the demo' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Too many attempts from this network. Please wait a little and try again.',
    );
    expect(router.state.location.pathname).toBe('/');
  });

  it('shows the read-only badge in demo scope, and hides it otherwise', async () => {
    mount('/dashboard', signedIn('demo'));
    expect(await screen.findByText('Demo — read only')).toBeInTheDocument();
  });
});
