import { ApiError, NotJsonError, apiFetch, type ApiRequestInit } from '../api/client';
import type { TokenResponse } from './authClient';
import type { SessionStore } from './session';

/**
 * Silent refresh: serialised, lazy, and capped after a failure.
 *
 * ## Why the refresh has to be serialised, and where serialising is not enough
 *
 * `server/auth/refresh.py::rotate` reads its row `FOR UPDATE` and treats a second
 * presentation of an already-rotated token as **theft**, revoking the whole family — outside the
 * 10-second grace window described in point 3 below. Note what the row lock does and does not
 * do: it **serialises** two presentations of the same token, it does not deduplicate them. So
 * the loser is *guaranteed* — not merely likely — to re-read the row after the winner commits
 * and see `rotated_at` set. Before the grace window that meant the family was revoked, killing
 * the winner's brand-new token too, and both callers ended up logged out with no way to refresh.
 *
 * Three realms are in play and **they do not line up**, which is the whole shape of this
 * problem. Getting them the wrong way round is how the guarantee gets overstated:
 *
 * | Thing                | Realm                                            |
 * | -------------------- | ------------------------------------------------ |
 * | `inFlight` below     | one **mount** (a closure local)                  |
 * | a Web Lock           | one **origin** (partitioned by storage key)      |
 * | the refresh cookie   | one **site** — one jar entry, both origins       |
 *
 * That last row needs one clarification, because "the profile" overstates it: the cookie is
 * **host-only** (no `Domain` attribute — see `server/auth/cookies.py`), so it is *stored*
 * against climb.kilianmc.com alone. But `SameSite=Lax` is a **site** rule, not an origin rule,
 * so a request from the federated mount on kilianmc.com still *sends* it. One entry in the jar,
 * reachable from both origins, which is the whole reason the two can collide.
 *
 * So there are three mechanisms, one per realm:
 *
 * 1. **Within a mount** — `inFlight`, so N concurrent 401s share one attempt.
 * 2. **Across tabs of ONE origin** — the **Web Locks API**, because two tabs on
 *    climb.kilianmc.com have two independent `inFlight` closures and one shared cookie.
 * 3. **Across the two ORIGINS** — a **server-side grace window**, not anything in this file.
 *    This is what issue #27 fixed. A standalone tab plus the climb-trainer card open on the
 *    portfolio is the arm no lock can reach, so both mounts present the same pre-rotation
 *    token; `rotate()` now answers the loser with **409** and writes nothing, instead of
 *    reading the replay as theft and revoking the family. This client retries the POST
 *    **exactly once** (see `rotateRefreshCookie`), and the browser attaches the token the
 *    winner just rotated into the shared jar, so the retry is an ordinary legitimate rotation.
 *    The server sees presentations, not origins, which is why one mechanism there covers all
 *    three realms where the lock covers one. **No migration was needed** — `rotated_at` was
 *    already on the row, and nothing about the successor is handed back.
 *
 * **⚠️ Point 3 is a strong mitigation, not a guarantee. Three bounds, none of them a reason to
 * loosen anything — the full reasoning is in `server/auth/refresh.py`'s grace-window section:**
 *
 * - **The retry is not certain to find the winner's cookie.** The winner's response is
 *   dispatched after its `commit()`, which is also what releases the row lock the loser is
 *   waiting on; the loser then pays its own commit round trip before answering. So the winner
 *   leads by roughly one database round trip — a real margin, but the two responses travel
 *   independently. If the 409 is processed first, the retry re-presents the same token, gets a
 *   second 409, and `exhausted` latches: **that mount cannot refresh for the rest of the page
 *   load.** The family survives and a reload recovers, so it degrades to "sign in again", never
 *   to a revoked session.
 * - **One retry converges exactly TWO realms.** Three same-site origins presenting at once
 *   means two losers retrying against the same fresh token, and the second loser has no retry
 *   left. Today there are two origins (`climb.kilianmc.com` and `kilianmc.com`), so the cap is
 *   right and it saves a Postgres write per attempt. **Revisit the count if a third same-site
 *   origin ever mounts this app** — and note the unusable-lock fallback can make two *tabs*
 *   behave as separate realms, so "two" is about realms, not about origins.
 * - **Issue #27 is narrowed, not eliminated.** A loser whose request takes longer than the
 *   server's 10-second window to travel from reading the cookie to reaching `rotate()` — a
 *   stalled radio, a queued cold start — still lands on reuse detection and still revokes the
 *   family. That is the original bug, on a much smaller target.
 *
 * ⚠️ **The lock itself does NOT cover mounts, and must not be described as if it did**, which
 * is the whole reason point 3 exists. The standalone app is `https://climb.kilianmc.com` and the
 * federated mount runs on `https://kilianmc.com`, so they get two *different* lock managers —
 * `climb-trainer:auth-refresh` in one excludes nothing in the other — while sharing **one**
 * refresh cookie. And that cookie sharing is not incidental: same registrable domain, therefore
 * same-*site*, therefore `SameSite=Lax` sends it, which is the entire reason auth works in the
 * federated mount (see `remote.tsx`). Exactly the same origin asymmetry that rules out
 * `BroadcastChannel` below.
 *
 * **The lock is kept, and it is not redundant.** The grace window would cover the same-origin
 * tabs too, but at the price of an extra POST and therefore an extra Postgres write and another
 * five minutes of Neon awake time per losing tab. Serialising avoids that. So the lock is now an
 * optimisation over a correct fallback rather than the correctness mechanism it used to be — and
 * where the lock does apply the reason it works is unchanged: both tabs only race because they
 * read the same **pre-rotation** cookie, so the waiter wakes, sends the *already-rotated* cookie
 * and rotates legitimately, needing nothing from the server.
 *
 * **The trade the grace window makes is real, and it is a loss.** Inside the window a replayed
 * token no longer revokes its family, so a genuine theft landing there goes undetected. The
 * replayer gains no token (the 409 carries none, and the successor is only reachable by whoever
 * already holds the shared cookie jar). Full reasoning lives at the one place the decision is
 * made: `server/auth/refresh.py`, the grace-window section.
 *
 * **Tokens are deliberately NOT shared between tabs.** A `BroadcastChannel` would be the
 * obvious way to save that write, and it is rejected: in the federated mount the origin is
 * kilianmc.com, so the channel is shared with the shell and every other remote on the
 * portfolio, and putting an access token on it would give away the property this design
 * exists to hold — the token is in no storage, no URL, no `postMessage` and no React prop.
 *
 * ## Lazy, and never on a timer
 *
 * Rotation is a Postgres write, and Neon bills awake time. A periodic refresh would keep
 * the compute up for the length of a whole training session for no benefit, which CLAUDE.md
 * records as the largest avoidable consumer of the budget. Access tokens live 3 h precisely
 * so that a 401 is rare. **Do not add a pre-emptive timer off `expires_in`.**
 *
 * ## The lock, concretely
 *
 * - **Name-spaced `climb-trainer:auth-refresh`.** Lock names are scoped to the ORIGIN, which
 *   in the federated mount is kilianmc.com — shared with the rest of the portfolio, hence the
 *   prefix, and *not* shared with the standalone app, which is why that arm needed the server.
 * - **Held across the FULL round trip, response body included.** `Set-Cookie` is only in the
 *   jar once the response has been received, so releasing before `res.json()` resolves would
 *   let the next waiter send the pre-rotation cookie and reintroduce the exact race.
 * - **Only the refresh path takes it.** `POST /api/auth/demo` presents no cookie and cannot
 *   race, so serialising demo mints would cost latency for nothing.
 * - **Released on rejection and on tab close**, by the API's own contract: the lock is held
 *   for exactly as long as the callback's promise is pending, and a closed tab releases it.
 *   The one residual case is a refresh that *hangs* rather than failing — it holds the lock
 *   until `fetch` settles or the tab goes away, which is the correct trade against the race.
 * - **⚠️ Fallback where the lock is unavailable** (jsdom; an opaque or sandboxed origin, where
 *   the property exists but `request()` rejects): behave exactly as before — the per-mount
 *   `inFlight` dedupe still holds, and the same-origin cross-tab guarantee is simply not
 *   available. It degrades to the previous behaviour rather than throwing, and never to
 *   something worse. Presence alone cannot tell you the lock is *usable*, so `withRefreshLock`
 *   detects the difference by observing whether its callback ever ran.
 *
 * ## Demo scope re-mints; it cannot refresh
 *
 * `POST /api/auth/demo` sets no cookie (it takes no `Response` and issues zero SQL), so a
 * demo session has nothing to rotate. Sending its 1 h token to `/api/auth/refresh` would
 * also hit the demo write-ban and 403 — a failure that looks nothing like an expiry. Demo
 * scope therefore re-mints from `/api/auth/demo`.
 */

/**
 * A 401 from one of these is an *answer*, not an expiry: wrong password, no cookie, a
 * revoked family. Refreshing would be nonsense, and refreshing `/api/auth/refresh` itself
 * would recurse. `/api/auth/me` is deliberately absent — it is a normal protected read.
 */
const CREDENTIAL_PATHS: ReadonlySet<string> = new Set([
  '/api/auth/register',
  '/api/auth/login',
  '/api/auth/refresh',
  '/api/auth/demo',
  '/api/auth/logout',
]);

const REFRESH_PATH = '/api/auth/refresh';
const DEMO_PATH = '/api/auth/demo';

/** Origin-scoped, so it is namespaced: the federated mount shares kilianmc.com. */
const REFRESH_LOCK = 'climb-trainer:auth-refresh';

/**
 * The lock manager, if there is a usable-looking one. A shape check rather than `'locks' in
 * navigator`: the DOM lib types `navigator.locks` as non-optional, so presence proves nothing,
 * and a property that is not a callable `request` is not a lock manager.
 */
function lockManager(): LockManager | null {
  const candidate: unknown = 'locks' in navigator ? navigator.locks : undefined;
  if (typeof candidate !== 'object' || candidate === null) return null;
  return typeof (candidate as LockManager).request === 'function'
    ? (candidate as LockManager)
    : null;
}

/**
 * Runs `attempt` while holding the same-origin refresh lock, falling back to running it
 * unlocked where no lock is available.
 *
 * **Presence is not usability and cannot be made into it** — in an opaque or sandboxed origin
 * the property exists, looks right, and `request()` rejects. There is no feature test for that,
 * so this does not pretend to have one: it passes a callback that records having been entered,
 * and on a rejection uses `started` to tell the two cases apart. If the callback never ran,
 * nothing was sent, the lock manager itself refused, and the honest response is to degrade to
 * the unlocked path — not to report the page as logged out, which is what attributing an
 * infrastructure refusal to `mint`'s failure branch would do.
 */
async function withRefreshLock<T>(attempt: () => Promise<T>): Promise<T> {
  const locks = lockManager();
  if (locks === null) return attempt();

  let started = false;
  try {
    // The lock is held for exactly as long as this promise is pending — so the whole round
    // trip, `res.json()` included, which is what puts the rotated Set-Cookie in the jar before
    // the next waiter sends. Rejection and tab-close both release it.
    return await locks.request(REFRESH_LOCK, () => {
      started = true;
      return attempt();
    });
  } catch (error) {
    if (started) throw error;
    return attempt();
  }
}

/**
 * One `POST /api/auth/refresh`, plus the single retry a **409** asks for.
 *
 * A 409 says another mount rotated the shared cookie a moment ago and the server declined to
 * read this presentation as theft (`server/auth/refresh.py`, grace window). Nothing was written
 * and no token came back: the jar is simply newer than what this request sent, so sending again
 * rotates the *current* token, which is legitimate. The browser re-reads the jar for us.
 *
 * **Placement inside `mint`'s attempt matters, and two of the three reasons are load-bearing
 * while the third is not — worth separating, because an overstated reason is how the weak one
 * gets deleted later.**
 *
 * 1. **`exhausted` can only ever see the FINAL failure.** Load-bearing. A 409 is an `ApiError`,
 *    so handling it outside `mint` lets the intermediate one latch the memo and disable refresh
 *    for the rest of the page load — a race that was already handled, reported as a logout.
 * 2. **`session.generation()` is compared against the final result only.** Load-bearing. A
 *    logout landing between the 409 and the retry must still win.
 * 3. **The Web Lock, where there is one, stays held across both round trips.** This is an
 *    ordering nicety, NOT correctness: a variant taking the lock per POST also converges, with
 *    the same number of writes, because a 409 implies the jar was already refreshed. What it
 *    changes is *which* mount owns *which* rotation — the mount that took the lock first no
 *    longer gets the first rotation. `crossTabRefresh.test.ts` asserts that ownership, so the
 *    claim has a guard rather than a comment; do not upgrade the wording past what it proves.
 *
 * **Exactly one retry** — a second 409 is a real failure, not a race worth losing twice.
 * `NotJsonError` is excluded first because it is an `ApiError` *subclass* carrying the HTML
 * response's status: a rewrite serving the SPA shell with a 409 is a broken deployment, not a
 * lost rotation.
 */
async function rotateRefreshCookie(): Promise<TokenResponse> {
  try {
    return await apiFetch<TokenResponse>(REFRESH_PATH, { method: 'POST' });
  } catch (error) {
    const superseded =
      error instanceof ApiError && !(error instanceof NotJsonError) && error.status === 409;
    if (!superseded) throw error;
    return await apiFetch<TokenResponse>(REFRESH_PATH, { method: 'POST' });
  }
}

export interface AuthedFetch {
  /** `apiFetch` plus the bearer, one silent refresh on 401, and exactly one retry. */
  <T>(path: string, init?: ApiRequestInit): Promise<T>;
}

export interface Reauthenticator {
  readonly request: AuthedFetch;
  /**
   * Obtain a token. `stale` is the token whose failure prompted this, or `null` for a cold
   * bootstrap; if the store already holds something newer, a concurrent waiter refreshed
   * while we were queued and there is nothing to do. Resolves to whether a token is held.
   */
  readonly reauthenticate: (stale: string | null) => Promise<boolean>;
}

export function createAuthedFetch(session: SessionStore): Reauthenticator {
  let inFlight: Promise<boolean> | null = null;

  /**
   * Set once a refresh has genuinely failed, cleared the moment a token arrives by any other
   * route. **This is not an optimisation.** `bootstrap()` used to carry its own `attempted`
   * cap while `request()` carried none, so once the session was anonymous `stale` and
   * `current` were both `null`, the early-out never fired, and *every* subsequent 401 minted
   * another attempt. Each one is a `ratelimit.enforce` upsert whenever a cookie is present but
   * invalid — one Postgres write and one restarted five-minute Neon window per 401, burning
   * the 30/hour `REFRESH` bucket until the user 429s. One memo, shared by both entry points.
   */
  let exhausted = false;

  // Re-arm on a login, a registration, or entering the demo. A token in hand means the
  // cookie situation may have changed, so a later 401 deserves a fresh attempt.
  session.subscribe(() => {
    if (session.get().token !== null) exhausted = false;
  });

  async function mint(): Promise<boolean> {
    const demo = session.get().scope === 'demo';
    // Read the scope first, then drop the token: see the "drop before every POST" rule in
    // `authClient.ts`. A dead token has no value to preserve, and the cookie is what
    // authenticates a refresh.
    session.clear();
    // Captured AFTER our own clear, so this attempt does not invalidate itself.
    const epoch = session.generation();

    try {
      const token = demo
        ? await apiFetch<TokenResponse>(DEMO_PATH, { method: 'POST' })
        : await withRefreshLock(rotateRefreshCookie);

      if (session.generation() === epoch) {
        session.set(token.access_token, token.scope);
        return true;
      }
    } catch (error) {
      if (session.generation() === epoch) {
        session.clear();
        // Latch ONLY when the API itself answered. `exhausted` exists to stop an unbounded
        // Postgres write per 401, and a write can only have happened if the request reached
        // FastAPI's rate limiter — which needs a real JSON response. A dropped connection or an
        // HTML shell from a bad rewrite never got there, so there is nothing to protect against
        // and latching would report an infrastructure fault as a logged-out session, disabling
        // refresh for the rest of the page load over a blip.
        if (error instanceof ApiError && !(error instanceof NotJsonError)) exhausted = true;
      }
    }

    // Abandoned mid-flight: a logout, a login, or an "explore the demo" click landed while we
    // were in the air. The deliberate action wins — never write over it, and never mark the
    // refresh exhausted on its account. Report whether the app now holds a usable token, so a
    // caller whose request 401ed still retries when a login supplied one.
    return session.get().token !== null;
  }

  function reauthenticate(stale: string | null): Promise<boolean> {
    // Joining an in-flight attempt is checked FIRST, before the staleness comparison. `mint`
    // clears the store synchronously before it awaits, so a second waiter arriving mid-flight
    // would otherwise see `token === null`, conclude someone else had already finished, and
    // give up — logging the user out on exactly the concurrent-401 case this exists for.
    if (inFlight !== null) return inFlight;

    // No attempt running, and the store holds something other than the token that failed:
    // a previous waiter refreshed and finished, so there is nothing to do but retry.
    const current = session.get().token;
    if (current !== stale) return Promise.resolve(current !== null);

    if (exhausted) return Promise.resolve(false);

    inFlight = mint().finally(() => {
      inFlight = null;
    });
    return inFlight;
  }

  function send<T>(path: string, init: ApiRequestInit | undefined, token: string | null) {
    const headers: Record<string, string> = { ...init?.headers };
    // The demo-drop rule, enforced STRUCTURALLY rather than by call-site discipline: the
    // write-ban 403s a demo bearer on every mutating /api/auth/* route, so this function must
    // be unable to attach one. `authClient` clears the store before each of those POSTs, which
    // is correct but is a property of its call sites; this is a property of the code path.
    // `/api/auth/me` is deliberately not in the set — a GET legitimately keeps its bearer.
    if (token !== null && !CREDENTIAL_PATHS.has(path)) headers.authorization = `Bearer ${token}`;
    return apiFetch<T>(path, { ...init, headers });
  }

  async function request<T>(path: string, init?: ApiRequestInit): Promise<T> {
    const stale = session.get().token;
    try {
      return await send<T>(path, init, stale);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      if (CREDENTIAL_PATHS.has(path)) throw error;
      if (!(await reauthenticate(stale))) throw error;
      // Exactly one retry. A second 401 is a real 401.
      return await send<T>(path, init, session.get().token);
    }
  }

  return { request, reauthenticate };
}
