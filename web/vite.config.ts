import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { federation } from '@module-federation/vite';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

/** The light `--ct-bg` from `src/styles/_tokens.scss`; `index.html` carries the dark twin. */
const LIGHT_BG = '#eef0ed';

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

/** Shared by `server` and `preview`: both need /api on this origin, for different reasons. */
const API_PROXY = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } };

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
        react: { singleton: true, requiredVersion: '^19.0.0', strictVersion: true },
        'react/': { singleton: true, requiredVersion: '^19.0.0', strictVersion: true },
        'react-dom': { singleton: true, requiredVersion: '^19.0.0', strictVersion: true },
        'react-dom/': { singleton: true, requiredVersion: '^19.0.0', strictVersion: true },
      },
    }),
    // AFTER federation(): the service worker precaches the built app shell, so it has to
    // see the final asset graph, remoteEntry stub included.
    VitePWA({
      // 'prompt', deliberately, not 'autoUpdate'. A silent `skipWaiting` deletes the old
      // precache the moment a new worker activates, so a page left open across a deploy
      // 404s on the next lazily-loaded route chunk — and it could swap code under a session
      // player mid-set. The visitor decides when to take the new build.
      registerType: 'prompt',
      // We register from `main.tsx`, and only from there (its scope in the federated mount
      // would be kilianmc.com). `null` rather than 'inline' is also forced by the production
      // CSP: `script-src 'self'` blocks an inline registration script with no nonce.
      injectRegister: null,
      // Not in the manifest's `icons`, so the plugin does not precache them on its own.
      includeAssets: ['favicon.ico', 'mark.svg', 'apple-touch-icon-180x180.png'],
      workbox: {
        // One `sw.js` instead of sw.js + an unhashed workbox-*.js — one fewer file at the root
        // that the SPA rewrite could mis-serve as index.html. It is a workbox-build option, not
        // a plugin-level one, despite reading like plugin plumbing.
        inlineWorkboxRuntime: true,
        // Explicit, and narrower than the default `**/*.{js,css,html,ico,png,svg}`: the
        // manifest icons and `includeAssets` above are added by the plugin with their own
        // revisions, so globbing them too would offer workbox two entries for one URL.
        // `build.sourcemap` is on and `.map` is deliberately absent — no reason to ship
        // sourcemaps into a phone's Cache Storage.
        globPatterns: ['**/*.{js,css,html}'],
        navigateFallback: '/index.html',
        // `/api/*` must ALWAYS be FastAPI JSON, never the SPA shell (CLAUDE.md deployment
        // trap 2). Without this the worker answers an offline API call with index.html and
        // `apiFetch` throws NotJsonError far from the cause.
        navigateFallbackDenylist: [/^\/api\//],
        cleanupOutdatedCaches: true,
        // NO `runtimeCaching` for /api, ever: authenticated JSON in Cache Storage is written
        // to disk and survives logout, and nothing in the app clears it.
      },
      manifest: {
        name: 'climb-trainer',
        short_name: 'Climb',
        description:
          'Pick the grade you are training for, get a plan that covers every aspect of climbing, and follow it set by set in the gym.',
        start_url: '/',
        scope: '/',
        id: '/',
        display: 'standalone',
        background_color: LIGHT_BG,
        theme_color: LIGHT_BG,
        categories: ['fitness', 'health', 'sports'],
        // Hand-written against the files `npm run generate:icons` actually emitted; the
        // generator is not wired into the build, so these names are checked, not assumed.
        icons: [
          { src: 'pwa-64x64.png', sizes: '64x64', type: 'image/png' },
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'maskable-icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
        // No `orientation`: the app is used in landscape on a bouldering mat as often as in
        // portrait, and locking it would fight the phone the moment it is put down.
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
    proxy: API_PROXY,
    // The production CSP is deliberately NOT applied here: the dev server's inline
    // client and HMR websocket would need a laxer policy than production's, which would
    // prove less while looking like coverage. Use `preview` below instead.
  },
  preview: {
    port: 4173,
    // The real build with the real production headers — run this before pushing anything
    // that adds a script, font, image host or stylesheet.
    headers: productionHeaders(),
    // The same /api proxy as dev. Production serves /api from this origin, so without it
    // preview 404s every auth call and cannot exercise a signed-in path at all — and
    // preview is the ONLY place the real build meets the real production headers, which is
    // exactly where a CSP or service-worker mistake shows up.
    proxy: API_PROXY,
  },
});
