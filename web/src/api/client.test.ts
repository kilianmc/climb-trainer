import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NotJsonError, apiFetch } from './client';

function mockFetch(body: unknown, init: { status?: number; contentType?: string }) {
  const res = new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'content-type': init.contentType ?? 'application/json' },
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res));
}

function lastInit(): RequestInit | undefined {
  return vi.mocked(fetch).mock.calls[0]?.[1];
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

  /**
   * FastAPI's `detail` is a string for our own `HTTPException`s and an **array** of
   * `{loc, msg, type}` for a Pydantic 422 — which the auth forms hit more than anything else.
   * Read as a string, that produced `[object Object]` in front of the user.
   */
  it('reads a 422 detail array instead of stringifying objects at the user', async () => {
    mockFetch(
      {
        detail: [
          { loc: ['body', 'password'], msg: 'String should have at least 12 characters' },
          { loc: ['body', 'email'], msg: 'value is not a valid email address' },
        ],
      },
      { status: 422 },
    );

    await expect(apiFetch('/api/auth/register')).rejects.toThrow(
      new ApiError(
        'String should have at least 12 characters; value is not a valid email address',
        422,
      ),
    );
  });

  it('falls back to the status when there is no usable detail', async () => {
    mockFetch({ detail: [{ loc: ['body'] }] }, { status: 400 });
    await expect(apiFetch('/api/nope')).rejects.toThrow(
      new ApiError('Request failed with 400', 400),
    );
  });

  it('sends credentials so the same-site refresh cookie travels', async () => {
    mockFetch({ status: 'ok' }, {});
    await apiFetch('/api/health');
    expect(lastInit()?.credentials).toBe('include');
  });

  /**
   * `strict_content_type` is on by default from FastAPI 0.132: a POST with a body and no
   * `content-type: application/json` is a 422 before the handler runs.
   */
  it('sets content-type and encodes the body for a json request', async () => {
    mockFetch({ ok: true }, {});
    await apiFetch('/api/auth/login', { json: { email: 'a@b.example' } });

    const init = lastInit();
    expect(init?.method).toBe('POST');
    expect((init?.headers as Record<string, string>)['content-type']).toBe('application/json');
    expect(init?.body).toBe(JSON.stringify({ email: 'a@b.example' }));
  });

  it('sets no content-type on a bodyless POST', async () => {
    mockFetch({ ok: true }, {});
    await apiFetch('/api/auth/demo', { method: 'POST' });

    const init = lastInit();
    expect(init?.method).toBe('POST');
    expect(init?.headers as Record<string, string>).not.toHaveProperty('content-type');
    expect(init?.body).toBeUndefined();
  });

  it('merges caller headers over the defaults without losing accept', async () => {
    mockFetch({ ok: true }, {});
    await apiFetch('/api/auth/me', { headers: { authorization: 'Bearer live' } });

    expect(lastInit()?.headers).toEqual({
      accept: 'application/json',
      authorization: 'Bearer live',
    });
  });
});
