import { createFileRoute, redirect, useRouter } from '@tanstack/react-router';
import { useState } from 'react';

import { authMessage } from '../auth/messages';
import { useAuth } from '../auth/AuthProvider';
import { Marketing } from '../ui/Marketing';

/**
 * The public landing page — the same page in both mounts, with no per-mount branching and no
 * auto-enter-demo path. A visitor reads it and then chooses: log in, register, or step into
 * the demo.
 *
 * `beforeLoad` only checks the token **already in memory**; it deliberately does not call
 * `bootstrap()`. Doing so would fire a refresh rotation — a Postgres write — for every
 * anonymous visitor who merely reads this page, which is the write-per-request pattern the
 * compute budget forbids. The accepted consequence: a signed-in user opening `/` cold sees
 * this page rather than their dashboard, and is signed back in as soon as they enter the app.
 */
function Landing() {
  const router = useRouter();
  const { client } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function exploreDemo() {
    setPending(true);
    setError(null);
    void client
      .demo()
      .then(() => router.navigate({ to: '/dashboard' }))
      .catch((cause: unknown) => {
        setError(authMessage(cause));
      })
      .finally(() => {
        setPending(false);
      });
  }

  return <Marketing onExploreDemo={exploreDemo} demoPending={pending} demoError={error} />;
}

export const Route = createFileRoute('/')({
  beforeLoad: ({ context }) => {
    if (context.auth.session.get().token !== null) throw redirect({ to: '/dashboard' });
  },
  component: Landing,
});
