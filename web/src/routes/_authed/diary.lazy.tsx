import { createLazyFileRoute } from '@tanstack/react-router';

/** Placeholder. PR #12 brings the training diary. */
function Diary() {
  return (
    <>
      <h1>Diary</h1>
      <p className="ct-app__muted">Arrives in PR #12.</p>
    </>
  );
}

export const Route = createLazyFileRoute('/_authed/diary')({ component: Diary });
