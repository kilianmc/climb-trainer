// @vitest-environment node
// Needs no DOM, and under jsdom `import.meta.url` is an http: URL that fileURLToPath rejects.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * `vercel.json`'s two `Access-Control-Allow-Origin` rules are the only header rules whose
 * removal breaks a consumer OUTSIDE this repo — portfolio-shell mounting
 * `climbTrainer/App` across origins — while every check in this repo stays green. Both
 * were proved load-bearing by deleting them:
 *
 * - without `/assets/*`, the first `import()` rejects with `TypeError: Failed to fetch
 *   dynamically imported module`, because `remoteEntry.js` is a stub that **statically
 *   imports** `/assets/virtual_mf-REMOTE_ENTRY_ID….js`;
 * - with the header on everything except the emitted `.css`, `get('./App')` rejects with
 *   `Unable to preload CSS for …/assets/router-*.css`.
 *
 * Asserted from the web side rather than beside `tests/test_routing.py` because
 * `tests/test_security_headers.py` deliberately does not assert `vercel.json`'s contents
 * ("that would restate config"). These two rules are the exception that reasoning allows:
 * they are not config restated, they are the MF contract, and they fail off-repo and
 * silently. Keeping them in the `web` job also puts them in the toolchain that owns the
 * remote.
 */

const ACAO = 'Access-Control-Allow-Origin';

/** The ONLY sources permitted to carry the wildcard. Never `/api/*`: it would let any
 *  site read authenticated responses. */
const WILDCARD_SOURCES = ['/remoteEntry.js', '/assets/(.*)'];

type HeaderRule = { source: string; headers: { key: string; value: string }[] };

const config = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../vercel.json', import.meta.url)), 'utf8'),
) as { headers?: HeaderRule[] };

const rules = config.headers ?? [];

describe('the Module Federation delivery contract in vercel.json', () => {
  it.each(WILDCARD_SOURCES)('serves %s with a wildcard ACAO', (source) => {
    const rule = rules.find((entry) => entry.source === source);
    expect(rule, `no headers rule with source "${source}"`).toBeDefined();
    expect(rule?.headers.find((header) => header.key === ACAO)?.value).toBe('*');
  });

  it('puts the wildcard on nothing else, so it can never reach /api/*', () => {
    const carriers = rules
      .filter((entry) => entry.headers.some((header) => header.key === ACAO))
      .map((entry) => entry.source);
    expect([...carriers].sort()).toEqual([...WILDCARD_SOURCES].sort());
  });
});
