import { ApiError, NotJsonError, apiFetch, type ApiRequestInit } from '../api/client';
import type { TokenResponse } from './authClient';
import type { SessionStore } from './session';

/**
 * Silent refresh: serialised, lazy, and capped after a failure.
 *
 * ## Three realms, and they do NOT line up
 *
 * `inFlight` below is per **mount** (a closure local). A Web Lock is per **origin**. The refresh
 * cookie is per **site**: host-only, so it is *stored* against climb.kilianmc.com alone, but
 * `SameSite=Lax` is a site rule, so the federated mount on kilianmc.com still *sends* it. One
 * jar entry, two origins — which is both why auth works federated and why the two can collide.
 *
 * ⚠️ **So the lock does NOT cover mounts, and must never be described as if it did.** Two
 * origins get two lock managers. That arm is covered on the SERVER instead: `rotate()` answers
 * the loser of a concurrent presentation with **409** and no write, and `rotateRefreshCookie`
 * retries the POST **exactly once**, by which time the jar holds the winner's fresh token. One
 * retry converges exactly **two** realms — revisit the count if a third same-site origin ever
 * mounts this app, and note that an unusable lock makes two tabs behave as separate realms. The
 * reasoning, the three bounds and the security trade the grace window accepts all live at the
 * one place the decision is made: `server/auth/refresh.py`'s grace-window section.
 *
 * The lock is **kept** and is not redundant: the grace window would cover same-origin tabs too,
 * but at the cost of an extra POST — a Postgres write and another five minutes of Neon awake
 * time — per losing tab. It is now an optimisation over a correct fallback.
 *
 * **Tokens are deliberately NOT shared between tabs.** A `BroadcastChannel` would save that
 * write and is rejected: in the federated mount the origin is kilianmc.com, so the channel is
 * shared with the shell and every other remote, and an access token on it would give away the
 * property this design holds — the token is in no storage, no URL, no `postMessage`, no prop.
 *
 * **Lazy, and never on a timer.** Rotation is a Postgres write and Neon bills awake time, so a
 * periodic refresh would keep the compute up for a whole training session. Do not add a
 * pre-emptive timer off `expires_in`.
 *
 * ## ⚠️ TWO deadlines, and collapsing them re-creates a worse bug than the one they fix
 *
 * The obvious fix for a hanging `fetch` — one `AbortSignal.timeout(8_000)` on the POST — is
 * worse than the bug. `POST /api/auth/refresh` is a **sync `def`**, so a client disconnect
 * cannot cancel it, and it **commits the rotation before the response exists**: abort at 8 s and
 * the server still rotates at 9 s. The successor is stored only as a sha256, so **nobody holds
 * the live refresh token** — a retry inside `REPLAY_GRACE` gets a 409, and one after it trips
 * reuse detection and hard-logs the user out. So:
 *
 * | Tier | What it does | Value |
 * | --- | --- | --- |
 * | `UI_DEADLINE_MS` | stops **awaiting** (a `setTimeout` racing the await); aborts nothing | 8 s |
 * | `vercel.json` `maxDuration` | the platform kills the invocation | 20 s |
 * | `HARD_ABORT_MS` | aborts the **socket** | 30 s |
 *
 * **The gap between the two client numbers IS the fix**: the route leaves the pending component
 * while the POST runs on, commits, and its `Set-Cookie` reaches the jar — no orphan is created.
 * ⚠️ **30 s is the OUTER bound only because that `maxDuration` pin exists.** Unpinned, Fluid
 * compute's default is 300 s, which puts the abort back *inside* the server's window; deleting
 * the block re-opens the hole with a green gate. **`inFlight` MUST survive a UI-tier give-up**,
 * so a retry re-joins the same attempt instead of re-presenting the stale cookie.
 *
 * **General rule, beyond auth: a client deadline on a request with SERVER-SIDE WRITE EFFECTS
 * must be the OUTER bound, never the inner one.** Giving up on an answer is cheap and
 * reversible; cancelling a write you cannot cancel is neither.
 *
 * `unavailable()` keeps a failure distinguishable from an *answer*: a 401 means no usable cookie
 * and `/login` is right, while a timeout, a dropped connection or a 5xx means the question was
 * never answered — `mint` throws `SessionUnavailableError` rather than reporting an
 * infrastructure fault as a logged-out session. Capped at `MAX_UNANSWERED_ATTEMPTS` per
 * **mount**, not per page load: `remote.tsx` builds a fresh `createAuth()` per mount instance,
 * and without a cap every guarded navigation would start a fresh POST.
 *
 * ## The lock, concretely
 *
 * - Name-spaced `climb-trainer:auth-refresh`, because lock names are scoped to the origin and
 *   in the federated mount that origin is shared with the rest of the portfolio.
 * - **Held across the FULL round trip, `res.json()` included** — `Set-Cookie` only reaches the
 *   jar on receipt, so releasing earlier lets the next waiter send the pre-rotation cookie.
 * - Only the refresh path takes it: `POST /api/auth/demo` presents no cookie and cannot race.
 * - ⚠️ **The UI deadline does NOT release it, deliberately** — the holder's rotation may be
 *   mid-commit. The waiter's bound is `HARD_ABORT_MS` **doubled, up to 60 s**, because the 409
 *   retry builds a fresh deadline inside the same callback. The visible cost is real: `mint`
 *   clears the store synchronously before queueing, so a waiting tab shows the anonymous nav
 *   until the holder releases. If that needs improving the fix is a "checking your session" nav
 *   state, **not** releasing the lock early.
 * - ⚠️ **Presence is not usability.** In an opaque or sandboxed origin the API exists and
 *   `request()` rejects, so `withRefreshLock` tells the cases apart by whether its callback was
 *   entered, and falls back to the per-mount dedupe — never to something worse, never a throw.
 *
 * **Demo scope re-mints; it cannot refresh.** `POST /api/auth/demo` sets no cookie, so there is
 * nothing to rotate, and sending its token to `/api/auth/refresh` hits the demo write-ban and
 * 403s — a failure that looks nothing like an expiry.
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
 * **Tier 1 — stop AWAITING. Aborts nothing.** The caller gives up so `_authed`'s `beforeLoad`
 * returns and the route leaves the pending component; the POST carries on, commits, and lands its
 * `Set-Cookie` in the jar. 8 s is roughly 4× the measured cold-start TTFB of a zero-SQL endpoint.
 *
 * ⚠️ **This is not `HARD_ABORT_MS` with a shorter fuse, and the two must never be merged.** Firing
 * an abort here is the defect this replaced: the server cannot cancel a committed rotation, so an
 * 8 s abort strands the successor token where nobody holds it. See the "a hang is a failure"
 * section above — the full reasoning lives there because it is the reason this pair exists.
 */
const UI_DEADLINE_MS = 8_000;

/**
 * **Tier 2 — abort the SOCKET.** Above the pinned function ceiling
 * (`vercel.json` → `functions."api/index.py".maxDuration`, 20 s) and above `REPLAY_GRACE`'s 10 s,
 * so that reaching it means the server is genuinely gone rather than merely slow. Its job is only
 * to stop a wedged connection leaking a request slot and the origin's Web Lock.
 *
 * **Two ways to break this, both silent.** Lowering it towards `UI_DEADLINE_MS` re-creates the
 * orphaned-rotation bug — the gap between the two numbers *is* the fix. Removing the
 * `maxDuration` pin does the same from the other side: the platform default under Fluid compute
 * is 300 s, which puts this abort back *inside* the server's window. Neither shows up in the gate.
 */
const HARD_ABORT_MS = 30_000;

/**
 * How many UNANSWERED attempts a page load gets. Two, not one: decision 1 depends on a retry
 * being able to re-join or re-drive the refresh, and one attempt leaves no room for that. Not
 * more than two, because every attempt that reaches FastAPI is a `ratelimit.enforce` upsert and
 * another restarted five-minute Neon window, and a stuck backend must not be able to bill that
 * once per guarded navigation. Distinct from `exhausted` on purpose — see its comment.
 */
const MAX_UNANSWERED_ATTEMPTS = 2;

/**
 * Attaches the hard abort to one auth POST.
 *
 * Built per POST and **inside** `withRefreshLock`, not around it — a tab queued behind the lock
 * must not spend its budget waiting for a turn it has not had yet.
 *
 * No `AbortSignal.any` composition: all three call sites pass a literal `{ method: 'POST' }`, so
 * there has never been a caller signal to compose with, and an earlier revision advertised that
 * capability without having it. Add the composition back with the first real caller signal — and
 * note `AbortSignal.any` is Safari 17.4+, which is a reason to check rather than assume.
 */
function withHardAbort(init: ApiRequestInit): ApiRequestInit {
  return { ...init, signal: AbortSignal.timeout(HARD_ABORT_MS) };
}

/**
 * A refresh that could not be **answered** — as opposed to one answered "no usable cookie".
 *
 * Thrown out of `mint`, and therefore out of `bootstrap()`, so `_authed`'s `beforeLoad` fails
 * the match instead of redirecting: the route's error boundary tells the visitor the server did
 * not respond, which is true, rather than showing them a login form, which is not.
 */
export class SessionUnavailableError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = 'SessionUnavailableError';
  }
}

/**
 * Tier 1, and it is a `Promise.race` over the AWAIT — not a cancellation of anything.
 *
 * `attempt` is `inFlight`, and it is left running on purpose: the rotation completes, the cookie
 * lands, and the next caller (a retry, or another guarded navigation) re-joins this very promise
 * instead of presenting a cookie the server has already rotated. Every waiter attaches its own
 * handler here, which is also what keeps a later rejection from surfacing as an unhandled one.
 */
function raceUiDeadline(attempt: Promise<boolean>): Promise<boolean> {
  return new Promise<boolean>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(
        new SessionUnavailableError(
          'The server is taking longer than usual to answer. The check is still running — try again.',
        ),
      );
    }, UI_DEADLINE_MS);

    attempt.then(
      (held) => {
        clearTimeout(timer);
        resolve(held);
      },
      (error: Error) => {
        // Typed as `Error` for the lint rule, and forwarded rather than wrapped: `mint`'s own
        // failure is the more specific answer, so it must win over the give-up message.
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/**
 * Matched on `name` alone, structurally.
 *
 * The abort reason is constructed by the platform, and `instanceof` is the wrong tool twice over:
 * a `DOMException` from another realm is not this realm's `DOMException`, and — measured under
 * jsdom, which is what the suite runs on — it is **not an `instanceof Error` either**. Both
 * checks compile and both quietly classify every abort as a plain network failure, which is a
 * downgrade with no symptom. `TimeoutError` is what `AbortSignal.timeout` aborts with;
 * `AbortError` is every other abort, including a caller's own signal.
 */
function isAbort(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false;
  const { name } = error as { name?: unknown };
  return name === 'TimeoutError' || name === 'AbortError';
}

/**
 * `null` when the API **answered**. A 401 is the answer "no usable cookie", and so is every
 * other 4xx: the visitor is genuinely anonymous, `/login` is the right destination, and re-asking
 * cannot change it. Anything else leaves the question open, and answering an open question with
 * "no session" is what turned an infrastructure fault into a silent logout.
 *
 * **⚠️ `status >= 500` is tested BEFORE the `NotJsonError` exclusion, and the order is the whole
 * point.** An earlier revision had it the other way round, which silently sent every HTML 5xx to
 * `/login` — and HTML is exactly what a platform 5xx looks like: Vercel serves
 * `FUNCTION_INVOCATION_TIMEOUT` (504) and its mid-deploy 502 as error *pages*, so the branch
 * worked for the 5xx we can barely produce and failed for the one the platform actually generates.
 * A `NotJsonError` below 500 still counts as answered, which is the case the exclusion is for: a
 * rewrite serving the SPA shell does it with a **200**, not a 5xx, so nothing is lost.
 */
function unavailable(error: unknown): SessionUnavailableError | null {
  if (isAbort(error)) {
    return new SessionUnavailableError(
      'The server took too long to answer. Check your connection and try again.',
      { cause: error },
    );
  }
  if (!(error instanceof ApiError)) {
    return new SessionUnavailableError(
      'Could not reach the server. Check your connection and try again.',
      { cause: error },
    );
  }
  if (error.status >= 500) {
    return new SessionUnavailableError('The server is having trouble. Please try again shortly.', {
      cause: error,
    });
  }
  return null;
}

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
    return await apiFetch<TokenResponse>(REFRESH_PATH, withHardAbort({ method: 'POST' }));
  } catch (error) {
    const superseded =
      error instanceof ApiError && !(error instanceof NotJsonError) && error.status === 409;
    if (!superseded) throw error;
    return await apiFetch<TokenResponse>(REFRESH_PATH, withHardAbort({ method: 'POST' }));
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
   * while we were queued and there is nothing to do.
   *
   * Resolves to whether a token is held — `false` means the API *answered* that there is no
   * usable cookie. It **rejects** with `SessionUnavailableError` when the API never answered at
   * all; the two are different outcomes and callers must not flatten them.
   *
   * A rejection does **not** mean the attempt is over. The `UI_DEADLINE_MS` arm rejects while the
   * POST is still running, so calling this again re-joins that same attempt — which is what the
   * retry affordance does, and why it costs no extra Postgres write.
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

  /**
   * The UNANSWERED counter, and the second half of the write cap. Two memos, deliberately —
   * they do not have overlapping meaning, which is the trap CLAUDE.md warns about:
   *
   * - `exhausted` is a **latch**: the API answered "no usable cookie", and re-asking cannot
   *   change that, ever, for this page load.
   * - this is a **counter**: the API did not answer, so re-asking genuinely might work — but an
   *   unanswered attempt latches nothing, so without a cap `bootstrap()` starts a brand-new POST
   *   on every subsequent guarded navigation and a stuck backend turns one write per mount into
   *   one per navigation. **Per mount, not per page load** — `remote.tsx` builds one `Auth` per
   *   mount instance, so leaving the project in the shell and coming back re-arms this.
   *
   * The fault is kept so that the capped answer stays honest: replaying it means the visitor
   * still sees "the server did not answer" rather than being told they have no session.
   */
  let unanswered = 0;
  let unansweredFault: SessionUnavailableError | null = null;

  // Re-arm on a login, a registration, or entering the demo. A token in hand means the
  // cookie situation may have changed, so a later 401 deserves a fresh attempt.
  session.subscribe(() => {
    if (session.get().token === null) return;
    exhausted = false;
    unanswered = 0;
    unansweredFault = null;
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
        ? await apiFetch<TokenResponse>(DEMO_PATH, withHardAbort({ method: 'POST' }))
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
        // An unanswered refresh must not be reported as an anonymous visitor. Returning `false`
        // here sent `_authed`'s `beforeLoad` to /login, so a timeout or a dead API read as a
        // logout — the fault hidden behind a login form the visitor cannot get past. The
        // generation check above is what keeps this from firing on a *deliberate* session change
        // that landed mid-flight; that action wins and is never an error.
        const fault = unavailable(error);
        if (fault !== null) {
          // ⚠️ Counted ONLY when the request actually REACHED the server. The cap's whole
          // justification is that an attempt costs a `ratelimit.enforce` upsert and a restarted
          // five-minute Neon window — and a `TypeError: Failed to fetch` never opened a
          // connection, so it costs **zero writes**. That is the same reasoning `exhausted`
          // applies twelve lines up; the counter has to agree with it.
          //
          // Counting it turned the retry button into a permanent no-op: on a dead radio `fetch`
          // rejects *instantly*, so two clicks in a second spend both attempts, and after that
          // nothing but a full page load re-arms the mount — the signal coming back does not,
          // because `unanswered` is only reset when a token arrives.
          if (error instanceof ApiError || isAbort(error)) {
            unanswered += 1;
            unansweredFault = fault;
          }
          throw fault;
        }
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
    //
    // ⚠️ It is also what makes a UI-tier give-up recoverable: the give-up rejects the *await*
    // and leaves `inFlight` set, so a retry lands here and re-joins the running refresh rather
    // than sending the pre-rotation cookie a second time. Never clear `inFlight` from the
    // deadline path.
    if (inFlight !== null) return raceUiDeadline(inFlight);

    // No attempt running, and the store holds something other than the token that failed:
    // a previous waiter refreshed and finished, so there is nothing to do but retry.
    const current = session.get().token;
    if (current !== stale) return Promise.resolve(current !== null);

    if (exhausted) return Promise.resolve(false);

    // The unanswered cap. Replaying the recorded fault rather than resolving `false` is the
    // point: out of attempts is still "the server did not answer", never "you are signed out".
    if (unanswered >= MAX_UNANSWERED_ATTEMPTS && unansweredFault !== null) {
      return Promise.reject(unansweredFault);
    }

    inFlight = mint().finally(() => {
      inFlight = null;
    });
    return raceUiDeadline(inFlight);
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
