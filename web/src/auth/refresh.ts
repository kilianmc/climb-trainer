import { ApiError, apiFetch, type ApiRequestInit } from '../api/client';
import type { TokenResponse } from './authClient';
import type { SessionStore } from './session';

/**
 * Silent refresh, single-flight, lazy.
 *
 * ## Why single-flight is a correctness requirement, not an optimisation
 *
 * `server/auth/refresh.py::rotate` reads its row `FOR UPDATE` and treats a second
 * presentation of an already-rotated token as **theft**, revoking the whole family. So two
 * concurrent refreshes triggered by two concurrent 401s do not merely waste a request —
 * the loser presents a token the winner already consumed and the user is logged out of
 * every device. One in-flight attempt, shared by every waiter.
 *
 * ## Lazy, and never on a timer
 *
 * Rotation is a Postgres write, and Neon bills awake time. A periodic refresh would keep
 * the compute up for the length of a whole training session for no benefit, which CLAUDE.md
 * records as the largest avoidable consumer of the budget. Access tokens live 3 h precisely
 * so that a 401 is rare. **Do not add a pre-emptive timer off `expires_in`.**
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

  async function mint(): Promise<boolean> {
    const path = session.get().scope === 'demo' ? '/api/auth/demo' : '/api/auth/refresh';
    // Read the scope first, then drop the token: see the "drop before every POST" rule in
    // `authClient.ts`. A dead token has no value to preserve, and the cookie is what
    // authenticates a refresh.
    session.clear();
    try {
      const token = await apiFetch<TokenResponse>(path, { method: 'POST' });
      session.set(token.access_token, token.scope);
      return true;
    } catch {
      session.clear();
      return false;
    }
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

    inFlight = mint().finally(() => {
      inFlight = null;
    });
    return inFlight;
  }

  function send<T>(path: string, init: ApiRequestInit | undefined, token: string | null) {
    const headers: Record<string, string> = { ...init?.headers };
    if (token !== null) headers.authorization = `Bearer ${token}`;
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
