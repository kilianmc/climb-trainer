import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';
import { SessionUnavailableError, createAuthedFetch } from './refresh';
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
  /**
   * `'html'` makes `apiFetch` raise `NotJsonError`; `'offline'` makes `fetch` itself reject;
   * `'hang'` never settles **unless the request carries a signal** — the platform's behaviour,
   * and the reason a request with no deadline on it strands its caller forever.
   */
  as?: 'html' | 'offline' | 'hang';
  /**
   * Latency, on the fake clock. **This is the arm that models the real server**, and its absence
   * is what let the orphaned-rotation defect through: every other stand-in here behaves as though
   * the API ceases to exist the moment the client stops listening. It does not — `POST
   * /api/auth/refresh` is a sync `def` in a threadpool and commits before it answers.
   */
  after?: number;
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
/** The connection is open and nothing comes back: no rejection, so nothing above it runs. */
const HANG: Reply = { status: 0, body: null, as: 'hang' };
/** The API is up but broken. It answered, but not with an answer about the session. */
const SERVER_ERROR: Reply = { status: 503, body: { detail: 'upstream unavailable' } };
/**
 * A **platform** 5xx, and therefore HTML — which is the shape a 5xx actually arrives in here.
 * Vercel serves `FUNCTION_INVOCATION_TIMEOUT` (504) and its mid-deploy 502 as error *pages*, so
 * this reaches the client as `NotJsonError(504)`. Its absence from this file is exactly why the
 * classifier shipped testing `!(error instanceof NotJsonError)` before `status >= 500` and sent
 * every platform timeout to `/login`.
 */
const HTML_GATEWAY_TIMEOUT: Reply = { status: 504, body: '<!doctype html>', as: 'html' };

/** Replies queued per path, so a test states the server's behaviour rather than a sequence. */
let replies: Map<string, Reply[]>;
let calls: string[];
let session: SessionStore;
/** The `signal` each request actually carried, so "did NOT abort" is assertable. */
let sentSignals: (AbortSignal | null)[];
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
  sentSignals = [];
  session = createSessionStore();

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url, 'https://climb.kilianmc.com').pathname;
      calls.push(path);
      sentSignals.push(init?.signal ?? null);
      // Also signal-blind, also deliberate: the tests that use it release it by hand on the real
      // clock, so no abort can fire inside it. The `after` arm below is the one that must listen.
      if (path === '/api/auth/refresh' && holdRefresh !== null) await holdRefresh;
      // The last queued reply repeats, so a test only lists the replies that differ.
      const queued = replies.get(path);
      const chosen =
        (queued !== undefined && queued.length > 1 ? queued.shift() : queued?.[0]) ?? OK;

      if (chosen.as === 'hang') {
        // What the platform does: a `fetch` rejects with the signal's abort reason, and with no
        // signal it simply never settles. Modelling BOTH arms is what makes the deadline tests
        // fail when the deadline is taken away, rather than passing on an unrelated path.
        return await new Promise<Response>((_resolve, reject) => {
          const { signal } = init ?? {};
          // `reason` is `any` in lib.dom; the platform puts a DOMException there.
          signal?.addEventListener('abort', () => reject(signal.reason as Error));
        });
      }
      const after = chosen.after;
      if (after !== undefined) {
        // ⚠️ Races the latency against the request's OWN SIGNAL, exactly as the `hang` arm does.
        // A bare `setTimeout` here made the flagship test unfailable: it resolved at 12 s whether
        // or not the client had aborted at 8 s, so it asserted this stand-in's indifference to
        // aborts rather than the code's restraint. A stand-in that ignores `signal` cannot
        // distinguish "we did not abort" from "aborting would not have mattered".
        const signal = init?.signal ?? null;
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(resolve, after);
          signal?.addEventListener('abort', () => {
            clearTimeout(timer);
            reject(signal.reason as Error);
          });
        });
      }
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

/**
 * `AbortSignal.timeout` runs on a platform timer Vitest's fake timers do **not** replace —
 * measured: advancing 9 s leaves the signal un-aborted. So the HARD tier is driven through a
 * controller-backed stand-in that schedules on the faked `setTimeout`, and the duration the auth
 * path asked for is recorded so the 30 s stays asserted rather than assumed.
 *
 * The UI tier needs no stand-in: it is a plain `setTimeout` racing the *await*, which is exactly
 * the difference between the two tiers made visible in the test harness.
 */
function fakeDeadlines(): { readonly requested: number[] } {
  const requested: number[] = [];
  vi.spyOn(AbortSignal, 'timeout').mockImplementation((ms: number) => {
    requested.push(ms);
    const controller = new AbortController();
    setTimeout(() => {
      controller.abort(new DOMException('The operation timed out.', 'TimeoutError'));
    }, ms);
    return controller.signal;
  });
  return { requested };
}

/** Attaches handlers up front: an unobserved rejection across a fake-clock tick fails the run. */
function watch(attempt: Promise<boolean>): Promise<unknown> {
  return attempt.then(
    (held) => `resolved ${String(held)}`,
    (error: unknown) => error,
  );
}

/**
 * The two-tier deadline (issue #28, reshaped after review).
 *
 * The first cut of this fix put a single `AbortSignal.timeout(8_000)` on the POST, and that was
 * **worse than the bug it fixed**. `POST /api/auth/refresh` is a sync `def` running in anyio's
 * threadpool, so a client disconnect cannot cancel it, and it commits the rotation *before* the
 * response exists. Abort at 8 s and the server still rotates at 9 s — leaving the successor token
 * live on the server, stored only as a sha256, and held by nobody. The next attempt gets a double
 * 409 or trips reuse detection and revokes the family. So:
 *
 * - **`UI_DEADLINE_MS` (8 s) stops AWAITING.** The route leaves the pending component; the POST
 *   runs on, commits, and its `Set-Cookie` lands. `inFlight` stays alive so a retry re-joins it.
 * - **`HARD_ABORT_MS` (30 s) aborts the SOCKET**, above every server ceiling, so that an abort
 *   once again means "gone" rather than "slow".
 *
 * The tests below are written so that collapsing the two values back into one goes red.
 */
describe('the two-tier auth deadline', () => {
  let deadlines: { readonly requested: number[] };

  beforeEach(() => {
    vi.useFakeTimers();
    deadlines = fakeDeadlines();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('stops awaiting at 8 s — and does NOT abort the request', async () => {
    reply('/api/auth/refresh', HANG);
    const { reauthenticate } = createAuthedFetch(session);

    const outcome = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(7_999);
    // The 8 s tier is a `setTimeout` on the await, so the request must have been given the 30 s
    // signal and nothing else. Asking the platform for 8 s here is the defect, not the fix.
    expect(deadlines.requested).toEqual([30_000]);

    await vi.advanceTimersByTimeAsync(1);
    const fault = await outcome;

    expect(fault).toBeInstanceOf(SessionUnavailableError);
    expect((fault as Error).message).toMatch(/still running/);
    // The whole point: the socket is untouched, so the rotation the server may already have
    // committed still gets to deliver its Set-Cookie.
    expect(sentSignals[0]?.aborted).toBe(false);
    expect(calls).toEqual(['/api/auth/refresh']);
  });

  it('aborts the socket at 30 s, and not a moment before', async () => {
    reply('/api/auth/refresh', HANG);
    const { reauthenticate } = createAuthedFetch(session);

    void watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(29_999);
    expect(sentSignals[0]?.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(1);
    expect(sentSignals[0]?.aborted).toBe(true);
    // Still exactly one POST: the hard tier bounds a wedged socket, it does not re-drive anything.
    expect(calls).toEqual(['/api/auth/refresh']);
  });

  /**
   * The property the whole reshape exists for, and the one the old suite asserted was impossible.
   * A server that is merely slow finishes: the rotation commits, the cookie lands, and the
   * session the caller gave up on becomes usable. An 8 s abort would have thrown that away and
   * orphaned the successor token.
   */
  it('lets a slow refresh LAND after the caller gave up, and the session becomes usable', async () => {
    reply('/api/auth/refresh', { ...TOKEN('user', 'landed-late'), after: 12_000 });
    const { reauthenticate } = createAuthedFetch(session);

    const outcome = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(8_000);
    expect(await outcome).toBeInstanceOf(SessionUnavailableError);
    expect(session.get().token).toBeNull();

    await vi.advanceTimersByTimeAsync(4_001);

    expect(session.get()).toEqual({ token: 'landed-late', scope: 'user' });
    expect(calls).toEqual(['/api/auth/refresh']);
  });

  /**
   * What the retry button on the error boundary does, at this layer. It must re-join the attempt
   * still in the air — a second POST would present the pre-rotation cookie again, which is one
   * more Postgres write and a walk straight into the collision the design avoids.
   */
  it('re-joins the in-flight refresh on a retry instead of sending a second POST', async () => {
    reply('/api/auth/refresh', { ...TOKEN('user', 'shared'), after: 12_000 });
    const { reauthenticate } = createAuthedFetch(session);

    const first = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(8_000);
    expect(await first).toBeInstanceOf(SessionUnavailableError);

    // The retry, while the original POST is still in the air.
    const second = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(4_001);

    expect(await second).toBe('resolved true');
    expect(session.get().token).toBe('shared');
    expect(calls).toEqual(['/api/auth/refresh']);
  });

  it('puts the hard abort on a demo re-mint too, the other auth POST', async () => {
    session.set('demo-stale', 'demo');
    reply('/api/auth/demo', HANG);
    const { reauthenticate } = createAuthedFetch(session);

    const outcome = watch(reauthenticate('demo-stale'));
    await vi.advanceTimersByTimeAsync(8_000);

    expect(await outcome).toBeInstanceOf(SessionUnavailableError);
    expect(deadlines.requested).toEqual([30_000]);
    expect(calls).toEqual(['/api/auth/demo']);
  });

  /**
   * `false` here would not be a lesser answer, it would be the wrong one: `_authed` turns it
   * into a redirect to `/login`, which is a claim about the visitor's session that none of these
   * failures established.
   *
   * `HTML_GATEWAY_TIMEOUT` is the case that shipped broken. It is a `NotJsonError`, so a
   * classifier that excludes `NotJsonError` before testing the status returns `null` for it —
   * and HTML is what a platform 5xx *is*.
   */
  it.each([
    ['a request that never settles', HANG],
    ['a dropped connection', OFFLINE],
    ['a JSON 5xx from the API', SERVER_ERROR],
    ['an HTML 504 from the platform', HTML_GATEWAY_TIMEOUT],
  ])('does not report %s as "no session"', async (_label, failure) => {
    reply('/api/auth/refresh', failure);
    const { reauthenticate } = createAuthedFetch(session);

    const outcome = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(8_000);

    expect(await outcome).toBeInstanceOf(SessionUnavailableError);
    expect(session.get().token).toBeNull();
  });

  it.each([
    ['a 401 — no usable cookie', UNAUTHORISED],
    ['an HTML 200 — a rewrite serving the SPA shell', SPA_SHELL],
  ])('positive control: %s IS an answer, so it still resolves false', async (_label, answered) => {
    reply('/api/auth/refresh', answered);
    const { reauthenticate } = createAuthedFetch(session);

    const outcome = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(8_000);

    expect(await outcome).toBe('resolved false');
  });

  /**
   * The write cap, on the path where nothing latches. An unanswered attempt leaves `exhausted`
   * clear on purpose — the API may recover — so without a counter every subsequent guarded
   * navigation starts a brand-new POST: one `ratelimit.enforce` upsert and one restarted
   * five-minute Neon window each. Two attempts per **mount** (`remote.tsx` builds one `Auth` per
   * mount instance, so this is not a page-load budget), then the recorded fault is replayed.
   * **Never `false`** — running out of attempts must not become a logout. Only faults that
   * actually reached the server count; see the offline test above.
   */
  it.each([
    ['a timeout', HANG],
    ['a 5xx', HTML_GATEWAY_TIMEOUT],
  ])(
    'gives a second navigation a fresh attempt after %s, then caps at two',
    async (_label, bad) => {
      reply('/api/auth/refresh', bad);
      const { reauthenticate } = createAuthedFetch(session);

      for (const expected of [1, 2, 2, 2]) {
        const outcome = watch(reauthenticate(null));
        await vi.advanceTimersByTimeAsync(30_001);
        expect(await outcome).toBeInstanceOf(SessionUnavailableError);
        expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(expected);
      }
    },
  );

  /**
   * ⚠️ The cap must NOT count a request that never opened a connection — and this is the case
   * that made the retry button a permanent no-op. On a dead radio `fetch` rejects *instantly*, so
   * there is no 8 s wait to slow anyone down: two clicks inside a second spent both attempts, and
   * because `unanswered` is only reset when a token arrives, the signal coming back did not
   * re-arm anything. The visitor was left clicking a button that never sent a request again for
   * the life of the mount.
   *
   * It is also the same reasoning `exhausted` already applies: a `TypeError: Failed to fetch`
   * never reached FastAPI's rate limiter, so it cost **zero** Postgres writes, and the cap's only
   * justification is the cost of a write. Ten of these in a row are still ten free attempts.
   */
  it('never spends the cap on a connection that never opened, however many times it fails', async () => {
    reply('/api/auth/refresh', OFFLINE);
    const { reauthenticate } = createAuthedFetch(session);

    for (let attempt = 1; attempt <= 5; attempt += 1) {
      const outcome = watch(reauthenticate(null));
      await vi.advanceTimersByTimeAsync(1);
      expect(await outcome).toBeInstanceOf(SessionUnavailableError);
      expect(calls.filter((path) => path === '/api/auth/refresh')).toHaveLength(attempt);
    }
  });

  /**
   * The recovery the test above protects, end to end at this layer: the radio comes back and the
   * very next attempt works, with no reload and nothing to reset by hand.
   */
  it('still refreshes once the network returns, after a run of offline failures', async () => {
    reply('/api/auth/refresh', OFFLINE, OFFLINE, OFFLINE, TOKEN('user', 'signal-came-back'));
    const { reauthenticate } = createAuthedFetch(session);

    for (let attempt = 0; attempt < 3; attempt += 1) {
      const outcome = watch(reauthenticate(null));
      await vi.advanceTimersByTimeAsync(1);
      expect(await outcome).toBeInstanceOf(SessionUnavailableError);
    }

    const recovered = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(1);

    expect(await recovered).toBe('resolved true');
    expect(session.get()).toEqual({ token: 'signal-came-back', scope: 'user' });
  });

  it('re-arms the cap once a token arrives by another route', async () => {
    reply('/api/auth/refresh', HANG);
    const { reauthenticate } = createAuthedFetch(session);

    for (let attempt = 0; attempt < 2; attempt += 1) {
      const outcome = watch(reauthenticate(null));
      await vi.advanceTimersByTimeAsync(30_001);
      expect(await outcome).toBeInstanceOf(SessionUnavailableError);
    }
    expect(calls).toHaveLength(2);

    // Stands in for a login: a token in hand means the cookie situation changed.
    session.set('from-login', 'user');
    session.clear();
    const outcome = watch(reauthenticate(null));
    await vi.advanceTimersByTimeAsync(30_001);

    expect(await outcome).toBeInstanceOf(SessionUnavailableError);
    expect(calls).toHaveLength(3);
  });

  /**
   * A deliberate session change still wins, and must not be dressed up as an infrastructure
   * fault. The reply lands *inside* the UI deadline here, because that is the only window in
   * which the two can be told apart: past 8 s the caller has already stopped listening, and a
   * logout that late also navigates away from the guarded route (`__root.tsx::logOut`).
   */
  it('does not raise unavailability when a logout lands mid-refresh', async () => {
    session.set('stale', 'user');
    reply('/api/auth/refresh', { ...TOKEN('user', 'resurrected'), after: 2_000 });
    const { reauthenticate } = createAuthedFetch(session);

    const outcome = watch(reauthenticate('stale'));
    session.clear();
    await vi.advanceTimersByTimeAsync(2_001);

    expect(await outcome).toBe('resolved false');
    expect(session.get()).toEqual({ token: null, scope: null });
  });
});
