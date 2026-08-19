import { act } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi, type MockInstance } from 'vitest';

/**
 * The positive arm of `remote.guard.test.tsx`. That file proves the federated entry registers no
 * service worker; on its own, deleting the PWA wiring entirely would leave it green. This asserts
 * the standalone entry does register — one half of "the PWA is wired". The other half is the
 * plugin configuration and the built output, which `pwaContract.test.ts` and
 * `distContract.test.ts` assert; nothing here can, because the URL the stub reports is the stub's.
 *
 * `vi.resetModules()` + a dynamic import, copied from the guard for the same reason: `main.tsx`
 * registers at MODULE SCOPE, so a static import would run before the `register` spy existed.
 *
 * No `load` dispatch, deliberately. jsdom is always `readyState: 'complete'`, so upstream's
 * `if (!immediate && document.readyState !== 'complete')` deferral does not apply and registration
 * happens during module evaluation. An earlier version of this test asserted the opposite.
 *
 * `#root` has to exist first: `main.tsx` throws without it, by design.
 */
let register: MockInstance;

beforeEach(() => {
  vi.resetModules();
  document.body.innerHTML = '<div id="root"></div>';

  register = vi.fn();
  // jsdom has no ServiceWorkerContainer at all, so it has to be supplied to be spied on.
  Object.defineProperty(navigator, 'serviceWorker', {
    value: { register, ready: Promise.resolve(), controller: null },
    configurable: true,
  });

  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Not authenticated.' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = '';
});

it('registers a service worker from the standalone entry', async () => {
  await act(async () => {
    await import('./main');
  });

  expect(register).toHaveBeenCalled();
});

it('positive control: the spy is what reports it, not the import succeeding', async () => {
  // `import('./main')` resolving proves nothing on its own — the assertion above would read the
  // same if `UpdateBar` were rendered but `registerSW` never called. So: a fresh module graph with
  // the spy in place must go from zero calls to at least one, and only because of the import.
  expect(register).not.toHaveBeenCalled();

  await act(async () => {
    await import('./main');
  });

  expect(register.mock.calls.length).toBeGreaterThan(0);
});
