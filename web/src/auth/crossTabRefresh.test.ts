import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createAuthedFetch } from './refresh';
import { createSessionStore, type SessionStore } from './session';

/**
 * Two tabs, one cookie jar. This is the failure the per-mount `inFlight` dedupe cannot see:
 * `inFlight` is a local of `createAuthedFetch`, so two mounts have two of them, while the
 * refresh cookie is one entry in one jar — stored host-only against climb.kilianmc.com, but
 * *sent* by the federated mount on kilianmc.com too, because `SameSite=Lax` is a **site**
 * rule and not an origin one.
 *
 * The model below is the part that makes the test meaningful, so it is worth stating what it
 * reproduces from the real server (`server/auth/refresh.py::rotate`):
 *
 * - the browser attaches the cookie **at send time**, which is why `presented` is captured
 *   synchronously before any latency;
 * - `Set-Cookie` reaches the jar **when the response arrives**, not when it is sent;
 * - presenting an already-rotated token **inside the grace window** is a lost race: a 409,
 *   with no state changed at all, and — *usually*, see `graceRefreshesTheJar` — the jar
 *   already holding the winner's fresh token;
 * - presenting a token that is neither live nor recently retired is **reuse**, and reuse
 *   revokes the whole family — killing the token the winner received, not merely failing the
 *   loser.
 *
 * The locked arm is the same-origin guarantee. The unlocked arm is now the **two-origin** arm
 * (issue #27), where the server's grace window is the only thing in play — and it is also what
 * keeps the locked arm honest, since the difference between them is one round trip and one
 * Postgres write rather than a working session versus a dead one.
 */
const REFRESH_URL = '/api/auth/refresh';

/** What the browser would send, and what the server considers live. */
let jar: string | null;
let live: string | null;
/** Tokens rotated away recently, i.e. inside the server's `REPLAY_GRACE`. */
let retired: Set<string>;
/**
 * Whether a 409 finds the winner's rotated cookie already in the jar.
 *
 * ⚠️ **Usually true, and only usually.** The winner's response is dispatched after the
 * `commit()` that releases the row lock, and the loser then pays its own commit round trip
 * before answering — so the winner leads by about one database round trip. That is a margin,
 * not an ordering guarantee, and the two responses then travel independently. Turning this off
 * models the loser-first ordering, which is exactly the case where the retry re-presents the
 * same token and the mount gives up.
 */
let graceRefreshesTheJar: boolean;
let rotations: number;
let sends: number;
/** When set, the API answers with the SPA shell at this status — a bad rewrite, not a race. */
let htmlShellStatus: number | null;
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
    if (retired.has(presented)) {
      // The grace window: a lost race, not theft. NOTHING is written — and the jar already
      // holds the winner's token, because the winner's response landed before this one.
      if (graceRefreshesTheJar) jar = live;
      return json({ detail: 'Refresh token superseded. Retry with the current cookie.' }, 409);
    }
    // Reuse detection. The family dies, which is what also invalidates the winner.
    live = null;
    jar = null;
    return json({ detail: 'Not authenticated.' }, 401);
  }
  retired.add(presented);
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

/**
 * Two independent mounts — separate stores, separate `inFlight` closures, one shared jar.
 *
 * ⚠️ **jsdom cannot model two origins, so what the arms below vary is the LOCK REALM, not the
 * origin.** Web Locks are partitioned per storage key, so two tabs of climb.kilianmc.com share
 * one lock manager while the standalone app and the federated mount (kilianmc.com) get two
 * independent ones — over the one refresh cookie both of them send. Two independent managers
 * exclude nothing from each other, which is behaviourally identical to having none — so
 * `installLocks()` is the same-origin arm and `removeLocks()` is the two-origin arm. The shared
 * jar is the one thing both arms have in common, and it is the real situation: one cookie,
 * host-only, sent by both origins because they are same-site.
 */
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
  retired = new Set();
  graceRefreshesTheJar = true;
  htmlShellStatus = null;
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
      const response =
        htmlShellStatus === null
          ? rotate(presented)
          : new Response('<!doctype html>', {
              status: htmlShellStatus,
              headers: { 'content-type': 'text/html' },
            });
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

  /**
   * The arm this file could not reach before issue #27: two mounts in **two separate lock
   * realms**, so nothing in the browser serialises them and the server's grace window is the
   * only mechanism left. Before it, this scenario ended with the family revoked and both
   * sessions dead — a standalone tab plus the climb-trainer card open on the portfolio.
   */
  it('lets two mounts in separate lock realms both refresh, through the 409 and one retry', async () => {
    removeLocks();
    const [a, b, run] = twoTabs();

    expect(await run()).toEqual([true, true]);

    // Both presented the pre-rotation cookie. The loser got a 409, sent again, and rotated the
    // token the winner had left in the shared jar — an ordinary rotation, not a replay.
    expect(events.slice(0, 2)).toEqual(['#1 send(refresh-1)', '#2 send(refresh-1)']);
    expect(events.at(-2)).toBe('#3 send(refresh-2)');
    expect(sends).toBe(3);
    expect(rotations).toBe(2);

    // The family is intact. This is the whole fix: nothing was revoked, so both mounts hold a
    // usable token and neither user is logged out.
    expect(live).not.toBeNull();
    expect(a.get().token).not.toBeNull();
    expect(b.get().token).not.toBeNull();
    expect(a.get().token).not.toBe(b.get().token);

    // And the cost of having no lock, stated as a number: one extra round trip and one extra
    // Postgres write against the locked arm's two sends. That is why the lock is kept.
    expect(sends).toBeGreaterThan(2);
  });

  /**
   * Presence is not usability: in an opaque or sandboxed origin `navigator.locks` exists, looks
   * right, and `request()` rejects. No feature test can see that, so `withRefreshLock` tells the
   * cases apart by whether its callback was entered. A refusal must degrade to the unlocked path
   * — not surface as a failed refresh, which would clear the session and report an
   * infrastructure problem to the user as a logged-out one.
   */
  it('degrades to unlocked when the lock manager refuses without running the callback', async () => {
    Object.defineProperty(navigator, 'locks', {
      value: {
        request: () => Promise.reject(new DOMException('denied', 'SecurityError')),
      },
      configurable: true,
    });
    const [a, , run] = twoTabs();

    const outcomes = await run();

    // The refresh still happened, so the refusal was not mistaken for a dead cookie.
    expect(outcomes[0]).toBe(true);
    expect(a.get().token).toBe('access-1');
    // Two rotations, not one: a refused lock serialises nothing, so the second mount lost the
    // race and reached its token through the server's 409 rather than being revoked.
    expect(rotations).toBe(2);
  });

  it.each([
    ['a non-callable request', { request: 'nope' }],
    ['an empty object', {}],
    ['a primitive', 'locks'],
  ])('treats %s as no lock manager at all rather than throwing', async (_label, value) => {
    Object.defineProperty(navigator, 'locks', { value, configurable: true });
    const [a, , run] = twoTabs();

    await run();

    expect(a.get().token).toBe('access-1');
  });

  it('retries the 409 inside the lock, so a waiting tab still cannot interleave', async () => {
    installLocks();
    // The mount starts from a cookie that another realm rotated away a moment ago.
    jar = 'refresh-0';
    retired.add('refresh-0');
    const [a, b, run] = twoTabs();

    expect(await run()).toEqual([true, true]);

    // Three sends, B's last. ⚠️ The event log is NOT what discriminates here: a variant that
    // takes the lock per POST produces a byte-identical log, because the mock's grace path
    // refreshes the jar, so nobody ever sends a stale cookie. What changes is ROTATION
    // OWNERSHIP — with the retry outside the lock, B slips in between A's two sends and takes
    // the first rotation, so A ends up with `access-2`. Hence the assertion below.
    expect(events).toEqual([
      '#1 send(refresh-0)',
      '#1 recv',
      '#2 send(refresh-1)',
      '#2 recv',
      '#3 send(refresh-2)',
      '#3 recv',
    ]);
    expect(a.get().token).toBe('access-1');
    expect(b.get().token).toBe('access-2');
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

/**
 * The single-mount half of the 409 contract. Two properties, and the second one is why the
 * retry has to live inside `mint`:
 *
 * - exactly ONE retry, so a server that keeps answering 409 cannot spin the client;
 * - an intermediate 409 must not consume the `exhausted` failure memo, which would disable
 *   refresh for the rest of the page load over a race that was already handled.
 *
 * `exhausted` is a closure local with no getter, and a successful refresh clears it through the
 * store's subscriber, so its state after a *successful* attempt cannot be read directly. The
 * observable proxy is the pair below: the intermediate case ends with a token after two sends,
 * and the genuinely-failing case stops sending altogether on the next attempt — which is the
 * latch doing its job. A naive retry placed outside `mint` fails the first of those, because the
 * 409 reaches `mint`'s catch, latches, and reports the page as logged out.
 */
describe('a 409 from the refresh endpoint', () => {
  function oneMount(): [SessionStore, () => Promise<boolean>] {
    const store = createSessionStore();
    const { reauthenticate } = createAuthedFetch(store);
    return [store, () => reauthenticate(null)];
  }

  it('is retried once, and the retry rotates the cookie the winner left in the jar', async () => {
    jar = 'refresh-0';
    retired.add('refresh-0');
    const [store, refreshOnce] = oneMount();

    expect(await refreshOnce()).toBe(true);

    expect(events).toEqual(['#1 send(refresh-0)', '#1 recv', '#2 send(refresh-1)', '#2 recv']);
    expect(store.get().token).toBe('access-1');
    expect(rotations).toBe(1);
  });

  it('does not retry when the 409 is really an HTML shell from a bad rewrite', async () => {
    // `NotJsonError` extends `ApiError` and carries the HTML response's status, so a 409 from a
    // misconfigured rewrite is indistinguishable from a lost race by status alone. It is a
    // broken deployment, not a race: retrying it would double the requests to a path that
    // cannot answer, and the exclusion is checked BEFORE the status for that reason.
    htmlShellStatus = 409;
    const [store, refreshOnce] = oneMount();

    expect(await refreshOnce()).toBe(false);

    expect(sends).toBe(1);
    expect(store.get().token).toBeNull();
  });

  it('does not retry a 401, and the family really is dead behind it', async () => {
    // Drives the mock's reuse arm, which nothing else reaches: a token that is neither live nor
    // recently retired is theft as far as the server is concerned, so the family dies. A 401 is
    // an answer, not a race — retrying it would be a second Postgres write for nothing.
    jar = 'captured-last-week';
    const [store, refreshOnce] = oneMount();

    expect(await refreshOnce()).toBe(false);

    expect(sends).toBe(1);
    expect(live).toBeNull();
    expect(store.get().token).toBeNull();
  });

  it('stops after that one retry, and does not keep minting attempts afterwards', async () => {
    // The retry presents a retired token again. Two ways to get here, both real: a THIRD
    // same-site realm rotating in between (one retry converges exactly two, so the second
    // loser has none left), or the loser's 409 being processed before the winner's 200 lands
    // in the jar. The cap is deliberate — every extra attempt is a Postgres write and another
    // five-minute Neon window — so the contract is that the mount stops and reports failure.
    graceRefreshesTheJar = false;
    jar = 'refresh-0';
    retired.add('refresh-0');
    const [store, refreshOnce] = oneMount();

    expect(await refreshOnce()).toBe(false);

    expect(sends).toBe(2);
    expect(store.get().token).toBeNull();

    // A second 409 IS a real failure, so the memo latches here — no further Postgres writes.
    expect(await refreshOnce()).toBe(false);
    expect(sends).toBe(2);
  });
});
