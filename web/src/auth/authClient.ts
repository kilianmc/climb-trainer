import { apiFetch } from '../api/client';
import type { Scope, SessionStore } from './session';

/**
 * The five `/api/auth/*` credential calls, and the one rule that is easy to get wrong.
 *
 * ## Drop the token before EVERY `POST /api/auth/*`
 *
 * `server/auth/deps.py::enforce_auth` applies the demo write-ban **before** its
 * public-route check, so a `demo`-scope bearer 403s on `register`, `login`, `logout` and
 * `refresh` alike — every mutating auth route except `POST /api/auth/demo`, which is the
 * sole entry in `DEMO_WRITE_EXEMPT_ROUTES`. A visitor who explored the demo and then
 * decided to sign up would otherwise get an unexplainable "demo mode is read-only" on the
 * login form. Clearing unconditionally is one line and cannot be got wrong per-call.
 *
 * ## ⚠️ Every credential call also RESETS THE QUERY CACHE
 *
 * `onSessionReplaced` fires next to each `session.clear()` below, and the entries wire it to
 * `queryClient.clear()`. Both session transitions in this app are client-side — the nav's
 * `logOut()` navigates with the router, `/login` uses `router.history.push` — so **there is
 * no page reload to throw cached answers away**, and no query key carries a user id.
 * Measured before this existed: user A's dashboard at 86%, log out, log in as B, and B saw
 * **86%** with `GET /api/profile` called once in the whole session (the profile's `staleTime`
 * is ten minutes). The same entry feeds the wizard's and the editor's draft, so B's form came
 * prefilled with A's answers and one Continue would have written them into B's row.
 *
 * **It has to be here and not on the session store**, because the store cannot tell the two
 * apart: `refresh.ts` clears the token before EVERY refresh POST (the same "drop the token"
 * rule as above), so a store-level hook on the token going null would wipe the cache on every
 * silent rotation. These four methods are exactly the transitions where the *principal* may
 * change.
 *
 * `me` is a GET, so it is the one call here that keeps its bearer — and it deliberately
 * issues **zero SQL** on the server (it reads the token's claims, nothing else), which is
 * what keeps a session bootstrap from waking Neon. Do not add fields to it that need a
 * row; the nav shows the scope, not an email, for exactly that reason.
 */

/** `server/auth/routes.py::TokenResponse`. The refresh token is NOT in this body. */
export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  scope: Scope;
}

/** `server/auth/routes.py::MeResponse`. */
export interface MeResponse {
  user_id: number;
  scope: Scope;
}

export interface Credentials {
  email: string;
  password: string;
}

/**
 * `server/auth/routes.py::RegisterRequest`. Registration is invite-gated (issue #35), and the
 * field is snake_case because it goes on the wire as-is — the model has `extra="forbid"`, so
 * a camelCase key is a 422 rather than a silently ignored one.
 */
export interface RegisterCredentials extends Credentials {
  invite_code: string;
}

/** Properties rather than methods, for the reason given on `SessionStore`. */
export interface AuthClient {
  readonly register: (credentials: RegisterCredentials) => Promise<void>;
  readonly login: (credentials: Credentials) => Promise<void>;
  readonly demo: () => Promise<void>;
  readonly logout: () => Promise<void>;
  readonly me: () => Promise<MeResponse>;
}

export function createAuthClient(
  session: SessionStore,
  /**
   * Called immediately after the session is dropped, before the request goes out. Defaults
   * to a no-op so the auth unit tests can build a client with no cache to reset.
   */
  onSessionReplaced: () => void = () => undefined,
): AuthClient {
  const adopt = (token: TokenResponse) => {
    session.set(token.access_token, token.scope);
  };

  /** The token AND everything fetched with it. See the note above. */
  const dropSession = () => {
    session.clear();
    onSessionReplaced();
  };

  return {
    register: async (credentials) => {
      dropSession();
      adopt(await apiFetch<TokenResponse>('/api/auth/register', { json: credentials }));
    },

    login: async (credentials) => {
      dropSession();
      adopt(await apiFetch<TokenResponse>('/api/auth/login', { json: credentials }));
    },

    demo: async () => {
      dropSession();
      // No body param on the server, so no `content-type` and nothing to encode.
      adopt(await apiFetch<TokenResponse>('/api/auth/demo', { method: 'POST' }));
    },

    logout: async () => {
      // Cleared first, so the UI is anonymous immediately and the request carries no
      // bearer. The endpoint is idempotent and never errors, and a demo session has no
      // refresh family to revoke — for it this call is a formality, not a failure.
      dropSession();
      await apiFetch<{ status: 'ok' }>('/api/auth/logout', { method: 'POST' });
    },

    me: () => apiFetch<MeResponse>('/api/auth/me', { headers: session.header() }),
  };
}
