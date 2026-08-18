import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createAuthedFetch } from './refresh';
import { createSessionStore, type SessionStore } from './session';

/**
 * Two tabs, one cookie jar. This is the failure the per-mount `inFlight` dedupe cannot see:
 * `inFlight` is a local of `createAuthedFetch`, so two mounts have two of them, while the
 * refresh cookie is scoped to the whole browser profile.
 *
 * The model below is the part that makes the test meaningful, so it is worth stating what it
 * reproduces from the real server (`server/auth/refresh.py::rotate`):
 *
 * - the browser attaches the cookie **at send time**, which is why `presented` is captured
 *   synchronously before any latency;
 * - `Set-Cookie` reaches the jar **when the response arrives**, not when it is sent;
 * - presenting an already-rotated token is **reuse**, and reuse revokes the whole family —
 *   killing the token the winner just received, not merely failing the loser.
 *
 * Both arms run the same scenario. The locked arm is the guarantee; the unlocked arm is the
 * permanent record of what the `navigator.locks` fallback does and does not cover, and it is
 * what makes the locked arm non-vacuous.
 */
const REFRESH_URL = '/api/auth/refresh';

/** What the browser would send, and what the server considers live. */
let jar: string | null;
let live: string | null;
let rotations: number;
let sends: number;
/** Ordered log of sends and receipts, so interleaving is visible rather than inferred. */
let events: string[];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function rotate(presented: string | null): Response {
  if (presented === null) return json({ detail: 'Not authenticated.' }, 401);
  if (presented !== live) {
    // Reuse detection. The family dies, which is what also invalidates the winner.
    live = null;
    jar = null;
    return json({ detail: 'Not authenticated.' }, 401);
  }
  rotations += 1;
  live = `refresh-${rotations + 1}`;
  jar = live;
  return json({
    access_token: `access-${rotations}`,
    token_type: 'bearer',
    expires_in: 10_800,
    scope: 'user',
  });
}

/**
 * A `LockManager` that actually serialises, by chaining callbacks per lock name. `then` is given
 * the same callback for both outcomes because the real API releases the lock whether the holder
 * resolves or rejects — a rejecting refresh must not wedge every other tab.
 */
function serialisingLockManager() {
  const chains = new Map<string, Promise<unknown>>();
  return {
    request: <T>(name: string, callback: () => Promise<T>): Promise<T> => {
      const previous = chains.get(name) ?? Promise.resolve();
      const result = previous.then(callback, callback);
      chains.set(
        name,
        result.then(
          () => undefined,
          () => undefined,
        ),
      );
      return result;
    },
  };
}

function installLocks(): void {
  Object.defineProperty(navigator, 'locks', {
    value: serialisingLockManager(),
    configurable: true,
  });
}

function removeLocks(): void {
  // jsdom ships no `navigator.locks`, so deleting it restores the real fallback condition.
  Reflect.deleteProperty(navigator, 'locks');
}

/** Two independent mounts — separate stores, separate `inFlight` closures, one shared jar. */
function twoTabs(): [SessionStore, SessionStore, () => Promise<[boolean, boolean]>] {
  const a = createSessionStore();
  const b = createSessionStore();
  const tabA = createAuthedFetch(a);
  const tabB = createAuthedFetch(b);
  return [a, b, () => Promise.all([tabA.reauthenticate(null), tabB.reauthenticate(null)])];
}

beforeEach(() => {
  jar = 'refresh-1';
  live = 'refresh-1';
  rotations = 0;
  sends = 0;
  events = [];
  removeLocks();

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      const url = typeof input === 'string' ? input : '';
      if (!url.includes(REFRESH_URL)) throw new Error(`unexpected request to ${url}`);

      const presented = jar; // the cookie the browser attaches, read at SEND time
      sends += 1;
      const id = `#${sends}`;
      events.push(`${id} send(${presented ?? 'no-cookie'})`);
      await new Promise((resolve) => setTimeout(resolve, 0));
      const response = rotate(presented);
      events.push(`${id} recv`);
      return response;
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  removeLocks();
});

describe('two mounts refreshing at once', () => {
  it('serialises through the Web Lock, so both tabs end up with a valid token', async () => {
    installLocks();
    const [a, b, run] = twoTabs();

    expect(await run()).toEqual([true, true]);

    // The second tab presented the ALREADY-ROTATED cookie and performed a legitimate rotation
    // of its own. That is the whole design: serialising is sufficient, no token is shared, and
    // the cost is one extra Postgres write per tab.
    expect(events).toEqual(['#1 send(refresh-1)', '#1 recv', '#2 send(refresh-2)', '#2 recv']);
    expect(rotations).toBe(2);
    expect(a.get().token).not.toBeNull();
    expect(b.get().token).not.toBeNull();
    expect(a.get().token).not.toBe(b.get().token);
  });

  it('documents the fallback boundary: without navigator.locks the family is revoked', async () => {
    // Not an endorsement — this is the state the code is in wherever the API is missing, and
    // it is what makes the assertion above mean something. Both tabs read the same
    // pre-rotation cookie, so the second is indistinguishable from theft.
    removeLocks();
    const [a, b, run] = twoTabs();

    const outcomes = await run();

    expect(events.slice(0, 2)).toEqual(['#1 send(refresh-1)', '#2 send(refresh-1)']);
    expect(outcomes).toContain(false);
    expect(rotations).toBe(1);
    // The loser's reuse revoked the family, so the winner's brand-new token is dead too.
    expect(live).toBeNull();
    expect([a.get().token, b.get().token]).toContain(null);
  });

  it('releases the lock when a refresh rejects, so the next tab is not wedged', async () => {
    installLocks();
    jar = null; // no cookie: every attempt 401s
    const [, , run] = twoTabs();

    expect(await run()).toEqual([false, false]);

    // Both got to send. A lock held past a rejection would leave the second pending forever.
    expect(events).toEqual(['#1 send(no-cookie)', '#1 recv', '#2 send(no-cookie)', '#2 recv']);
  });
});
