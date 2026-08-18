import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { createAuthClient } from './authClient';
import { createSessionStore } from './session';

/**
 * The token must never reach web storage, in either mount. `remote.guard.test.tsx` watches
 * the whole federated entry for that; this watches the module that actually holds the token,
 * because the realistic regression is someone "persisting the session across reloads" here.
 *
 * Storage has four mutation paths and they fail differently — see the note in
 * `remote.guard.test.tsx`. `Object.keys` catches property assignment, which bypasses
 * `Storage.prototype.setItem` entirely.
 */
// One spy covers both stores: `localStorage` and `sessionStorage` share the prototype.
let setItem: MockInstance<Storage['setItem']>;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setItem = vi.spyOn(Storage.prototype, 'setItem');
  // A fresh Response per call: a body can only be read once, so a shared mockResolvedValue
  // fails the second request with "Body has already been read".
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Response(
          JSON.stringify({
            access_token: 'a.b.c',
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
  vi.restoreAllMocks();
});

describe('the session store', () => {
  it('holds the token in memory and writes nothing to storage', async () => {
    const session = createSessionStore();
    await createAuthClient(session).login({ email: 'a@b.example', password: 'x'.repeat(12) });

    expect(session.get()).toEqual({ token: 'a.b.c', scope: 'user' });
    expect(session.header()).toEqual({ authorization: 'Bearer a.b.c' });
    expect(Object.keys(localStorage)).toEqual([]);
    expect(Object.keys(sessionStorage)).toEqual([]);
    expect(setItem).not.toHaveBeenCalled();
  });

  it('positive control: the storage detectors can see a write', () => {
    localStorage.setItem('ct:probe', '1');
    (sessionStorage as unknown as Record<string, string>)['probe'] = '1';

    expect(setItem).toHaveBeenCalled();
    expect(Object.keys(localStorage)).toEqual(['ct:probe']);
    // Property assignment leaves no `setItem` call, which is why the key check exists.
    expect(Object.keys(sessionStorage)).toEqual(['probe']);
  });

  it('goes anonymous on logout, and notifies subscribers exactly on change', async () => {
    const session = createSessionStore();
    const client = createAuthClient(session);
    const changes = vi.fn();
    session.subscribe(changes);

    await client.login({ email: 'a@b.example', password: 'x'.repeat(12) });
    expect(changes).toHaveBeenCalledTimes(1);

    await client.logout();

    expect(session.get()).toEqual({ token: null, scope: null });
    expect(session.header()).toEqual({});
    // One for the login, one for the logout. `logout` clears before its request, and a
    // clear from an already-anonymous store must not emit at all.
    expect(changes).toHaveBeenCalledTimes(2);
  });
});
