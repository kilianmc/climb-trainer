import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
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
