import { createMemoryHistory } from '@tanstack/react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The `.lazy.tsx` naming trap has no other guard: renaming `plan.lazy.tsx` to `plan.tsx`
 * keeps `format:check`, `lint`, `typecheck`, `test` AND `build` green while silently
 * folding the route into the eager router chunk with no separate chunk emitted. A comment
 * cannot catch that; this can.
 *
 * Asserted on router state, not on emitted chunk files, because `vitest` runs BEFORE
 * `build` in `check:web` — a test reading `dist/` would either fail on a clean checkout or
 * skip itself, i.e. be vacuous in exactly the way this suite exists to avoid. An unloaded
 * `options.component` IS the runtime consequence of code-splitting, so this measures the
 * property that matters with no build required.
 *
 * `routeTree` is a module-level singleton and `.lazy()` mutates its route objects in
 * place, so a resolved import stays resolved for every later router built from it. Hence
 * `resetModules` + dynamic import per test: without it these assertions would silently
 * depend on which test navigated first.
 */
const LAZY = ['/plan', '/session', '/diary', '/profile'] as const;
const EAGER = ['/', '/login', '/$'] as const;

async function freshRoutes() {
  const { createAppRouter } = await import('./router');
  return createAppRouter(createMemoryHistory({ initialEntries: ['/'] })).routesById;
}

beforeEach(() => {
  vi.resetModules();
});

describe('the four heavy leaves are code-split', () => {
  it.each(LAZY)('%s has not loaded its component before navigation', async (id) => {
    expect((await freshRoutes())[id].options.component).toBeUndefined();
  });

  // Without this, the check above would also pass if every route lost its component, or
  // if the assertion were pointed at something that is always undefined.
  it.each(EAGER)('%s is eager, so the check above discriminates', async (id) => {
    expect((await freshRoutes())[id].options.component).toBeTypeOf('function');
  });

  it('resolves a lazy component once navigated to, so it is split and not just missing', async () => {
    const { createAppRouter } = await import('./router');
    const router = createAppRouter(createMemoryHistory({ initialEntries: ['/'] }));
    expect(router.routesById['/plan'].options.component).toBeUndefined();

    await router.navigate({ to: '/plan' });

    expect(router.routesById['/plan'].options.component).toBeTypeOf('function');
  });
});
