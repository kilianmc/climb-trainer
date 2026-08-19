import { createFileRoute, redirect, useRouter } from '@tanstack/react-router';
import { useState } from 'react';

import { useAuth } from '../auth/AuthProvider';
import type { Credentials } from '../auth/authClient';
import { authMessage } from '../auth/messages';
import { CredentialsForm } from '../ui/CredentialsForm';

/**
 * Registration logs you straight in — `POST /api/auth/register` returns an access token and
 * sets the refresh cookie in the same response, so there is no second login step.
 *
 * No `?redirect=` here. The guard only ever bounces to `/login`, and someone creating an
 * account has not yet been anywhere to be sent back to.
 */
const MIN_PASSWORD_LENGTH = 12;

function Register() {
  const router = useRouter();
  const { client } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit(credentials: Credentials) {
    setPending(true);
    setError(null);
    void client
      .register(credentials)
      .then(() => router.navigate({ to: '/dashboard' }))
      .catch((cause: unknown) => {
        setError(authMessage(cause));
        setPending(false);
      });
  }

  return (
    <>
      <h1>Create account</h1>
      <p className="ct-app__lede">
        Email and a password, nothing else. There is no verification email, so you are signed in
        straight away.
      </p>
      <CredentialsForm
        submitLabel="Create account"
        pendingLabel="Creating your account…"
        passwordAutoComplete="new-password"
        minPasswordLength={MIN_PASSWORD_LENGTH}
        pending={pending}
        error={error}
        onSubmit={submit}
      />
    </>
  );
}

export const Route = createFileRoute('/register')({
  beforeLoad: ({ context }) => {
    if (context.auth.session.get().token !== null) throw redirect({ to: '/dashboard' });
  },
  component: Register,
});
