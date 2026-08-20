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
 * Attempted at most once per app load: an *answered* failure means "no usable cookie", which no
 * amount of re-asking will change, and re-asking on every navigation would be exactly the
 * write-per-request pattern CLAUDE.md forbids.
 *
 * **An unanswered one is a different thing and does not resolve `false`.** A timeout, a dropped
 * connection or a 5xx rejects with `SessionUnavailableError` — "we could not check" is not "you
 * are signed out", and collapsing the two put an infrastructure fault in front of the visitor as
 * a login screen. See the "a hang is a failure" section in `refresh.ts`.
 *
 * **A rejection can also mean "not yet".** The 8 s tier gives up *awaiting* without cancelling
 * the refresh, so calling `bootstrap()` again re-joins the attempt still in the air rather than
 * starting a second one — which is exactly what the retry button on the error boundary does. The
 * "at most once" budget is therefore about POSTs, not about calls.
 */
export interface Auth {
  readonly session: SessionStore;
  readonly client: AuthClient;
  /** `apiFetch` + bearer + single-flight refresh. Use this for everything except auth. */
  readonly request: AuthedFetch;
  /** Resolves to whether a session is held; rejects with `SessionUnavailableError` if unknown. */
  readonly bootstrap: () => Promise<boolean>;
}

export function createAuth(): Auth {
  const session = createSessionStore();
  const { request, reauthenticate } = createAuthedFetch(session);

  /**
   * `reauthenticate` owns both caps now — the in-flight join and the post-failure memo — so
   * this is a thin wrapper rather than a second bookkeeping site. It used to keep its own
   * `attempted`/`pending` pair, which meant the "at most once" rule held for the bootstrap and
   * silently did not hold for `request()`: two memos with overlapping meaning, one of them
   * missing. See the `exhausted` comment in `refresh.ts`.
   */
  function bootstrap(): Promise<boolean> {
    if (session.get().token !== null) return Promise.resolve(true);
    return reauthenticate(null);
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
