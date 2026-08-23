import { createMemoryHistory } from '@tanstack/react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The `.lazy.tsx` naming trap has no other guard: renaming `plan.lazy.tsx` to `plan.tsx` folds
 * the route into the eager router chunk, emitting no separate chunk, and `format:check`, `lint`,
 * `typecheck` and `build` all stay green — the build even rewrites the source's
 * `createLazyFileRoute` to `createFileRoute` to match the new filename, so afterwards the file
 * itself no longer hints it was ever lazy. **`test` is what catches it**, and since issue #26
 * the gate builds first, so this file reads a freshly generated tree: measured 2026-08-18, the
 * rename fails here with `expected [Function Plan] to be undefined`. (Run against a *stale*
 * committed tree the same rename fails much earlier and less usefully — 14 transform errors on
 * the unresolvable `import('./routes/_authed/plan.lazy')`. It was never silently green; it was
 * loudly wrong about the reason.)
 *
 * Asserted on router state, not on emitted chunk files: `vitest` is routinely run on its own
 * (`npm --prefix web run test`, a watch run, a clean checkout), so a test reading `dist/` would
 * either fail there or skip itself — vacuous in exactly the way this suite exists to avoid. An
 * unloaded `options.component` IS the runtime consequence of code-splitting, so this measures
 * the property that matters with no build required. Since issue #26 `check:web` does build
 * first, so the *committed* tree this file imports is a freshly generated one.
 *
 * `routeTree` is a module-level singleton and `.lazy()` mutates its route objects in
 * place, so a resolved import stays resolved for every later router built from it. Hence
 * `resetModules` + dynamic import per test: without it these assertions would silently
 * depend on which test navigated first.
 */
// Route IDS, which carry the pathless `_authed` segment; the URL paths are still /plan etc.
const LAZY = [
  '/_authed/plan',
  '/_authed/session',
  '/_authed/diary',
  '/_authed/library',
  '/_authed/profile',
  '/_authed/onboarding',
] as const;
const EAGER = ['/', '/login', '/register', '/$', '/_authed/dashboard'] as const;

async function freshRouter() {
  const { createAppRouter, createQueryClient } = await import('./router');
  const { createAuth } = await import('./auth/AuthProvider');
  return createAppRouter(createMemoryHistory({ initialEntries: ['/'] }), {
    auth: createAuth(),
    queryClient: createQueryClient(),
  });
}

async function freshRoutes() {
  return (await freshRouter()).routesById;
}

beforeEach(() => {
  vi.resetModules();
});

describe('the heavy leaves are code-split', () => {
  it.each(LAZY)('%s has not loaded its component before navigation', async (id) => {
    expect((await freshRoutes())[id].options.component).toBeUndefined();
  });

  // Without this, the check above would also pass if every route lost its component, or
  // if the assertion were pointed at something that is always undefined.
  it.each(EAGER)('%s is eager, so the check above discriminates', async (id) => {
    expect((await freshRoutes())[id].options.component).toBeTypeOf('function');
  });

  it('resolves a lazy component once navigated to, so it is split and not just missing', async () => {
    const router = await freshRouter();
    // Signed in, or the guard would redirect to /login and the chunk would never load.
    router.options.context.auth.session.set('live-token', 'user');
    expect(router.routesById['/_authed/plan'].options.component).toBeUndefined();

    await router.navigate({ to: '/plan' });

    expect(router.routesById['/_authed/plan'].options.component).toBeTypeOf('function');
  });
});
