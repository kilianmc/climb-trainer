/**
 * The deploy identity, as one string, read from the `define` in `vite.config.ts`.
 *
 * Its only job is to key `GET /api/library?v=<BUILD_ID>`. That response is served
 * `public, s-maxage=31536000, immutable` from a shared CDN, so the URL is the only thing
 * that can ever invalidate it: **a build id that fails to change between deploys pins a
 * stale exercise library for a year.** See `buildId()` in `vite.config.ts` for where the
 * value comes from and what it is locally.
 *
 * `typeof` rather than a bare reference, and a literal fallback, because `vitest.config.ts`
 * REPLACES `vite.config.ts` (see the comment in that file) — so under Vitest the define is
 * not applied and the identifier does not exist. A bare read would be a `ReferenceError` in
 * every test that touches the library, which is a confusing way to learn about a build
 * setting. `typeof` on an undeclared identifier is the one safe read in JavaScript.
 */
declare const __BUILD_ID__: string | undefined;

export const BUILD_ID: string =
  typeof __BUILD_ID__ === 'string' && __BUILD_ID__ !== '' ? __BUILD_ID__ : 'test';
