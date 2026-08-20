import {
  Link,
  Outlet,
  createRootRouteWithContext,
  useRouter,
  useRouterState,
} from '@tanstack/react-router';
import type { QueryClient } from '@tanstack/react-query';

import { useAuth, type Auth } from '../auth/AuthProvider';
import { CtAppScope, RouteError, RouteNotFound } from '../ui/status';
import '../styles/app.scss';

/**
 * The app shell, and the `.ct-app` element. Every style and every design token hangs off
 * it rather than `:root`/`body`, because in the federated mount this tree is injected
 * into kilianmc.com's document and anything global restyles the shell.
 *
 * A root-level error, not-found or pending render replaces this component, so the three
 * status renders re-establish `.ct-app` themselves (issue #15) — `CtAppScope` is what
 * tells them not to when they render inside the outlet instead. See `ui/status.tsx`.
 *
 * `app.scss` is imported here, not in the entries, so both mounts get it from the
 * single route tree.
 */

/**
 * Router context. `beforeLoad` runs outside React, so the guard reads auth from here rather
 * than from `useAuth()`; the entries hand the same `Auth` instance to both.
 */
export interface AppContext {
  auth: Auth;
  queryClient: QueryClient;
}

function AppNav() {
  const router = useRouter();
  const { isAuthenticated, scope, client } = useAuth();
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  /**
   * Clearing the session does NOT re-run `beforeLoad`, so without the navigation the visitor
   * would sit on a guarded route with an anonymous nav and no way back. `session.clear()`
   * runs synchronously inside `logout()` before its first `await`, so `/` already sees an
   * anonymous store by the time it evaluates its own redirect.
   */
  function logOut() {
    void client.logout();
    void router.navigate({ to: '/' });
  }

  // The landing page renders NO nav, and it is the only route that does not. Its three anonymous
  // destinations are Home (itself), Log in and Create account, and the hero already carries the
  // last two as primary actions — so the nav there was a second copy of the same page. This is
  // shared chrome, not landing chrome: every other route, signed in or out, still gets it, which
  // is why this is a route check and not a deletion.
  if (pathname === '/') return null;

  // Anonymous and authenticated navs are disjoint on purpose: linking a signed-out visitor
  // to /plan would only bounce them off the guard and back to /login.
  return (
    <nav className="ct-app__nav" aria-label="Main">
      {isAuthenticated ? (
        <>
          <Link to="/dashboard">Dashboard</Link>
          <Link to="/plan">Plan</Link>
          <Link to="/session">Session</Link>
          <Link to="/diary">Diary</Link>
          <Link to="/profile">Profile</Link>
          <button type="button" className="ct-app__button ct-app__button--quiet" onClick={logOut}>
            Log out
          </button>
          {scope === 'demo' && (
            <span className="ct-app__badge" role="status">
              Demo — read only
            </span>
          )}
        </>
      ) : (
        <>
          <Link to="/">Home</Link>
          <Link to="/login">Log in</Link>
          <Link to="/register">Create account</Link>
        </>
      )}
    </nav>
  );
}

function RootLayout() {
  return (
    <div className="ct-app">
      <AppNav />
      <main className="ct-app__main">
        <CtAppScope>
          <Outlet />
        </CtAppScope>
      </main>
    </div>
  );
}

export const Route = createRootRouteWithContext<AppContext>()({
  component: RootLayout,
  notFoundComponent: RouteNotFound,
  errorComponent: RouteError,
});
