import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserHistory } from '@tanstack/react-router';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';
import { UpdateBar } from './ui/UpdateBar';
import './styles/global.scss';

/**
 * Standalone entry (climb.kilianmc.com): browser history, so deep links and the back
 * button work. `remote.tsx` is the federated entry and shares the route tree.
 *
 * ⚠️ This is the ONLY file that may ever register a service worker. From `remote.tsx`
 * the scope would be kilianmc.com and it would intercept the live portfolio's requests.
 * `<UpdateBar>` is what pulls in `pwa/updatePrompt`, which registers it — so that component
 * may be rendered from here and from nowhere in the route tree, which both mounts share.
 * `remote.guard.test.tsx` asserts the negative, `main.pwa.test.tsx` the positive.
 *
 * It renders as a SIBLING of the router, outside `.ct-app`, hence the token mixin in
 * `styles/_tokens.scss` rather than tokens declared on that element.
 */
const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

// One `Auth` for the router context and for React, so the guard and the nav can never
// disagree about who is signed in. No token ever leaves this closure.
const auth = createAuth();
const queryClient = createQueryClient();
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
        <UpdateBar />
      </QueryClientProvider>
    </AuthProvider>
  </StrictMode>,
);
