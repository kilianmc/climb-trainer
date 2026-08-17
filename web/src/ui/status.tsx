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

export function RouteNotFound() {
  return (
    <Scoped>
      <section className="ct-app__status">
        <h1>Not found</h1>
        <p>That page does not exist.</p>
      </section>
    </Scoped>
  );
}

export function RouteError({ error }: { error: Error }) {
  return (
    <Scoped>
      <section className="ct-app__status ct-app__status--error">
        <h1>Something broke</h1>
        <p>{error.message}</p>
      </section>
    </Scoped>
  );
}
