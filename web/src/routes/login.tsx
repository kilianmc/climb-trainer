import { createFileRoute } from '@tanstack/react-router';

/** Placeholder. PR #6 brings the real auth UI; nothing auth-related belongs here yet. */
function Login() {
  return (
    <>
      <h1>Log in</h1>
      <p className="ct-app__muted">Arrives in PR #6.</p>
    </>
  );
}

// Eager, unlike the other leaves: it is the first screen an unauthenticated visitor
// needs, so there is nothing to gain from making them wait on a second request.
export const Route = createFileRoute('/login')({ component: Login });
