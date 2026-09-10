import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RouteError } from './status';

const FALLBACK = 'An unexpected error occurred.';

/** `ErrorComponentProps['error']` is `unknown` (router-core `DefaultErrorBoundaryTypes`) and the
 *  boundary preserves falsy throws, so every shape below really reaches this render. */
const thrown: ReadonlyArray<readonly [string, unknown, string]> = [
  ['an Error', new Error('the loader blew up'), 'the loader blew up'],
  ['an Error with a blank message', new Error('   '), FALLBACK],
  ['a string', 'the token was rejected', 'the token was rejected'],
  ['a blank string', '  ', FALLBACK],
  ['a plain object', { status: 500, detail: 'boom' }, FALLBACK],
  ['null', null, FALLBACK],
  ['undefined', undefined, FALLBACK],
  ['the number 0', 0, FALLBACK],
  ['false', false, FALLBACK],
];

describe.each(thrown)('RouteError given %s', (_name, error, expected) => {
  it('renders a readable line and keeps the boundary standing', () => {
    const { container } = render(<RouteError error={error} />);

    expect(container.querySelector('.ct-app__status--error')?.textContent).toBe(expected);
    expect(screen.getByRole('heading', { name: 'Something broke' })).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Try again' })).not.toBeNull();
    expect(container.textContent).not.toContain('[object Object]');
  });
});
