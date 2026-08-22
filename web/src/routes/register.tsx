import { createFileRoute, redirect, useRouter } from '@tanstack/react-router';
import { useState } from 'react';

import { useAuth } from '../auth/AuthProvider';
import { authMessage } from '../auth/messages';
import { CredentialsForm, type CredentialsFormValues } from '../ui/CredentialsForm';

/**
 * Registration logs you straight in — `POST /api/auth/register` returns an access token and
 * sets the refresh cookie in the same response, so there is no second login step.
 *
 * No `?redirect=` here. The guard only ever bounces to `/login`, and someone creating an
 * account has not yet been anywhere to be sent back to.
 *
 * Invite-gated since issue #35: the server refuses a registration without a valid code, and
 * answers the same 400 for a code that is unknown, expired, revoked or used up — so the copy
 * here and in `auth/messages.ts` must not offer to explain which.
 */
const MIN_PASSWORD_LENGTH = 12;

function Register() {
  const router = useRouter();
  const { client } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit({ email, password, inviteCode }: CredentialsFormValues) {
    setPending(true);
    setError(null);
    void client
      .register({ email, password, invite_code: inviteCode })
      .then(() => router.navigate({ to: '/dashboard' }))
      .catch((cause: unknown) => {
        setError(authMessage(cause));
        setPending(false);
      });
  }

  return (
    <div className="ct-app__narrow">
      <h1>Create account</h1>
      <p className="ct-app__lede">
        Registration is invite-only. With a code, an email and a password you are signed in straight
        away — there is no verification email.
      </p>
      <CredentialsForm
        submitLabel="Create account"
        pendingLabel="Creating your account…"
        passwordAutoComplete="new-password"
        minPasswordLength={MIN_PASSWORD_LENGTH}
        requestInviteCode
        pending={pending}
        error={error}
        onSubmit={submit}
      />
    </div>
  );
}

export const Route = createFileRoute('/register')({
  beforeLoad: ({ context }) => {
    if (context.auth.session.get().token !== null) throw redirect({ to: '/dashboard' });
  },
  component: Register,
});
