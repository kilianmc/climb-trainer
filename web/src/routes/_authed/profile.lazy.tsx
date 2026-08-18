import { createLazyFileRoute } from '@tanstack/react-router';

/** Placeholder. PR #7 onward brings profile and target-grade editing. */
function Profile() {
  return (
    <>
      <h1>Profile</h1>
      <p className="ct-app__muted">Arrives in PR #7.</p>
    </>
  );
}

export const Route = createLazyFileRoute('/_authed/profile')({ component: Profile });
