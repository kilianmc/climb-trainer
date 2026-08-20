import { createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';
import { Route } from './routes/__root';
import { CtAppScope, RouteError, RouteNotFound, RoutePending } from './ui/status';

/**
 * Everything this app renders must stay inside `.ct-app`: in the federated mount the tree
 * is injected into kilianmc.com's document and every rule in `app.scss` — design tokens
 * included — is `.ct-app`-prefixed (issue #15).
 *
 * All three status renders reach ROOT level, where they replace `RootLayout` and the
 * `.ct-app` element goes with it: a root error, a root not-found, a pending root match,
 * and the router's two root-level Suspense fallbacks. They also render inside the outlet,
 * where a second `.ct-app` would inset the layout twice — so both directions are asserted.
 */
const renders = [
  ['RouteError', <RouteError error={new Error('boom from the root')} />, 'boom from the root'],
  ['RouteNotFound', <RouteNotFound />, 'That page does not exist.'],
  ['RoutePending', <RoutePending />, 'Loading…'],
] as const;

describe.each(renders)('%s', (_name, element, text) => {
  it('re-establishes .ct-app at root level', () => {
    const { container } = render(element);

    expect(container.firstElementChild).toHaveClass('ct-app');
    expect(screen.getByText(text).closest('.ct-app')).not.toBeNull();
  });

  it('does not nest a second .ct-app inside the outlet', () => {
    const { container } = render(
      <div className="ct-app">
        <CtAppScope>{element}</CtAppScope>
      </div>,
    );

    expect(container.querySelectorAll('.ct-app')).toHaveLength(1);
    expect(screen.getByText(text).closest('.ct-app')).not.toBeNull();
  });
});

/**
 * `RouteError` reads the router so its "Try again" can `invalidate()`, and it is *also* rendered
 * outside any provider — by the two cases above, and by the root-level Suspense fallbacks. That
 * is what `useRouter({ warn: false })` is for: it returns `undefined` instead of throwing. Without
 * the guard the retry button would take the whole error boundary down with it, which is the worst
 * possible place for a crash.
 */
it('renders its retry outside a RouterProvider, and clicking it is a no-op', () => {
  // Asserted through `window`'s error event, NOT `expect(...).not.toThrow()`: React re-raises a
  // handler's exception asynchronously via `reportError`, so the throw never reaches the
  // `fireEvent` call and a `not.toThrow()` version of this test passes while the button is broken.
  const uncaught: unknown[] = [];
  const record = (event: ErrorEvent) => {
    uncaught.push(event.error);
    event.preventDefault();
  };
  window.addEventListener('error', record);
  try {
    render(<RouteError error={new Error('boom')} />);
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  } finally {
    window.removeEventListener('error', record);
  }

  expect(uncaught).toEqual([]);
});

// #15 was a wiring bug, not a rendering bug: the components were fine and the root route
// pointed somewhere unscoped. These are the three slots that can render at root level.
it('wires every root-level slot to a scoped render', () => {
  expect(Route.options.errorComponent).toBe(RouteError);
  expect(Route.options.notFoundComponent).toBe(RouteNotFound);
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/'] }), {
    auth: createAuth(),
    queryClient: createQueryClient(),
  });

  expect(router.options.defaultPendingComponent).toBe(RoutePending);
});
