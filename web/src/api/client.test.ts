import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NotJsonError, apiFetch } from './client';

function mockFetch(body: unknown, init: { status?: number; contentType?: string }) {
  const res = new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'content-type': init.contentType ?? 'application/json' },
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res));
}

afterEach(() => vi.unstubAllGlobals());

describe('apiFetch', () => {
  it('returns the parsed body on success', async () => {
    mockFetch({ status: 'ok' }, {});
    await expect(apiFetch<{ status: string }>('/api/health')).resolves.toEqual({ status: 'ok' });
  });

  it('rejects HTML with NotJsonError rather than letting res.ok lie', async () => {
    // The exact failure this client exists to prevent: a rewrite serves the SPA
    // shell with a 200, so `res.ok` is true and `res.json()` throws far away from
    // the cause. Bit the fund dashboard once already.
    mockFetch('<!doctype html><html></html>', { contentType: 'text/html; charset=utf-8' });
    await expect(apiFetch('/api/health')).rejects.toBeInstanceOf(NotJsonError);
  });

  it('surfaces the API detail message on an error status', async () => {
    mockFetch({ detail: 'Not Found' }, { status: 404 });
    await expect(apiFetch('/api/nope')).rejects.toThrow(new ApiError('Not Found', 404));
  });

  it('sends credentials so the same-site refresh cookie travels', async () => {
    mockFetch({ status: 'ok' }, {});
    await apiFetch('/api/health');
    const [, init] = vi.mocked(fetch).mock.calls[0]!;
    expect(init?.credentials).toBe('include');
  });
});
