import { createMemoryHistory } from '@tanstack/react-router';
import { describe, expect, it } from 'vitest';

import { createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';

/**
 * The client mirror of `tests/test_auth_routes_enumerated.py`, and for the same reason: the
 * `_authed` directory convention protects a leaf by where its file sits, so the failure mode
 * is **omission** — a new route created next to `login.tsx` instead of inside `_authed/` is
 * silently public, and nothing else in the gate notices.
 *
 * So every route in the generated tree must be either explicitly listed below or a descendant
 * of `_authed`. Making a route public stays a visible line in a diff, exactly as
 * `PUBLIC_ROUTES` is on the server.
 */
const PUBLIC_ROUTE_IDS: ReadonlySet<string> = new Set([
  '__root__',
  // The public landing page. It redirects an already-signed-in visitor to /dashboard, but
  // deliberately does not attempt a refresh — see routes/index.tsx.
  '/',
  // The catch-all. An unmatched URL must render "not found", not bounce to a login form.
  '/$',
  '/login',
  '/register',
]);

const GUARD_ID = '/_authed';

function freshRouter() {
  return createAppRouter(createMemoryHistory({ initialEntries: ['/'] }), {
    auth: createAuth(),
    queryClient: createQueryClient(),
  });
}

function routeIds(): string[] {
  return Object.keys(freshRouter().routesById);
}

function isGuarded(id: string): boolean {
  return id === GUARD_ID || id.startsWith(`${GUARD_ID}/`);
}

describe('every route is public on purpose or guarded', () => {
  it('has no route that is neither listed nor under the guard', () => {
    const unaccounted = routeIds().filter((id) => !PUBLIC_ROUTE_IDS.has(id) && !isGuarded(id));

    expect(unaccounted).toEqual([]);
  });

  // Without this the assertion above would also pass on a tree with no guarded routes at all,
  // or with a `_authed` route that had lost its `beforeLoad`.
  it('positive control: the guard exists, carries a beforeLoad, and has leaves under it', () => {
    const router = freshRouter();
    const ids = Object.keys(router.routesById);

    expect(ids).toContain(GUARD_ID);
    // The directory convention is worth nothing if the layout route stops guarding.
    expect(router.routesById[GUARD_ID].options.beforeLoad).toBeTypeOf('function');
    expect(ids.filter((id) => id.startsWith(`${GUARD_ID}/`)).sort()).toEqual([
      '/_authed/dashboard',
      '/_authed/diary',
      '/_authed/plan',
      '/_authed/profile',
      '/_authed/session',
    ]);
  });

  it('does not list a route as public that no longer exists', () => {
    const ids = new Set(routeIds());
    const stale = [...PUBLIC_ROUTE_IDS].filter((id) => !ids.has(id));

    expect(stale).toEqual([]);
  });
});
