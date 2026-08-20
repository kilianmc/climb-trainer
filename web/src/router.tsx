import { QueryClient } from '@tanstack/react-query';
import { createRouter, type RouterHistory } from '@tanstack/react-router';

import { routeTree } from './routeTree.gen';
import { ApiError, NotJsonError } from './api/client';
import { SessionUnavailableError } from './auth/refresh';
import type { AppContext } from './routes/__root';
import { RouteError, RouteNotFound, RoutePending } from './ui/status';

/**
 * One route tree, two histories. `main.tsx` passes a browser history, `remote.tsx` a
 * memory history — the history is the only difference between the two mounts, so
 * everything else lives here and cannot drift between them.
 *
 * `context` is required rather than defaulted: `_authed`'s `beforeLoad` runs outside React
 * and reads auth from here, so a router built without it would render an app whose guard
 * silently could not see the session. The entries pass the same `Auth` instance they give
 * `<AuthProvider>`, which is what keeps the two views of the session from disagreeing.
 */
export function createAppRouter(history: RouterHistory, context: AppContext) {
  return createRouter({
    routeTree,
    history,
    context,
    defaultPreload: 'intent',
    // Query owns staleness. Leaving this above 0 would give the router a second,
    // independent cache with its own expiry, and the two would disagree.
    defaultPreloadStaleTime: 0,
    defaultPendingMs: 300,
    defaultPendingMinMs: 500,
    // Route-level, so a navigation swaps the outlet instead of suspending the shell.
    defaultPendingComponent: RoutePending,
    defaultErrorComponent: RouteError,
    defaultNotFoundComponent: RouteNotFound,
  });
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A gym phone flaps between focused and blurred constantly (screen timeout,
        // notifications, pocket). Refetching on each one would wake Neon repeatedly.
        refetchOnWindowFocus: false,
        staleTime: 60_000,
        // Every retry is another Neon wake-up, so retry only what can actually
        // succeed on a second try: a cold-start timeout or a 5xx, never a 4xx, and
        // never a NotJsonError (that is a rewrite misconfiguration, not a blip).
        retry: (failureCount, error) => {
          // Checked FIRST, and it is not an `ApiError`, so without this line it fell through to
          // `failureCount < 2` and became the most-retried error in the app: three refresh POSTs
          // and three Postgres writes for one query, on top of `refresh.ts`'s own cap. The auth
          // layer already owns the refresh retry policy — Query must not add a second one.
          //
          // 📌 Note for whoever builds the data layer: because this is `false`, a query that hits
          // an 8 s UI-tier give-up stays errored even though the refresh usually succeeds a few
          // seconds later. Retrying here is the wrong fix (it re-drives the refresh); the right
          // one is a refetch triggered by the session store's next non-null token — one
          // `session.subscribe` in the provider that owns the queries.
          if (error instanceof SessionUnavailableError) return false;
          if (error instanceof NotJsonError) return false;
          if (error instanceof ApiError && error.status < 500) return false;
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
      },
    },
  });
}

// Gives `<Link to>` and `router.navigate` their literal path types.
declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
