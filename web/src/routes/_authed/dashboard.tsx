import { createFileRoute } from '@tanstack/react-router';

import { useAuth } from '../../auth/AuthProvider';

/**
 * Dashboard placeholder — PR #8 onward fills it in. Eager, not lazy: it is where every
 * successful login lands, so there is nothing to gain from a second round trip.
 *
 * The `/api/health` probe that lived here until PR #6 is gone. Its only job was to exercise
 * `apiFetch` resolving its base from `import.meta.url` in a real browser; the auth calls now
 * do that on the path a visitor actually takes.
 */
function Dashboard() {
  const { scope } = useAuth();

  return (
    <>
      <h1>Dashboard</h1>
      <p className="ct-app__muted">
        {scope === 'demo'
          ? 'You are exploring the demo. Everything is read-only.'
          : 'Your training plan and today’s session will appear here.'}
      </p>
    </>
  );
}

export const Route = createFileRoute('/_authed/dashboard')({ component: Dashboard });
