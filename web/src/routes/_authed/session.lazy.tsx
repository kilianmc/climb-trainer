import { createLazyFileRoute } from '@tanstack/react-router';

/** Placeholder. PR #15a brings the session player. */
function Session() {
  return (
    <>
      <h1>Session</h1>
      <p className="ct-app__muted">Arrives in PR #15a.</p>
    </>
  );
}

export const Route = createLazyFileRoute('/_authed/session')({ component: Session });
