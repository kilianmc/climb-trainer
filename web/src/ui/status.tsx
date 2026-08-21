import { useRouter } from '@tanstack/react-router';
import { createContext, useContext, type ReactNode } from 'react';

/**
 * The three route-level status renders. Shared because the root route and the router
 * defaults both need them: the router defaults give every leaf its own boundary (an
 * error in `/plan` keeps the nav usable), and the root route is the backstop for
 * anything that fails above the outlet.
 *
 * All three can render at ROOT level, where they REPLACE `RootLayout` and take the
 * `.ct-app` element with it: a root error, a root not-found, a pending root match, and
 * the router's two root-level Suspense fallbacks — `Matches` and `MatchView` both build
 * theirs from the ROOT route's `pendingComponent ?? defaultPendingComponent`. Unscoped,
 * that markup lands in the shell's document with no styles and no tokens, because every
 * rule in `app.scss` is `.ct-app`-prefixed (issue #15).
 *
 * So each render re-establishes `.ct-app`, but only when it is not already there:
 * that element carries padding, a max width and a background, so a nested one would
 * inset the layout twice.
 */
const CtAppContext = createContext(false);

/** Marks its subtree as already inside `.ct-app`; `RootLayout` wraps its outlet in it. */
export function CtAppScope({ children }: { children: ReactNode }) {
  return <CtAppContext.Provider value={true}>{children}</CtAppContext.Provider>;
}

function Scoped({ children }: { children: ReactNode }) {
  return useContext(CtAppContext) ? children : <div className="ct-app">{children}</div>;
}

export function RoutePending() {
  return (
    <Scoped>
      <p className="ct-app__status" role="status">
        Loading…
      </p>
    </Scoped>
  );
}

/**
 * `ct-app__status` goes on the LINE, not on the section. On the section it beat `ct-app__card` in
 * the cascade and the heading inherited the muted (or danger) colour with it, which made "Not
 * found" look disabled and "Something broke" look like part of the error text.
 */
export function RouteNotFound() {
  return (
    <Scoped>
      <section className="ct-app__card">
        <h1>Not found</h1>
        <p className="ct-app__status">That page does not exist.</p>
      </section>
    </Scoped>
  );
}

/**
 * `reset` is what TanStack hands an `errorComponent`; both props are optional because this
 * component is also rendered directly, outside any router, by `rootStatusScope.test.tsx`.
 *
 * **The retry is `router.invalidate()`, and that choice is load-bearing.** For the auth failure
 * this boundary exists to show, invalidating re-runs `_authed`'s `beforeLoad` → `bootstrap()` →
 * `reauthenticate`, which **re-joins the refresh still in flight** after an 8 s UI-tier give-up
 * (see `auth/refresh.ts`). So the button costs no extra `POST /api/auth/refresh` and no extra
 * Postgres write. A "retry" that fired a fresh refresh instead would present the pre-rotation
 * cookie a second time, which is the collision the whole design avoids. `reset()` alone only
 * clears the boundary's own state and would re-render the same failed match.
 *
 * `useRouter({ warn: false })` reads the context without throwing when there is no provider — and
 * it hands back the context DEFAULT, which is `null`, not `undefined`. Testing only for
 * `undefined` compiles (the hook is typed non-nullable, so TypeScript sees no problem) and then
 * throws on the click, taking the error boundary down from inside the error boundary. Both cases
 * are checked for that reason.
 */
export function RouteError({ error, reset }: { error: Error; reset?: () => void }) {
  const router: ReturnType<typeof useRouter> | null | undefined = useRouter({ warn: false });

  function retry() {
    reset?.();
    if (router === null || router === undefined) return;
    void router.invalidate();
  }

  return (
    <Scoped>
      <section className="ct-app__card ct-app__card--danger">
        <h1>Something broke</h1>
        <p className="ct-app__status ct-app__status--error">{error.message}</p>
        <button type="button" className="ct-app__button" onClick={retry}>
          Try again
        </button>
      </section>
    </Scoped>
  );
}
