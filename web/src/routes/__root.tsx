import { Link, Outlet, createRootRoute } from '@tanstack/react-router';

import { RouteError, RouteNotFound } from '../ui/status';
import '../styles/app.scss';

/**
 * The app shell, and the ONE `.ct-app` element. Every style and every design token
 * hangs off it rather than `:root`/`body`, because in the federated mount this tree
 * is injected into kilianmc.com's document and anything global restyles the shell.
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
        <Outlet />
      </main>
    </div>
  );
}

export const Route = createRootRoute({
  component: RootLayout,
  notFoundComponent: RouteNotFound,
  errorComponent: RouteError,
});
