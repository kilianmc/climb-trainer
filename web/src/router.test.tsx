import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createAppRouter, createQueryClient } from './router';

/**
 * Memory history is what makes these nearly free: no jsdom URL plumbing, and it is the
 * same history the federated mount runs on.
 *
 * These also guard a build-level invariant: vitest.config.ts REPLACES vite.config.ts,
 * so the router plugin is not running here. If `src/routeTree.gen.ts` ever stops being
 * committed, this file is what fails.
 */
function renderAt(path: string) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

beforeEach(() => {
  // The dashboard probes /api/health; an unstubbed fetch would reject and retry.
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe('createAppRouter', () => {
  it('renders the dashboard at /', async () => {
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'climb-trainer' })).toBeInTheDocument();
  });

  it('navigates to a lazy leaf, loading its chunk on demand', async () => {
    const router = renderAt('/');
    await screen.findByRole('heading', { name: 'climb-trainer' });

    await router.navigate({ to: '/plan' });

    expect(await screen.findByRole('heading', { name: 'Plan' })).toBeInTheDocument();
    // The shell survives the hop — the nav is outside the outlet.
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });

  it('lands an unmatched path on the catch-all rather than a blank outlet', async () => {
    renderAt('/no-such-page');
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument();
  });
});
