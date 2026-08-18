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

  /**
   * The dot-segment family. None of these is an origin escape — the leading `/` has already
   * committed the parse to a path — but each one collapses to `climb.kilianmc.com//evil.example`
   * in the address bar, so they are normalised away rather than left as scruff.
   */
  it.each([
    '/..//evil.example',
    '/.//evil.example',
    '/%2e%2e//evil.example',
    '/~/..//evil.example',
  ])('rejects the dot-segment collapse %j', (value) => {
    expect(internalPath(value)).toBeNull();
  });

  it.each(['/../evil.example', '/a/../../evil.example', '/%2E%2E/evil.example', '/a/./b'])(
    'rejects the dot segment %j even without a double slash',
    (value) => {
      expect(internalPath(value)).toBeNull();
    },
  );

  /**
   * ⚠️ **The literal `//` check runs on the UNDECODED value, and that ordering is load-bearing.**
   * `decodeSegments` is throw-tolerant, so a trailing `%` makes `decodeURIComponent` fail and the
   * dot-segment check then runs against the raw string, finds no literal `..`, and passes. The
   * value below is only harmless because the undecoded `//` check already rejected it.
   *
   * So: never move the `//` check after the decode, never make it operate on the decoded string,
   * and never make `decodeSegments` the sole gate. Producing a `//` by collapse requires a
   * literal `//` in the input, which is precisely what the earlier check catches.
   */
  it('rejects a dot segment hidden behind a decode failure, via the undecoded check', () => {
    expect(internalPath('/%2e%2e//evil.example%')).toBeNull();
    // The proof that the decode really does fail on this input, so the case above is reaching
    // the fallback rather than being caught by the decoded check.
    expect(() => decodeURIComponent('/%2e%2e//evil.example%')).toThrow();
  });

  /**
   * Exactly one level of decoding, which is what the URL parser does: `%2e` is a dot segment to
   * the parser, `%252e` is not. So a double-encoded value stays a literal path segment and is
   * correctly accepted rather than over-rejected.
   */
  it('accepts a double-encoded dot segment, which the parser never collapses', () => {
    expect(internalPath('/%252e%252e/plan')).toBe('/%252e%252e/plan');
  });

  // The segment anchoring must not eat file extensions, dotfiles, version numbers or an
  // encoded percent in a query string.
  it.each(['/plan.html', '/a/.well-known/x', '/v1.2/x', '/x?q=100%25', '/diary?page=2#top'])(
    'still accepts the legitimate %j',
    (value) => {
      expect(internalPath(value)).toBe(value);
    },
  );

  // A `//` in a QUERY string is not a path traversal, so the checks are path-scoped.
  it('leaves a double slash inside a query string alone', () => {
    expect(internalPath('/diary?next=a//b')).toBe('/diary?next=a//b');
  });

  it.each([undefined, null, 42, {}, ['/plan']])('rejects the non-string %j', (value) => {
    expect(internalPath(value)).toBeNull();
  });
});
