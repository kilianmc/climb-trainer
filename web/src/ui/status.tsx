/**
 * The three route-level status renders. Shared because the root route and the router
 * defaults both need them: the router defaults give every leaf its own boundary (an
 * error in `/plan` keeps the nav usable), and the root route is the backstop for
 * anything that fails above the outlet.
 */

export function RoutePending() {
  return (
    <p className="ct-app__status" role="status">
      Loading…
    </p>
  );
}

export function RouteNotFound() {
  return (
    <section className="ct-app__status">
      <h1>Not found</h1>
      <p>That page does not exist.</p>
    </section>
  );
}

export function RouteError({ error }: { error: Error }) {
  return (
    <section className="ct-app__status ct-app__status--error">
      <h1>Something broke</h1>
      <p>{error.message}</p>
    </section>
  );
}
