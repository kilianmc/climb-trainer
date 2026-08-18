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

/** Properties rather than methods, for the reason given on `SessionStore`. */
export interface AuthClient {
  readonly register: (credentials: Credentials) => Promise<void>;
  readonly login: (credentials: Credentials) => Promise<void>;
  readonly demo: () => Promise<void>;
  readonly logout: () => Promise<void>;
  readonly me: () => Promise<MeResponse>;
}

export function createAuthClient(session: SessionStore): AuthClient {
  const adopt = (token: TokenResponse) => {
    session.set(token.access_token, token.scope);
  };

  return {
    register: async (credentials) => {
      session.clear();
      adopt(await apiFetch<TokenResponse>('/api/auth/register', { json: credentials }));
    },

    login: async (credentials) => {
      session.clear();
      adopt(await apiFetch<TokenResponse>('/api/auth/login', { json: credentials }));
    },

    demo: async () => {
      session.clear();
      // No body param on the server, so no `content-type` and nothing to encode.
      adopt(await apiFetch<TokenResponse>('/api/auth/demo', { method: 'POST' }));
    },

    logout: async () => {
      // Cleared first, so the UI is anonymous immediately and the request carries no
      // bearer. The endpoint is idempotent and never errors, and a demo session has no
      // refresh family to revoke — for it this call is a formality, not a failure.
      session.clear();
      await apiFetch<{ status: 'ok' }>('/api/auth/logout', { method: 'POST' });
    },

    me: () => apiFetch<MeResponse>('/api/auth/me', { headers: session.header() }),
  };
}
