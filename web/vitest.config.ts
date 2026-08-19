import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // This file REPLACES vite.config.ts, so `vite-plugin-pwa` is not running and nothing
      // resolves `virtual:pwa-register`. Without the alias, importing it fails with a resolve
      // error — which reads the same as "no service worker was registered", the exact
      // distinction `remote.guard.test.tsx` exists to make. The stub registers from a `window`
      // `load` listener because the real one does; see the comment in the file.
      'virtual:pwa-register': fileURLToPath(
        new URL('./src/test/pwaRegisterStub.ts', import.meta.url),
      ),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Vitest 4 no longer excludes dist/ by default.
    exclude: ['**/node_modules/**', '**/dist/**'],
    // jsdom >=28 dropped the ResourceLoader export Vitest still imports, so setting
    // environmentOptions.jsdom.userAgent throws. Use jsdom's `resources: { userAgent }`.
  },
});
