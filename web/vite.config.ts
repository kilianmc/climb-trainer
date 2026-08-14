import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/**
 * The production document headers, read out of `vercel.json` rather than copied, so
 * `vite preview` cannot drift from what the CDN sends. Throws instead of falling back:
 * a silently header-less preview is the false negative this exists to prevent.
 */
function productionHeaders(): Record<string, string> {
  // The `source` patterns from vercel.json that a document response matches.
  const documentSources = ['/(.*)', '/((?!api/).*)'];

  const configPath = fileURLToPath(new URL('../vercel.json', import.meta.url));
  const config = JSON.parse(readFileSync(configPath, 'utf8')) as {
    headers?: { source: string; headers: { key: string; value: string }[] }[];
  };

  const headers: Record<string, string> = {};
  for (const source of documentSources) {
    const rule = config.headers?.find((entry) => entry.source === source);
    if (!rule) {
      throw new Error(
        `vercel.json has no headers rule with source "${source}". vite preview mirrors ` +
          `the production headers from that file; update this list if the sources changed.`,
      );
    }
    for (const { key, value } of rule.headers) headers[key] = value;
  }
  return headers;
}

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: true },
  server: {
    port: 5173,
    // Local stand-in for Vercel's /api/* rewrite, so the SPA and API share an
    // origin in dev exactly as they do in production.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
    // The production CSP is deliberately NOT applied here: the dev server's inline
    // client and HMR websocket would need a laxer policy than production's, which would
    // prove less while looking like coverage. Use `preview` below instead.
  },
  preview: {
    port: 4173,
    // The real build with the real production headers — run this before pushing anything
    // that adds a script, font, image host or stylesheet.
    headers: productionHeaders(),
  },
});
