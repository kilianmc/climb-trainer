import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Route } from './routes/__root';

/**
 * Everything this app renders has to stay inside `.ct-app`: in the federated mount the
 * tree is injected into kilianmc.com's document, and every rule in `app.scss` — design
 * tokens included — is `.ct-app`-prefixed. A root-level error replaces the layout, so its
 * fallback is the one render path that can escape the scope and drop unstyled error text
 * into the portfolio (issue #15). `notFoundComponent` renders inside the outlet.
 */
describe('the root route error fallback', () => {
  it('renders inside the .ct-app scope', () => {
    const RootError = Route.options.errorComponent;
    if (typeof RootError !== 'function') throw new Error('the root route lost its errorComponent');

    const { container } = render(
      <RootError error={new Error('boom from the root')} reset={() => undefined} />,
    );

    expect(container.firstElementChild).toHaveClass('ct-app');
    expect(screen.getByText('boom from the root').closest('.ct-app')).not.toBeNull();
  });
});
