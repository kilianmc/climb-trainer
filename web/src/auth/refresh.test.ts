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
type Reply = { status: number; body: unknown };

const TOKEN = (scope: 'user' | 'demo', value: string): Reply => ({
  status: 200,
  body: { access_token: value, token_type: 'bearer', expires_in: 10_800, scope },
});
const UNAUTHORISED: Reply = { status: 401, body: { detail: 'Not authenticated.' } };
const OK: Reply = { status: 200, body: { ok: true } };

/** Replies queued per path, so a test states the server's behaviour rather than a sequence. */
let replies: Map<string, Reply[]>;
let calls: string[];
let session: SessionStore;

function reply(path: string, ...queued: Reply[]) {
  replies.set(path, queued);
}

beforeEach(() => {
  replies = new Map();
  calls = [];
  session = createSessionStore();

  vi.stubGlobal(
    'fetch',
    // eslint-disable-next-line @typescript-eslint/require-await
    vi.fn(async (url: string) => {
      const path = new URL(url, 'https://climb.kilianmc.com').pathname;
      calls.push(path);
      // The last queued reply repeats, so a test only lists the replies that differ.
      const queued = replies.get(path);
      const chosen =
        (queued !== undefined && queued.length > 1 ? queued.shift() : queued?.[0]) ?? OK;
      return new Response(JSON.stringify(chosen.body), {
        status: chosen.status,
        headers: { 'content-type': 'application/json' },
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
