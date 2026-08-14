import { QueryClient } from '@tanstack/react-query';
import { createRouter, type RouterHistory } from '@tanstack/react-router';

import { routeTree } from './routeTree.gen';
import { ApiError, NotJsonError } from './api/client';
import { RouteError, RouteNotFound, RoutePending } from './ui/status';

/**
 * One route tree, two histories. `main.tsx` passes a browser history, `remote.tsx` a
 * memory history — the history is the only difference between the two mounts, so
 * everything else lives here and cannot drift between them.
 */
export function createAppRouter(history: RouterHistory) {
  return createRouter({
    routeTree,
    history,
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
