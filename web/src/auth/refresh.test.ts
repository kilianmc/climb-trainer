import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';
import { createAuthedFetch } from './refresh';
import { createSessionStore, type SessionStore } from './session';

/**
 * The three properties that make silent refresh safe, and one that makes it correct for demo
 * mode. Each is a real failure the naive version ships:
 *
 * - **single-flight.** `refresh.rotate` reads its row `FOR UPDATE` and treats a second
 *   presentation of an already-rotated token as theft, revoking the whole family. Two
 *   concurrent 401s racing two refreshes therefore log the user out of every device — this is
 *   a correctness requirement, not a request-count optimisation.
 * - **exactly one retry, and no recursion.** A refresh that succeeds but is followed by
 *   another 401 must surface it, not loop.
 * - **credential endpoints are never refreshed.** A 401 from `/api/auth/login` is a wrong
 *   password; refreshing `/api/auth/refresh` itself would recurse.
 * - **demo scope re-mints.** `POST /api/auth/demo` sets no cookie, so there is nothing to
 *   rotate, and sending its token to `/api/auth/refresh` hits the demo write-ban and 403s.
 */
type Reply = {
  status: number;
  body: unknown;
  /** `'html'` makes `apiFetch` raise `NotJsonError`; `'offline'` makes `fetch` itself reject. */
  as?: 'html' | 'offline';
};

const TOKEN = (scope: 'user' | 'demo', value: string): Reply => ({
  status: 200,
  body: { access_token: value, token_type: 'bearer', expires_in: 10_800, scope },
});
const UNAUTHORISED: Reply = { status: 401, body: { detail: 'Not authenticated.' } };
const OK: Reply = { status: 200, body: { ok: true } };
/** A rewrite serving the SPA shell for an /api path: 200, but not JSON. */
const SPA_SHELL: Reply = { status: 200, body: '<!doctype html>', as: 'html' };
/** The network is gone — `fetch` rejects, so no request ever reached FastAPI. */
const OFFLINE: Reply = { status: 0, body: null, as: 'offline' };

/** Replies queued per path, so a test states the server's behaviour rather than a sequence. */
let replies: Map<string, Reply[]>;
let calls: string[];
let session: SessionStore;
/** When set, the refresh reply is withheld until it resolves — a refresh held mid-flight. */
let holdRefresh: Promise<void> | null;

function reply(path: string, ...queued: Reply[]) {
  replies.set(path, queued);
}

function headersSentTo(path: string): Record<string, string>[] {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => urlOf(url).endsWith(path))
    .map(([, init]) => (init?.headers ?? {}) as Record<string, string>);
}

/** A promise plus its resolver, for holding a request open across other work. */
function gate(): { blocked: Promise<void>; release: () => void } {
  let release = () => undefined as void;
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { blocked, release };
}

beforeEach(() => {
  replies = new Map();
  calls = [];
  holdRefresh = null;
  session = createSessionStore();

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const path = new URL(url, 'https://climb.kilianmc.com').pathname;
      calls.push(path);
      if (path === '/api/auth/refresh' && holdRefresh !== null) await holdRefresh;
      // The last queued reply repeats, so a test only lists the replies that differ.
      const queued = replies.get(path);
      const chosen =
        (queued !== undefined && queued.length > 1 ? queued.shift() : queued?.[0]) ?? OK;

      if (chosen.as === 'offline') throw new TypeError('Failed to fetch');
      const html = chosen.as === 'html';
      return new Response(html ? String(chosen.body) : JSON.stringify(chosen.body), {
        status: chosen.status,
        headers: { 'content-type': html ? 'text/html; charset=utf-8' : 'application/json' },
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** `fetch`'s first argument is `RequestInfo | URL`; only one of the three is a string. */
function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

describe('createAuthedFetch', () => {
  it('refreshes ONCE for concurrent 401s and resolves every caller', async () => {
    session.set('stale', 'user');
    reply('/api/bootstrap', UNAUTHORISED, OK, OK);
    reply('/api/plans', UNAUTHORISED, OK, OK);
    reply('/api/auth/refresh', TOKEN('user', 'fresh'));

    const { request } = createAuthedFetch(session);
    const [a, b] = await Promise.all([
      request<{ ok: boolean }>('/api/bootstrap'),
      request<{ ok: boolean }>('/api/plans'),
    ]);

    expect(a).toEqual({ ok: true });
    expect(b).toEqual({ ok: true });
    expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(1);
    expect(session.get().token).toBe('fresh');
  });

  it('retries with the NEW token, not the one that just 401ed', async () => {
    session.set('stale', 'user');
    reply('/api/bootstrap', UNAUTHORISED, OK);
    reply('/api/auth/refresh', TOKEN('user', 'fresh'));

    const { request } = createAuthedFetch(session);
    await request('/api/bootstrap');

    const authorizations = vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => urlOf(url).endsWith('/api/bootstrap'))
      .map(([, init]) => (init?.headers as Record<string, string>).authorization);

    expect(authorizations).toEqual(['Bearer stale', 'Bearer fresh']);
  });

  it('clears the session and surfaces the 401 when the refresh fails', async () => {
    session.set('stale', 'user');
    reply('/api/bootstrap', UNAUTHORISED);
    reply('/api/auth/refresh', UNAUTHORISED);

    const { request } = createAuthedFetch(session);
    await expect(request('/api/bootstrap')).rejects.toBeInstanceOf(ApiError);

    expect(session.get()).toEqual({ token: null, scope: null });
    // One refresh attempt, and the failed request is not tried a third time.
    expect(calls).toEqual(['/api/bootstrap', '/api/auth/refresh']);
  });

  it('does not loop when the retry 401s as well', async () => {
    session.set('stale', 'user');
    reply('/api/bootstrap', UNAUTHORISED);
    reply('/api/auth/refresh', TOKEN('user', 'fresh'));

    const { request } = createAuthedFetch(session);
    await expect(request('/api/bootstrap')).rejects.toBeInstanceOf(ApiError);

    expect(calls).toEqual(['/api/bootstrap', '/api/auth/refresh', '/api/bootstrap']);
  });

  it('never refreshes a credential endpoint — a 401 there is the answer', async () => {
    reply('/api/auth/login', UNAUTHORISED);

    const { request } = createAuthedFetch(session);
    await expect(request('/api/auth/login', { json: {} })).rejects.toBeInstanceOf(ApiError);

    expect(calls).toEqual(['/api/auth/login']);
  });

  it('re-mints a demo session instead of refreshing it', async () => {
    session.set('demo-stale', 'demo');
    reply('/api/bootstrap', UNAUTHORISED, OK);
    reply('/api/auth/demo', TOKEN('demo', 'demo-fresh'));

    const { request } = createAuthedFetch(session);
    await request('/api/bootstrap');

    expect(calls).toEqual(['/api/bootstrap', '/api/auth/demo', '/api/bootstrap']);
    expect(calls).not.toContain('/api/auth/refresh');
    expect(session.get()).toEqual({ token: 'demo-fresh', scope: 'demo' });
  });

  /**
   * The memo. `bootstrap()` used to cap itself while `request()` capped nothing, so once the
   * store was anonymous `stale` and `current` were both `null`, the early-out never fired, and
   * every 401 minted another attempt. `refresh_tokens` checks the cookie before the rate
   * limiter, so a cookie-less visitor is free — but a cookie that is present and INVALID (the
   * state after a revoked family) falls through to a `ratelimit.enforce` upsert. That is one
   * Postgres write and one restarted five-minute Neon window per 401, until the 30/hour bucket
   * 429s.
   */
  it('refreshes at most ONCE after a failure, however many 401s follow', async () => {
    session.set('stale', 'user');
    reply('/api/plans', UNAUTHORISED);
    reply('/api/auth/refresh', UNAUTHORISED);

    const { request } = createAuthedFetch(session);
    for (let attempt = 0; attempt < 3; attempt += 1) {
      await expect(request('/api/plans')).rejects.toBeInstanceOf(ApiError);
    }

    expect(calls.filter((path) => path === '/api/plans')).toHaveLength(3);
    expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(1);
  });

  /**
   * `exhausted` protects against an unbounded Postgres write per 401, and a write only happens
   * if the request reached FastAPI's rate limiter — which needs a real JSON response. Neither of
   * these got there, so latching would disable refresh for the rest of the page load over an
   * infrastructure blip, while reporting it to the user as a logged-out session.
   */
  it.each([
    ['a dropped connection', OFFLINE],
    ['an HTML shell from a bad rewrite', SPA_SHELL],
  ])('does not latch on %s, because no rate-limit write happened', async (_label, failure) => {
    session.set('stale', 'user');
    reply('/api/plans', UNAUTHORISED);
    reply('/api/auth/refresh', failure, failure, TOKEN('user', 'recovered'));

    const { request } = createAuthedFetch(session);
    await expect(request('/api/plans')).rejects.toThrow();
    await expect(request('/api/plans')).rejects.toThrow();

    // Two attempts, not one — the opposite of the 401 case immediately above.
    expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(2);
  });

  it('positive control: a real 401 from the API DOES latch', async () => {
    session.set('stale', 'user');
    reply('/api/plans', UNAUTHORISED);
    reply('/api/auth/refresh', UNAUTHORISED);

    const { request } = createAuthedFetch(session);
    await expect(request('/api/plans')).rejects.toThrow();
    await expect(request('/api/plans')).rejects.toThrow();

    expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(1);
  });

  it('re-arms once a token arrives by another route, so a login is not a dead end', async () => {
    session.set('stale', 'user');
    reply('/api/plans', UNAUTHORISED, UNAUTHORISED, OK);
    reply('/api/auth/refresh', UNAUTHORISED, TOKEN('user', 'second-chance'));

    const { request } = createAuthedFetch(session);
    await expect(request('/api/plans')).rejects.toBeInstanceOf(ApiError);
    expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(1);

    // Stands in for a successful login: `authClient` sets a token on the same store.
    session.set('from-login', 'user');
    await request('/api/plans');

    expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(2);
  });

  /**
   * A refresh that resolves after a deliberate session change must not write into it. Without
   * the generation check the nav shows a signed-in user who just logged out, holding an access
   * token whose refresh family the server has already revoked — and the refresh response's
   * `Set-Cookie` lands after logout cleared the jar.
   */
  it('does not resurrect the session when a logout lands mid-refresh', async () => {
    session.set('stale', 'user');
    reply('/api/auth/refresh', TOKEN('user', 'resurrected'));
    const { blocked, release } = gate();
    holdRefresh = blocked;

    const { reauthenticate } = createAuthedFetch(session);
    const attempt = reauthenticate('stale');

    // What `authClient.logout()` does first, and the thing that bumps the generation.
    session.clear();
    release();

    await expect(attempt).resolves.toBe(false);
    expect(session.get()).toEqual({ token: null, scope: null });
  });

  it('lets a login that lands mid-refresh win, and still reports success', async () => {
    session.set('stale', 'user');
    reply('/api/auth/refresh', TOKEN('user', 'from-refresh'));
    const { blocked, release } = gate();
    holdRefresh = blocked;

    const { reauthenticate } = createAuthedFetch(session);
    const attempt = reauthenticate('stale');

    session.clear();
    session.set('from-login', 'user');
    release();

    // True, because the app DOES hold a usable token — so a request that 401ed still retries.
    await expect(attempt).resolves.toBe(true);
    expect(session.get().token).toBe('from-login');
  });

  /**
   * `CREDENTIAL_PATHS` suppresses the retry; it has to suppress the HEADER too. The demo
   * write-ban 403s a demo bearer on every mutating `/api/auth/*` route, and `authClient`
   * clearing the store beforehand is a property of its call sites, not of this code path.
   */
  it('attaches no bearer to a credential path, even holding a demo token', async () => {
    session.set('demo-token', 'demo');
    reply('/api/auth/logout', OK);

    const { request } = createAuthedFetch(session);
    await request('/api/auth/logout', { method: 'POST' });

    expect(headersSentTo('/api/auth/logout')[0]).not.toHaveProperty('authorization');
  });

  it('positive control: it does attach one to /api/auth/me, which is a read', async () => {
    session.set('demo-token', 'demo');
    reply('/api/auth/me', OK);

    const { request } = createAuthedFetch(session);
    await request('/api/auth/me');

    expect(headersSentTo('/api/auth/me')[0]?.authorization).toBe('Bearer demo-token');
  });

  it('skips the refresh entirely if a concurrent waiter already got a token', async () => {
    session.set('stale', 'user');
    const { request, reauthenticate } = createAuthedFetch(session);

    // Stands in for the winner of the race having already replaced the token.
    session.set('fresh', 'user');
    await expect(reauthenticate('stale')).resolves.toBe(true);
    expect(calls).toEqual([]);

    reply('/api/bootstrap', OK);
    await request('/api/bootstrap');
    expect(calls).toEqual(['/api/bootstrap']);
  });
});
