import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';

/**
 * The submit path of login, end to end through the real form and the real client — the
 * sibling of `registerSubmit.test.tsx`, and written because the bug it guards SHIPPED.
 *
 * `CredentialsForm` always emits three values (`email`, `password`, `inviteCode`), because
 * one component serves both screens and the invite field is merely hidden on `/login`.
 * `login.tsx` used to forward that object whole to `client.login()`, so every production
 * login POSTed `{email, password, inviteCode: ''}`. `LoginRequest` is `extra="forbid"`, so
 * the server answered **422 before `enforce_all`** — which is also why no rate-limit row was
 * ever written to point at it.
 *
 * ## Why this has to assert the serialised body
 *
 * **The type system provably cannot catch it.** Excess-property checking applies only to
 * object *literals*; a variable whose type has extra properties still satisfies
 * `Credentials` structurally, so `client.login(credentials)` type-checked perfectly. Nothing
 * below the wire format distinguishes the broken version from the fixed one — not the call
 * arguments, not the client, not the form.
 *
 * **And it must assert the exact key SET, with `toEqual`.** A test that merely checked
 * `email` and `password` were present would have passed against the bug, which is the whole
 * failure mode being guarded. Same reasoning as the register test's `toEqual`.
 *
 * The harness is deliberately a copy of `registerSubmit.test.tsx`'s rather than a shared
 * import: these two guards must be able to fail independently, and `urlOf` is already
 * duplicated in `auth/refresh.test.ts` for the same reason.
 */
const EMAIL = 'bob@example.com';
const PASSWORD = 'a-long-enough-passphrase';

/** `fetch`'s first argument is `RequestInfo | URL`; only one of the three is a string. */
function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

function loginRequestBody(): unknown {
  const call = vi
    .mocked(fetch)
    .mock.calls.find(([input]) => urlOf(input).endsWith('/api/auth/login'));
  if (call === undefined) throw new Error('no request was made to /api/auth/login');
  const body = call[1]?.body;
  // `apiFetch` JSON-encodes `json` itself, so anything else here means the call was made
  // without a body at all — which is a failure worth naming rather than stringifying.
  if (typeof body !== 'string') throw new Error(`login carried no JSON body: ${typeof body}`);
  return JSON.parse(body);
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'issued',
          token_type: 'bearer',
          expires_in: 10_800,
          scope: 'user',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it('sends ONLY email and password — never the form’s empty invite code', async () => {
  const auth = createAuth();
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/login'] }), {
    auth,
    queryClient,
  });
  render(
    <AuthProvider auth={auth}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthProvider>,
  );

  expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: EMAIL } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

  await vi.waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());

  // `toEqual`, not per-key assertions: the bug was an EXTRA key, so only the full set shows it.
  expect(loginRequestBody()).toEqual({ email: EMAIL, password: PASSWORD });
});
