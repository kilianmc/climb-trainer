import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { AuthProvider, createAuth } from '../auth/AuthProvider';
import { BUILD_ID } from '../buildId';
import { useLibrary } from '../library/api';
import { useVocabulary } from '../profile/api';
import { createQueryClient } from '../router';

// Both cached reference reads must carry the build id: the URL is the only thing that can stop a
// new bundle reading a body cached before its own deploy, and no behavioural test can see that.
const CACHED_READS: readonly [string, () => unknown][] = [
  ['/api/vocabulary', () => useVocabulary()],
  ['/api/library', () => useLibrary()],
];

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

function harness() {
  const auth = createAuth();
  // Signed in, or `enabled: isAuthenticated` keeps both queries from fetching at all.
  auth.session.set('user-token', 'user');
  const queryClient = createQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <AuthProvider auth={auth}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </AuthProvider>
  );
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each(CACHED_READS)('%s is requested with the build id as `?v=`', async (path, hook) => {
  renderHook(hook, { wrapper: harness() });

  await waitFor(() => {
    expect(fetch).toHaveBeenCalled();
  });

  const url = new URL(urlOf(vi.mocked(fetch).mock.calls[0]?.[0]), 'http://localhost');
  expect(url.pathname).toBe(path);
  expect(url.searchParams.get('v')).toBe(BUILD_ID);
});

it('positive control: the build id is a real value, so the assertion above is not `null === null`', () => {
  expect(BUILD_ID).not.toBe('');
  expect(new URL('http://localhost/api/vocabulary').searchParams.get('v')).toBeNull();
});
