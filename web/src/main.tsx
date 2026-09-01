import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserHistory } from '@tanstack/react-router';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { AuthProvider } from './auth/AuthProvider';
import { registerServiceWorker } from './pwa/register';
import { createAppContext, createAppRouter } from './router';
import './styles/global.scss';

/**
 * Standalone entry (climb.kilianmc.com): browser history, so deep links and the back
 * button work. `remote.tsx` is the federated entry and shares the route tree.
 *
 * ⚠️ This is the ONLY file that may ever register a service worker. From `remote.tsx`
 * the scope would be kilianmc.com and it would intercept the live portfolio's requests.
 * `pwa/register` may therefore be imported from here and from nowhere in the route tree,
 * which both mounts share. `remote.guard.test.tsx` asserts the negative,
 * `main.pwa.test.tsx` the positive.
 */
const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

registerServiceWorker();

// One `Auth` for the router context and for React, so the guard and the nav can never
// disagree about who is signed in. No token ever leaves this closure.
// ONE call, because the two are linked: a credential change has to reset the query cache,
// and nothing else discards one account's cached profile before the next one reads it.
const { auth, queryClient } = createAppContext();
const router = createAppRouter(createBrowserHistory(), { auth, queryClient });

createRoot(container, {
  // Without these a failed mount is a blank page and a silent console, which is the
  // hardest failure to diagnose in a client-only SPA.
  onCaughtError: (error) => console.error('[climb-trainer] error boundary caught', error),
  onUncaughtError: (error) => console.error('[climb-trainer] uncaught', error),
}).render(
  <StrictMode>
    <AuthProvider auth={auth}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthProvider>
  </StrictMode>,
);
