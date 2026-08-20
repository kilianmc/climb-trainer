import { createFileRoute, redirect, useRouter } from '@tanstack/react-router';
import { useState } from 'react';

import { useAuth } from '../auth/AuthProvider';
import { authMessage } from '../auth/messages';
import { internalPath } from '../auth/redirectTarget';
import { CredentialsForm, type CredentialsFormValues } from '../ui/CredentialsForm';

/**
 * `?redirect=` carries the path the guard bounced the visitor off, and it is validated
 * **twice** — see the comment on `target` below for why the second one is the real control
 * and `validateSearch` is only tidying the URL.
 *
 * The successful navigation goes through `router.history.push`, not `router.navigate({ to })`:
 * the target is a validated runtime string, and `to` is typed to the literal paths in the
 * route tree. `push` takes the raw path, which is also what `remoteHistory.ts` documents as
 * the safe half — only `<Link>` reads the origin-rewriting `createHref`.
 */
function Login() {
  const router = useRouter();
  // Validated AGAIN here, not just in `validateSearch`. A route's search is MERGED with its
  // parents', and the root route validates nothing, so a rejected `?redirect=` still reaches
  // this component through the merge — verified 2026-08-18, and `routeGuard.test.tsx` pins the
  // behaviour rather than the intermediate value. This second call is what actually closes the
  // open redirect; treat the one in `validateSearch` as tidying the URL, not as the control.
  const target = internalPath(Route.useSearch().redirect);
  const { client } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Destructured, NOT forwarded whole. `CredentialsForm` always emits `inviteCode` (empty
  // here, since this form does not render the field), and `LoginRequest` is
  // `extra="forbid"` — so passing the form's object through sends a third key and the
  // server 422s before it even reaches the rate limiter. TypeScript cannot catch this:
  // excess-property checking only applies to object *literals*, and a variable carrying
  // extra properties still satisfies `Credentials` structurally. `loginSubmit.test.tsx`
  // asserts the serialised body's exact key set, which is the only level at which it shows.
  function submit({ email, password }: CredentialsFormValues) {
    setPending(true);
    setError(null);
    void client
      .login({ email, password })
      .then(() => {
        router.history.push(target ?? '/dashboard');
      })
      .catch((cause: unknown) => {
        setError(authMessage(cause));
        setPending(false);
      });
  }

  return (
    <>
      <h1>Log in</h1>
      <CredentialsForm
        submitLabel="Log in"
        pendingLabel="Logging in…"
        passwordAutoComplete="current-password"
        pending={pending}
        error={error}
        onSubmit={submit}
      />
    </>
  );
}

// Eager, unlike the guarded leaves: it is the first screen an unauthenticated visitor
// needs, so there is nothing to gain from making them wait on a second request.
export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => {
    const target = internalPath(search.redirect);
    return target === null ? {} : { redirect: target };
  },
  beforeLoad: ({ context }) => {
    if (context.auth.session.get().token !== null) throw redirect({ to: '/dashboard' });
  },
  component: Login,
});
