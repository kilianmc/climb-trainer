import { registerSW } from 'virtual:pwa-register';

/**
 * Service worker registration, and the store behind the update prompt.
 *
 * ⚠️ This module — and anything that imports it — must stay reachable ONLY from `main.tsx`.
 * `remote.tsx` shares the route tree, so a component here rendered from `__root.tsx` or any route
 * would register a service worker scoped to **kilianmc.com** and start intercepting the live
 * portfolio's requests. `remote.guard.test.tsx` is the detector; `main.pwa.test.tsx` is its
 * positive arm; `pwaContract.test.ts` asserts the plugin options this depends on.
 *
 * An external store rather than React state because registration happens once, at module scope,
 * before any component mounts — `useSyncExternalStore` is the supported way to read a value that
 * already existed.
 */
let waiting = false;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

/**
 * Sampled at module scope, which is the same controller state `workbox-window` samples one tick
 * later as its `isUpdate` flag. See `applyUpdate` for why it has to be captured at all.
 */
const wasControlled = 'serviceWorker' in navigator && navigator.serviceWorker.controller !== null;

const applyUpdate = registerSW({
  onNeedRefresh() {
    waiting = true;
    emit();
  },
});

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSnapshot(): boolean {
  return waiting;
}

/**
 * Activates the waiting worker, then makes sure the page actually reloads.
 *
 * ⚠️ The explicit reload is not belt-and-braces. `vite-plugin-pwa`'s prompt-mode registration
 * reloads from `wb.addEventListener('controlling', …)` **gated on `event.isUpdate`**, and
 * `isUpdate` is `Boolean(navigator.serviceWorker.controller)` sampled when it registered
 * (`client/build/register.ts`, and `Workbox.ts`'s `this.mn`). On an UNCONTROLLED client — a first
 * visit, or any hard reload, both of which can still surface the prompt — that is `false`, so
 * `SKIP_WAITING` is sent, the new worker activates, and **nothing reloads**: `waiting` stays true
 * and a second tap does nothing at all. Without a controller there is also no `controllerchange`
 * to wait for, since prompt mode does not call `clients.claim()`.
 */
export function updateSW(): Promise<void> {
  return applyUpdate(true).then(() => {
    if (!wasControlled) window.location.reload();
  });
}

/**
 * Closes the prompt without updating. Required, not a nicety: the bar is `position: fixed` at the
 * bottom of the viewport, and until this existed a visitor who saw it lost the bottom-anchored
 * primary action — measured, the bar covered 32.5px of the 44px "Open the demo" button — for the
 * rest of the session, with no way back. An update is never urgent enough to be unclosable.
 */
export function dismissUpdate(): void {
  waiting = false;
  emit();
}
