import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { useState } from 'react';

import { createAppRouter, createQueryClient } from './router';
import { createRemoteHistory } from './remoteHistory';

/**
 * Federated entry — what `climbTrainer/App` resolves to. The shell mounts it with
 * `React.lazy`, so this must stay a default-exported component.
 *
 * It runs on the kilianmc.com origin, which is the whole reason for the constraints:
 *
 * - **memory history**, so the router never touches the shell's `window.location`,
 *   with absolute standalone hrefs so a cmd-click leaves for climb.kilianmc.com rather
 *   than a 404 on the portfolio (see `remoteHistory.ts`);
 * - **no service worker** (its scope would be kilianmc.com — see `main.tsx`);
 * - **no un-namespaced `localStorage`** — that store is the portfolio's.
 *
 * `remote.guard.test.tsx` asserts all three at runtime. No `StrictMode` here either:
 * the host owns that decision, and adding it would double-render inside the shell.
 */
export default function ClimbTrainerApp() {
  // Per mount instance, not per module: a module-level router would keep its location
  // and cache across shell navigations away from and back to this project.
  const [mount] = useState(() => ({
    router: createAppRouter(createRemoteHistory()),
    queryClient: createQueryClient(),
  }));

  return (
    <QueryClientProvider client={mount.queryClient}>
      <RouterProvider router={mount.router} />
    </QueryClientProvider>
  );
}
