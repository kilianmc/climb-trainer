import { readFileSync, readdirSync } from 'node:fs';
import { cwd } from 'node:process';

import { describe, expect, it } from 'vitest';

import { stripComments } from '../test/sourceScan';

/**
 * Closed design decisions, scanned at SOURCE level. **There is no stylelint in this repo**, so
 * this is not a lint rule restated; adding a whole toolchain to enforce three project-specific
 * decisions would cost more than it returns.
 *
 * ⚠️ **This is the weaker half of two guards, and it is not a substitute for the other.** A
 * per-file source scan cannot see the invariant that actually matters — *which bundle* a
 * declaration lands in. `distContract.test.ts` asserts that on the built stylesheet the
 * federated mount loads, and it is what catches `@use 'global';` in `app.scss`. What this file
 * adds on top is reach: it sees a `backdrop-filter` sitting in a partial that nothing `@use`s
 * yet, and an inline `position: 'fixed'` in a component, neither of which appears in any CSS.
 *
 * - **`backdrop-filter` / translucent glass** — evaluated and REJECTED by Kilian on 2026-08-12:
 *   a blur pass every frame on a phone that is awake mid-session, and worse legibility at arm's
 *   length with chalky hands. A future agent "helpfully improving" the look is the realistic
 *   regression, which is why the rejection is asserted and not merely written down.
 * - **`:root` outside `global.scss`** — `global.scss` is imported by `main.tsx` alone; every
 *   other stylesheet can reach the route tree, and in the federated mount that is injected into
 *   kilianmc.com's document.
 * - **`@import`** — deprecated in Dart Sass, and it re-emits a partial once per importer, so the
 *   token block would be duplicated into every consumer's output.
 * - **Inline `position: 'fixed'` in a component** — a `fixed` element in the federated mount is
 *   positioned against kilianmc.com's viewport. React style props never become CSS, so
 *   `distContract.test.ts` is structurally unable to see this one; only a source scan can.
 *   (`position: fixed` in a *stylesheet* is deliberately NOT scanned here — it is legitimate in
 *   `update-bar.scss` and illegitimate only once it reaches the remote bundle, which is a
 *   question about the bundle, not the file.)
 *
 * `process.cwd()`, not `import.meta.url`: under jsdom the latter is an `http://localhost` URL.
 */
const SRC = `${cwd()}/src`;

/** The document-level file, imported by `main.tsx` alone. The one `:root` exemption. */
const GLOBAL = 'global.scss';

/** Recursive: an earlier version read one directory and was blind to `src/ui/*.scss`. */
function sources(extension: string, dir = SRC): [string, string][] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry): [string, string][] =>
    entry.isDirectory()
      ? sources(extension, `${dir}/${entry.name}`)
      : entry.isFile() && entry.name.endsWith(extension)
        ? [
            [
              `${dir}/${entry.name}`.slice(SRC.length + 1),
              readFileSync(`${dir}/${entry.name}`, 'utf8'),
            ],
          ]
        : [],
  );
}

const hasBackdropFilter = (source: string) => /backdrop-filter\s*:/.test(stripComments(source));
const hasRootSelector = (source: string) => /(^|[\s,{}]):root\b/.test(stripComments(source));
const hasSassImport = (source: string) => /@import\b/.test(stripComments(source));
const hasInlineFixed = (source: string) =>
  /position\s*:\s*['"`]fixed['"`]/.test(stripComments(source));

const sheets = sources('.scss');
const components = sources('.tsx');

describe('the stylesheets', () => {
  it('are all found, recursively', () => {
    // Without this every `it.each` below would vacuously pass on an empty list — the exact
    // failure mode recorded in CLAUDE.md for the route-enumeration walk.
    const names = sheets.map(([name]) => name);
    expect(names).toContain(`styles/${GLOBAL}`);
    expect(names).toContain('styles/_tokens.scss');
    expect(sheets.length).toBeGreaterThanOrEqual(9);
    expect(components.length).toBeGreaterThanOrEqual(10);
  });

  it.each(sheets)('%s uses no backdrop-filter and no @import', (_name, source) => {
    expect(hasBackdropFilter(source)).toBe(false);
    expect(hasSassImport(source)).toBe(false);
  });

  it.each(sheets.filter(([name]) => !name.endsWith(GLOBAL)))(
    '%s declares no :root',
    (_name, source) => {
      expect(hasRootSelector(source)).toBe(false);
    },
  );

  it.each(components)('%s positions nothing fixed inline', (_name, source) => {
    expect(hasInlineFixed(source)).toBe(false);
  });

  it('keeps the one exemption real rather than merely unused', () => {
    // If `global.scss` lost its `:root` the rule above would still pass and the exemption would
    // be silently dead — as would this file's claim about where document styles live.
    const global = sheets.find(([name]) => name.endsWith(GLOBAL))?.[1] ?? '';
    expect(hasRootSelector(global)).toBe(true);
  });
});

describe('positive control', () => {
  it.each([
    ['backdrop-filter', hasBackdropFilter, '.x { backdrop-filter: blur(12px); }'],
    [':root', hasRootSelector, ':root { --ct-bg: #fff; }'],
    ['@import', hasSassImport, "@import 'tokens';"],
    ['inline fixed', hasInlineFixed, "<div style={{ position: 'fixed', inset: 0 }} />"],
  ])(
    'the %s detector sees its own violation, and ignores it in a comment',
    (_rule, detect, bad) => {
      expect(detect(bad)).toBe(true);
      expect(detect(`// never do this: ${bad}\n`)).toBe(false);
      expect(detect(`/* never do this:\n${bad}\n*/\n`)).toBe(false);
    },
  );

  it('does not confuse `:root` with a class that merely ends in it', () => {
    expect(hasRootSelector('.ct-app__root { color: red; }')).toBe(false);
  });

  it('sees a violation in a NESTED source file, not just a top-level one', () => {
    // The recursion is the fix for a real blind spot, so it gets its own control: the scanned
    // set must contain something from a subdirectory of `src/`.
    expect(components.map(([name]) => name)).toContain('ui/UpdateBar.tsx');
    expect(components.some(([name]) => name.includes('/'))).toBe(true);
  });
});
