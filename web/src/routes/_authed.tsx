import { createFileRoute, redirect } from '@tanstack/react-router';

/**
 * The route guard, and the client-side mirror of `server/auth/deps.py::enforce_auth`.
 *
 * A **pathless layout** route, so every leaf that lives under `routes/_authed/` is guarded
 * by existing there — the deny-by-default shape. `publicRoutes.test.ts` closes the one hole
 * that leaves (a leaf created outside the directory) by asserting every route in the tree is
 * either explicitly public or a descendant of this one.
 *
 * Two things this must not do, both because it also runs in the federated mount:
 *
 * - **never read `window.location`.** There the history is in-memory and `window.location`
 *   is kilianmc.com's, so a guard built on it would redirect the portfolio.
 * - **never build a URL.** `location.href` here is TanStack's own path + search string, and
 *   it goes into the search param as an internal path that `internalPath` re-validates on
 *   the way out. `remoteHistory.ts` rewrites `<Link>` hrefs to absolute standalone URLs;
 *   `redirect()` does not go through `createHref`, so nothing here can leak an origin.
 */
export const Route = createFileRoute('/_authed')({
  beforeLoad: async ({ context, location }) => {
    // The one place `bootstrap()` is called: entering a guarded route is the first moment
    // an existing session is worth a refresh rotation, i.e. a Postgres write. See
    // `auth/AuthProvider.tsx` for why this is not done at mount.
    if (await context.auth.bootstrap()) return;
    throw redirect({ to: '/login', search: { redirect: location.href } });
  },
});
