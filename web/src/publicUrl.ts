/**
 * Absolute URL for a file served out of `web/public/`.
 *
 * **This is the image half of the bug `api/client.ts` exists for.** A bare
 * `src="/landing/hero-960.avif"` is resolved by the browser against the DOCUMENT, and in the
 * federated mount the document is kilianmc.com — so every landing photograph would 404 against
 * the portfolio's own origin while working perfectly standalone. Same shape as the relative
 * `/api/...` that returned the shell's SPA rewrite, and same fix: resolve against the origin
 * **this chunk was served from**, which is climb.kilianmc.com in the federated mount and
 * localhost in dev.
 *
 * Why not `import`ed assets: Vite would emit a content-hashed name (better for caching) but as an
 * absolute `/assets/…` path baked into the JS, i.e. exactly the broken form above. Assets
 * referenced from a stylesheet resolve correctly cross-origin because a `url()` is relative to
 * the CSS file, but `<picture srcset>` cannot be expressed in CSS. So: `public/`, and a runtime
 * origin.
 *
 * No CORS header is needed on these — an `<img>` is not a CORS-governed fetch unless it carries
 * `crossorigin`, and ours do not. (Do NOT add `/landing/*` to `vercel.json`'s
 * `Access-Control-Allow-Origin` rules: `mf-contract.test.ts` asserts that wildcard appears on
 * `/remoteEntry.js` and `/assets/*` and nowhere else.)
 */

function resolvePublicBase(): string {
  try {
    // @vite-ignore — it must stay unresolved at build time; runtime resolution is the point.
    return new URL(/* @vite-ignore */ '.', import.meta.url).origin;
  } catch {
    return globalThis.location?.origin ?? '';
  }
}

export const PUBLIC_BASE = resolvePublicBase();

/** `path` is relative to `web/public/`, with no leading slash. */
export function publicUrl(path: string): string {
  return `${PUBLIC_BASE}/${path}`;
}
