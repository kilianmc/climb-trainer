import { useQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';

import { apiFetch } from '../api/client';

type Health = { status: string };

/**
 * Dashboard placeholder — PR #8 onward fills it in.
 *
 * The one non-stub part is the health probe carried over from the PR #1 shell. It is
 * the only code path that exercises `apiFetch` resolving its base from
 * `import.meta.url`, which is what makes the federated mount reach climb.kilianmc.com
 * instead of the shell's SPA rewrite. Deleting it would leave that untested in a
 * browser until PR #6.
 */
function Dashboard() {
  const health = useQuery({ queryKey: ['health'], queryFn: () => apiFetch<Health>('/api/health') });

  return (
    <>
      <h1>climb-trainer</h1>
      <p className="ct-app__muted">Training plans that follow the aspects of climbing.</p>
      <p className="ct-app__status" role="status">
        {health.isPending && 'Checking the API…'}
        {health.isSuccess && 'API reachable — SPA and FastAPI are the same origin.'}
        {health.isError && health.error.message}
      </p>
    </>
  );
}

export const Route = createFileRoute('/')({ component: Dashboard });
