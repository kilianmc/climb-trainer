// @vitest-environment node
// Needs no DOM, and under jsdom `import.meta.url` is an http: URL that fileURLToPath rejects.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { stripComments } from './test/sourceScan';

/** Four VitePWA properties whose breach is SILENT: every check stays green and the damage lands
 * on a visitor's phone. Each `it` below states the rule it enforces and why it matters. */
const CONFIG = stripComments(
  readFileSync(fileURLToPath(new URL('../vite.config.ts', import.meta.url)), 'utf8'),
);

// Read from the SOURCE config, not `dist/sw.js`: `distContract.test.ts` already owns the one
// ordering dependency on `build`, and every property here is stated directly in the config.
/** Each detector takes source text, so the positive controls can run the real thing. */
const hasPromptRegisterType = (s: string) => /registerType:\s*'prompt'/.test(s);
const hasAutoUpdate = (s: string) => /registerType:\s*'autoUpdate'/.test(s);
const hasNullInjectRegister = (s: string) => /injectRegister:\s*null/.test(s);
const hasApiNavigateFallbackDenylist = (s: string) =>
  /navigateFallbackDenylist:\s*\[\s*\/\^\\\/api\\\/\/\s*\]/.test(s);
const hasRuntimeCaching = (s: string) => /\bruntimeCaching\b/.test(s);

describe('the PWA contract in vite.config.ts', () => {
  it('is read from a config that actually has a VitePWA block', () => {
    // Without this every assertion below would pass on an empty string.
    expect(CONFIG).toContain('VitePWA(');
    expect(CONFIG).toContain('navigateFallback:');
  });

  it('activates a new worker itself — `prompt` would wait for an update prompt the app never shows, so a precached build would never be taken up', () => {
    expect(hasAutoUpdate(CONFIG)).toBe(true);
    expect(hasPromptRegisterType(CONFIG)).toBe(false);
  });

  it('injects no registration of its own — anything but null either double-registers alongside `main.tsx` or emits an inline script the CSP `script-src self` blocks', () => {
    expect(hasNullInjectRegister(CONFIG)).toBe(true);
  });

  it('keeps /api out of the navigation fallback — without the denylist the worker answers an API request with index.html, `res.ok` is true, and `apiFetch` throws NotJsonError far from the cause', () => {
    expect(hasApiNavigateFallbackDenylist(CONFIG)).toBe(true);
  });

  it('caches no API response at runtime — `runtimeCaching` would put authenticated JSON in Cache Storage, on disk, where it survives logout and nothing clears it', () => {
    expect(hasRuntimeCaching(CONFIG)).toBe(false);
  });
});

describe('positive control', () => {
  it.each([
    ['registerType: prompt', hasPromptRegisterType, "registerType: 'prompt',"],
    ['registerType: autoUpdate', hasAutoUpdate, "registerType: 'autoUpdate',"],
    ['injectRegister: null', hasNullInjectRegister, 'injectRegister: null,'],
    [
      'navigateFallbackDenylist',
      hasApiNavigateFallbackDenylist,
      'navigateFallbackDenylist: [/^\\/api\\//],',
    ],
    ['runtimeCaching', hasRuntimeCaching, 'runtimeCaching: [{ urlPattern: /^\\/api\\// }],'],
  ])('the %s detector sees its own sample', (_name, detect, sample) => {
    expect(detect(sample)).toBe(true);
  });

  it('ignores every one of those samples inside a comment', () => {
    // This repo's stylesheets and this very config explain these rules in prose, so a detector
    // that read comments would report the explanation as the violation.
    const commented = [
      "// registerType: 'prompt',",
      '// runtimeCaching: [{ urlPattern: /^\\/api\\// }],',
      '/* runtimeCaching is forbidden */',
    ].join('\n');

    expect(hasPromptRegisterType(stripComments(commented))).toBe(false);
    expect(hasRuntimeCaching(stripComments(commented))).toBe(false);
    // …and the real config's own prose is exactly that case: it names `runtimeCaching` in a
    // comment explaining why it is not used.
    const raw = readFileSync(fileURLToPath(new URL('../vite.config.ts', import.meta.url)), 'utf8');
    expect(hasRuntimeCaching(raw)).toBe(true);
    expect(hasRuntimeCaching(stripComments(raw))).toBe(false);
  });
});
