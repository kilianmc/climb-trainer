import { createLazyFileRoute } from '@tanstack/react-router';

/** Placeholder. PR #8 brings the plan generator UI. */
function Plan() {
  return (
    <>
      <h1>Plan</h1>
      <p className="ct-app__muted">Arrives in PR #8.</p>
    </>
  );
}

export const Route = createLazyFileRoute('/_authed/plan')({ component: Plan });
