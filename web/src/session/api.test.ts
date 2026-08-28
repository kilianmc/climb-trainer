import { describe, expect, it } from 'vitest';

import { ApiError, NotJsonError } from '../api/client';

import { classifyFailure, sessionLogKey, writesEnabled } from './api';

/**
 * The two decisions in `api.ts` that can destroy data or spend money, both pure:
 *
 * - **`classifyFailure`** — a quarantined batch is gone for good, so treating a 503 as
 *   permanent loses a session; treating a 422 as retryable is the "retries forever and can
 *   never succeed" payload `server/fields.py` warns about. 401 requeues: it belongs to the
 *   refresh layer, and a re-login must not cost the climber their sets.
 * - **`writesEnabled`** — demo scope issues zero writes (#65), and every write here is a Neon
 *   wake.
 *
 * The mutation itself is exercised by the screen tests, which own the triggers.
 */

describe('classifyFailure', () => {
  it.each([400, 403, 404, 409, 422])('quarantines a %i', (status) => {
    expect(classifyFailure(new ApiError('refused', status))).toBe('quarantine');
  });

  it.each([500, 502, 503, 504])('requeues a %i', (status) => {
    expect(classifyFailure(new ApiError('server', status))).toBe('requeue');
  });

  it('requeues a 401, which belongs to the refresh layer', () => {
    expect(classifyFailure(new ApiError('unauthorised', 401))).toBe('requeue');
  });

  it('requeues a NotJsonError even though it carries a 2xx status', () => {
    expect(classifyFailure(new NotJsonError(200, 'text/html'))).toBe('requeue');
  });

  it('requeues a network failure and anything else that is not an ApiError', () => {
    expect(classifyFailure(new TypeError('Failed to fetch'))).toBe('requeue');
    expect(classifyFailure(undefined)).toBe('requeue');
  });
});

describe('writesEnabled', () => {
  it('is false for demo scope and for no scope at all', () => {
    expect(writesEnabled('demo')).toBe(false);
    expect(writesEnabled(null)).toBe(false);
  });

  it('is true for a real account', () => {
    expect(writesEnabled('user')).toBe(true);
  });
});

describe('sessionLogKey', () => {
  it('is per-session, so two runs never share a cache entry', () => {
    expect(sessionLogKey('abc')).toEqual(['session', 'log', 'abc']);
    expect(sessionLogKey('abc')).not.toEqual(sessionLogKey('def'));
  });
});
