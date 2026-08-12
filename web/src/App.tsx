import { useEffect, useState } from 'react';

import { apiFetch } from './api/client';

type Health = { status: string };
type State = { kind: 'loading' } | { kind: 'ok' } | { kind: 'error'; message: string };

/**
 * Placeholder shell for PR #1. Its only job is to prove the deployed SPA and the
 * Python API are the same origin in the same Vercel project — the S0 finding this
 * repo is built on. Routing and the real UI arrive in PR #4.
 */
export default function App() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    let cancelled = false;
    apiFetch<Health>('/api/health')
      .then(() => !cancelled && setState({ kind: 'ok' }))
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({ kind: 'error', message: err instanceof Error ? err.message : String(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="boot">
      <h1>climb-trainer</h1>
      <p className="boot__tagline">Training plans that follow the aspects of climbing.</p>
      <p className={`boot__status boot__status--${state.kind}`}>
        {state.kind === 'loading' && 'Checking the API…'}
        {state.kind === 'ok' && 'API reachable — SPA and FastAPI are the same origin.'}
        {state.kind === 'error' && state.message}
      </p>
    </main>
  );
}
