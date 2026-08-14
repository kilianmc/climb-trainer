import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { federation } from '@module-federation/vite';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
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
  // Note this file is NOT merged into vitest.config.ts — that one replaces it — so
  // neither plugin below is active in tests. Hence `src/routeTree.gen.ts` is committed.
  plugins: [
    // Generator first: it must have written the route tree before react() transforms
    // the modules that import it. All four orderings were verified to build, so this
    // is the documented order rather than a required one.
    tanstackRouter({ target: 'react' }),
    react(),
    federation({
      name: 'climbTrainer',
      filename: 'remoteEntry.js',
      dts: false,
      exposes: { './App': './src/remote.tsx' },
      shared: {
        // The scoped `react/` and `react-dom/` entries are not decoration: without
        // them `react/jsx-runtime` and `react-dom/client` resolve to a SECOND copy of
        // React while `react` itself is shared, and hooks fail in ways that look
        // unrelated. See the MF section of CLAUDE.md.
        react: { singleton: true, requiredVersion: '^19.0.0' },
        'react/': { singleton: true, requiredVersion: '^19.0.0' },
        'react-dom': { singleton: true, requiredVersion: '^19.0.0' },
        'react-dom/': { singleton: true, requiredVersion: '^19.0.0' },
      },
    }),
  ],
  // No explicit `build.target`: Vite 8's default (`baseline-widely-available`, chrome111+)
  // already supports the top-level await MF emits. ai-portfolio-project1 pins `chrome89`
  // because it predates that default; copying it here would only LOWER the baseline.
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
