import { createContext, useContext, useSyncExternalStore, type ReactNode } from 'react';

import { createAuthClient, type AuthClient } from './authClient';
import { createAuthedFetch, type AuthedFetch } from './refresh';
import { createSessionStore, type Scope, type SessionStore } from './session';

/**
 * Composes the three auth pieces into the one object both the router and React read, and
 * owns the **session bootstrap**.
 *
 * ## Why the bootstrap is not automatic
 *
 * The access token lives in memory, so a page reload has none — the only way to discover an
 * existing session is to present the refresh cookie. But rotation is a Postgres write and
 * Neon bills awake time, so firing it on every load would mean every anonymous visitor who
 * reads the landing page wakes the database for five minutes. `bootstrap()` is therefore
 * called from **`_authed`'s `beforeLoad` only** — entering a guarded route is the first
 * moment the answer is worth a write.
 *
 * The visible consequence, accepted: a signed-in user who opens `/` cold sees the public
 * landing page rather than their dashboard, and is signed in again the moment they enter the
 * app. The server helps here too — `refresh_tokens` 401s on a missing cookie *before* it
 * touches the rate-limit table, so a cookie-less visitor costs no SQL at all.
 *
 * Attempted at most once per app load: a failure means "no usable cookie", which no amount
 * of re-asking will change, and re-asking on every navigation would be exactly the
 * write-per-request pattern CLAUDE.md forbids.
 */
export interface Auth {
  readonly session: SessionStore;
  readonly client: AuthClient;
  /** `apiFetch` + bearer + single-flight refresh. Use this for everything except auth. */
  readonly request: AuthedFetch;
  readonly bootstrap: () => Promise<boolean>;
}

export function createAuth(): Auth {
  const session = createSessionStore();
  const { request, reauthenticate } = createAuthedFetch(session);
  let attempted = false;
  let pending: Promise<boolean> | null = null;

  function bootstrap(): Promise<boolean> {
    if (session.get().token !== null) return Promise.resolve(true);
    if (attempted) return Promise.resolve(false);
    pending ??= reauthenticate(null).finally(() => {
      attempted = true;
      pending = null;
    });
    return pending;
  }

  return { session, client: createAuthClient(session), request, bootstrap };
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ auth, children }: { auth: Auth; children: ReactNode }) {
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

export interface AuthView extends Auth {
  readonly scope: Scope | null;
  readonly isAuthenticated: boolean;
}

/** The reactive view. `session.get` returns a stable snapshot, so this cannot loop. */
export function useAuth(): AuthView {
  const auth = useContext(AuthContext);
  if (auth === null) throw new Error('useAuth() used outside <AuthProvider>');

  const snapshot = useSyncExternalStore(auth.session.subscribe, auth.session.get);
  return { ...auth, scope: snapshot.scope, isAuthenticated: snapshot.token !== null };
}
