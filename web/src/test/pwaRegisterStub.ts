/**
 * Stub for `virtual:pwa-register`, aliased in by `vitest.config.ts`.
 *
 * `vitest.config.ts` REPLACES `vite.config.ts`, so `vite-plugin-pwa` is not running in tests and
 * the virtual module has nothing to resolve it — an import of it would fail with a resolve error,
 * which reads the same as "no service worker was registered". The whole point of
 * `remote.guard.test.tsx`'s service-worker assertion is telling those two apart, so the stub has
 * to actually call `navigator.serviceWorker.register`.
 *
 * **The deferral condition is copied from upstream verbatim, and it is the opposite of what it
 * looks like.** `workbox-window/src/Workbox.ts:113` is:
 *
 *     if (!immediate && document.readyState !== 'complete') {
 *       await new Promise((res) => window.addEventListener('load', res));
 *     }
 *
 * Under jsdom `document.readyState` is **always `'complete'`**, so the real code registers
 * SYNCHRONOUSLY during module evaluation and never waits for `load`. Reproduce the condition,
 * not a remembered summary of it — the earlier version of this stub deferred unconditionally,
 * and two tests then asserted a deferral production does not have.
 *
 * This stub is NOT the real registration path: it is a stand-in for it. What it buys is that the
 * module graph under test is the real one (`pwa/updatePrompt.ts` → `virtual:pwa-register`) and
 * that the spy sees a call. The emitted service-worker URL, scope and plugin options are
 * asserted from the config and the built output instead — see `pwaContract.test.ts` and
 * `distContract.test.ts` — because the literals below are this file's, not the app's.
 */
export interface RegisterSWOptions {
  immediate?: boolean;
  onNeedRefresh?: () => void;
  onOfflineReady?: () => void;
  onRegisteredSW?: (
    swScriptUrl: string,
    registration: ServiceWorkerRegistration | undefined,
  ) => void;
  onRegisterError?: (error: unknown) => void;
}

export function registerSW(options: RegisterSWOptions = {}): () => Promise<void> {
  const swUrl = '/sw.js';

  const register = () => {
    if ('serviceWorker' in navigator) void navigator.serviceWorker.register(swUrl, { scope: '/' });
  };

  if (!options.immediate && document.readyState !== 'complete') {
    window.addEventListener('load', register, { once: true });
  } else {
    register();
  }

  return () => Promise.resolve();
}
