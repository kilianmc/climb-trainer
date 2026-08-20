import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';

/**
 * The submit path of registration, end to end through the real form and the real client.
 *
 * `authClient.test.ts` proves `register()` puts whatever it is given on the wire, and
 * `CredentialsForm` is deliberately not unit-tested (it renders the props it was given). The
 * **glue between them is not** — `register.tsx` maps the form's `inviteCode` onto the request's
 * snake_case `invite_code` — and that gap shipped green: `invite_code: ''` passed the whole
 * suite while making sign-up impossible for every invitee, since the server answers a 400 for
 * an empty code exactly as it does for a wrong one.
 *
 * So this is a core-user-path test (CLAUDE.md: "anything that saves or submits"), not a render
 * test of a presentational component. It is the only one of its kind here on purpose — the
 * policy exclusion still covers the rest of `CredentialsForm`.
 *
 * Note the body is asserted with `toEqual`, which pins the key SET as well as the values.
 * `RegisterRequest` has `extra="forbid"`, so a camelCase `inviteCode` sent alongside the
 * correct field would be a 422 in production and has to fail here too.
 */
const EMAIL = 'bob@example.com';
const PASSWORD = 'a-long-enough-passphrase';
const INVITE_CODE = 'ZjE-KAd_05rpl9w0USLAUw';

/** `fetch`'s first argument is `RequestInfo | URL`; only one of the three is a string. */
function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

function registerRequestBody(): unknown {
  const call = vi
    .mocked(fetch)
    .mock.calls.find(([input]) => urlOf(input).endsWith('/api/auth/register'));
  if (call === undefined) throw new Error('no request was made to /api/auth/register');
  const body = call[1]?.body;
  // `apiFetch` JSON-encodes `json` itself, so anything else here means the call was made
  // without a body at all — which is a failure worth naming rather than stringifying.
  if (typeof body !== 'string') throw new Error(`register carried no JSON body: ${typeof body}`);
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
        { status: 201, headers: { 'content-type': 'application/json' } },
      ),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it('sends the invite code the visitor typed, under the name the server expects', async () => {
  const auth = createAuth();
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/register'] }), {
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

  expect(await screen.findByRole('heading', { name: 'Create account' })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: EMAIL } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: PASSWORD } });
  fireEvent.change(screen.getByLabelText('Invite code'), { target: { value: INVITE_CODE } });
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

  await vi.waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());

  expect(registerRequestBody()).toEqual({
    email: EMAIL,
    password: PASSWORD,
    invite_code: INVITE_CODE,
  });
});
