import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createAuthClient } from './authClient';
import { internalPath } from './redirectTarget';
import { createSessionStore, type SessionStore } from './session';

/**
 * The demo write-ban is the trap this file exists for. `server/auth/deps.py::enforce_auth`
 * applies it **before** its public-route check, so a `demo`-scope bearer 403s on register,
 * login, logout and refresh — every mutating auth route except `POST /api/auth/demo`. A
 * visitor who looked around the demo and then decided to sign up would hit "demo mode is
 * read-only" on the login form, with nothing on screen to explain it.
 */
let session: SessionStore;

function headersOf(index: number): Record<string, string> {
  const call = vi.mocked(fetch).mock.calls[index];
  return (call?.[1]?.headers ?? {}) as Record<string, string>;
}

beforeEach(() => {
  session = createSessionStore();
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'new',
          token_type: 'bearer',
          expires_in: 10_800,
          scope: 'user',
        }),
        { headers: { 'content-type': 'application/json' } },
      ),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the credential calls', () => {
  it.each(['login', 'register', 'logout'] as const)(
    'drops a demo bearer before %s, or the demo write-ban 403s it',
    async (method) => {
      session.set('demo-token', 'demo');
      const client = createAuthClient(session);

      if (method === 'logout') await client.logout();
      else await client[method]({ email: 'a@b.example', password: 'x'.repeat(12) });

      expect(headersOf(0)).not.toHaveProperty('authorization');
    },
  );

  it('sends content-type on the bodied calls — FastAPI 422s a POST without it', async () => {
    await createAuthClient(session).login({ email: 'a@b.example', password: 'x'.repeat(12) });

    expect(headersOf(0)['content-type']).toBe('application/json');
    expect(vi.mocked(fetch).mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({ email: 'a@b.example', password: 'x'.repeat(12) }),
    );
  });

  it('sends no content-type where the server declares no body param', async () => {
    await createAuthClient(session).demo();

    expect(headersOf(0)).not.toHaveProperty('content-type');
    expect(vi.mocked(fetch).mock.calls[0]?.[1]?.body).toBeUndefined();
  });

  it('keeps the bearer on GET /api/auth/me, which is not a write', async () => {
    session.set('live', 'user');
    await createAuthClient(session).me();

    expect(headersOf(0).authorization).toBe('Bearer live');
  });
});

/**
 * `internalPath` guards the `?redirect=` round trip through `/login`. An open redirect here
 * would fire from the *portfolio's* address bar in the federated mount, so the accepted shape
 * is exactly one: a single leading slash, no whitespace, no backslash.
 */
describe('internalPath', () => {
  it.each(['/plan', '/', '/diary?page=2', '/a/b/c#top'])('accepts %s', (value) => {
    expect(internalPath(value)).toBe(value);
  });

  it.each([
    '//evil.example',
    'https://evil.example',
    '/\\evil.example',
    '/\\\\evil.example',
    '/ /evil.example',
    '/\tevil.example',
    '/\nevil.example',
    'plan',
    '',
  ])('rejects %j', (value) => {
    expect(internalPath(value)).toBeNull();
  });

  it.each([undefined, null, 42, {}, ['/plan']])('rejects the non-string %j', (value) => {
    expect(internalPath(value)).toBeNull();
  });
});
