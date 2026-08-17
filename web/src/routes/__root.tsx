import { Link, Outlet, createRootRoute } from '@tanstack/react-router';

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
function RootLayout() {
  return (
    <div className="ct-app">
      <nav className="ct-app__nav" aria-label="Main">
        <Link to="/">Dashboard</Link>
        <Link to="/plan">Plan</Link>
        <Link to="/session">Session</Link>
        <Link to="/diary">Diary</Link>
        <Link to="/profile">Profile</Link>
        <Link to="/login">Log in</Link>
      </nav>
      <main className="ct-app__main">
        <CtAppScope>
          <Outlet />
        </CtAppScope>
      </main>
    </div>
  );
}

export const Route = createRootRoute({
  component: RootLayout,
  notFoundComponent: RouteNotFound,
  errorComponent: RouteError,
});
