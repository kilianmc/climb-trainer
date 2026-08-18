/**
 * Validates the `redirect` search param the route guard round-trips through `/login`.
 *
 * An unvalidated one is an open redirect, and this app is unusually exposed to it: the
 * federated mount runs on the kilianmc.com origin, so a crafted link that made the login
 * form navigate off-site would do it from the portfolio's own address bar. The guard also
 * has to work under memory history, where `window.location` is the *host's* — so the value
 * is only ever an internal path, never a URL, and is never handed to `new URL()`.
 *
 * Allow exactly one shape: a single leading `/` followed by a path. Everything below is a
 * real bypass, not defensive padding:
 *
 * - `//evil.com` is protocol-relative — a browser treats it as an absolute origin.
 * - a backslash after the leading slash is normalised to `//` by several browsers.
 * - whitespace and control characters are stripped before URL parsing, so a tab spliced
 *   into the value can survive a naive prefix check and still leave the origin.
 *
 * Written as an ALLOWLIST — a leading slash then printable ASCII, space excluded — rather
 * than a list of rejections, so anything not thought of is denied by default. Route paths
 * here are ASCII and any real value is already percent-encoded, so nothing legitimate is
 * lost, and the whitespace and control-character cases fall out of the same expression.
 */
const SAFE_PATH = /^\/[\u0021-\u007e]*$/;

/** A `.` or `..` path segment, which the URL parser collapses before anyone sees it. */
const DOT_SEGMENT = /(?:^|\/)\.\.?(?:\/|$)/;

export function internalPath(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  if (!SAFE_PATH.test(value)) return null;
  // Printable, so the allowlist admits it; browsers normalise `/\` to `//`.
  if (value.includes('\\')) return null;

  // Checked on the PATH only, so a query string keeping a `//` in a future param is not
  // collateral damage. Both checks close the dot-segment-collapse family — `/..//host`,
  // `/.//host`, `/%2e%2e//host` — which is **not** an origin escape (the leading `/` has
  // already committed the parse to a path), but does let a crafted link put
  // `climb.kilianmc.com//host` in the address bar on a not-found page. Cosmetic; closed
  // because normalising here is a line and a half.
  const path = value.split(/[?#]/, 1)[0] ?? '';
  if (path.includes('//')) return null;
  if (DOT_SEGMENT.test(decodeSegments(path))) return null;

  return value;
}

/**
 * Percent-decodes just enough to see a hidden dot segment (`%2e%2e`). Deliberately narrow and
 * failure-tolerant: `decodeURIComponent` throws on a lone `%`, and a malformed escape is not a
 * reason to reject a path the allowlist already vetted.
 */
function decodeSegments(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}
