import { describe, expect, it } from 'vitest';

import { ApiError, NotJsonError } from '../api/client';
import { authMessage } from './messages';

/**
 * Issue #24 asks that a 401, 409, 422 and 429 each produce a specific, human-readable message.
 * This is not a lookup table restating itself — one branch of it is genuinely load-bearing:
 *
 * **`NotJsonError extends ApiError`**, so the ORDER of the two `instanceof` checks decides the
 * outcome. Checking the base class first reads more naturally and is the likely tidy-up, and it
 * would silently turn every HTML-shell response into "Incorrect email or password." — telling a
 * visitor their password is wrong when the truth is that a rewrite is serving the SPA shell for
 * an `/api/*` path. That is the single most misleading message this app could produce, and it is
 * the failure the whole `NotJsonError` design exists to surface.
 */
describe('authMessage', () => {
  it.each([
    [401, 'Incorrect email or password.'],
    [403, 'That did not go through. Please reload the page and try again.'],
    [409, 'That email is already registered — try logging in instead.'],
    [422, 'Check the email address, and make sure the password is at least 12 characters.'],
    [429, 'Too many attempts from this network. Please wait a little and try again.'],
  ])('gives %i its own copy rather than the raw API detail', (status, expected) => {
    expect(authMessage(new ApiError('raw server detail', status))).toBe(expected);
  });

  it('passes an unmapped status through, so a 500 is not silently mislabelled', () => {
    expect(authMessage(new ApiError('Internal Server Error', 500))).toBe('Internal Server Error');
  });

  it('reports a rewrite misconfiguration as itself even though its status is 401', () => {
    // The ordering guard. Swap the two `instanceof` branches in messages.ts and this is the
    // test that fails; nothing else in the suite would notice.
    const message = authMessage(new NotJsonError(401, 'text/html; charset=utf-8'));

    expect(message).toContain('text/html');
    expect(message).toContain('serving the SPA shell');
    expect(message).not.toBe('Incorrect email or password.');
  });

  it('positive control: a plain 401 really does take the credentials branch', () => {
    // Without this, the assertion above would also pass if 401 had no mapping at all.
    expect(authMessage(new ApiError('Not authenticated.', 401))).toBe(
      'Incorrect email or password.',
    );
  });

  it.each([
    ['a dropped connection', new TypeError('Failed to fetch')],
    ['a thrown string', 'boom'],
    ['nothing at all', undefined],
  ])('turns %s into advice instead of a browser-specific string', (_label, thrown) => {
    expect(authMessage(thrown)).toBe(
      'Could not reach the server. Check your connection and try again.',
    );
  });
});
