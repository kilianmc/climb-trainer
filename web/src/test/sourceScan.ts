/**
 * Shared by the source-scanning guards (`styles/designGuard.test.ts`, `pwaContract.test.ts`).
 *
 * Stripping comments is load-bearing, not tidiness: the REASON for each rule those guards
 * enforce is written in the very file being scanned ("do not use `backdrop-filter`", "NO
 * `runtimeCaching` for /api"), so every detector would otherwise fire on its own prose. It is
 * also the part most likely to be subtly wrong, which is why both callers positive-control it
 * against a bad sample AND against the same sample commented out.
 *
 * The `//` form requires start-of-line or whitespace before it, so it does not eat the escaped
 * slashes in a regex literal such as `/^\/api\//` or the `//` in a URL string.
 */
export function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1');
}
