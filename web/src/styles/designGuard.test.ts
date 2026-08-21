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
 * - **Viewport units in a stylesheet** — `vh`/`vw`/`dvh`/`svh`/`lvh` and their `v*`/`vmin`/`vmax`
 *   relatives. CLAUDE.md states this as a hard rule beside `position: fixed` ("no `position: fixed`
 *   and no viewport units anywhere the route tree can reach") and it had **no detector at all**
 *   until this line: both mounts share the route tree, and in the federated one a viewport unit
 *   measures kilianmc.com's window, not the space the app was given. `distContract.test.ts` greps
 *   the built remote stylesheet for `position: fixed` and, deliberately, not for these — so this
 *   is the only guard, and it is stricter on purpose: it covers partials nothing `@use`s yet.
 *   **There is no exemption**, not even for the `main.tsx`-only sheets that may use
 *   `position: fixed`, because neither of them wants one today and a dead exemption is worse than
 *   no exemption. If the update bar ever needs `100dvh`, that is the moment to add one — with a
 *   control, like the `:root` exemption has.
 *   **The `.tsx` sources are scanned too**, because an inline `style={{ blockSize: '100vh' }}`
 *   never becomes CSS and would otherwise pass the entire gate — the same blind spot that made
 *   the inline-`fixed` scan necessary. `sizes="…"` attributes are stripped first: the two
 *   `sizes="100vw"` hints on `<LandingPicture>` are resource selection, not layout (in the shell
 *   they over-estimate and may fetch one rung too many; they can never move a box).
 *   ⚠️ **The real limitation, stated correctly.** The pattern needs a digit adjacent to the
 *   unit, so anything COMPUTED slips past: `#{$h}vh` in Sass, and `` `${h}vh` ``,
 *   `'100' + 'vh'` or `String(n) + 'vh'` in a component. Chasing those means parsing Sass and
 *   evaluating JS, which this file will not do. For the Sass half `distContract.test.ts` sees
 *   the emitted CSS and would still catch a `fixed`, though not a viewport unit — it does not
 *   scan for those. **For the `.tsx` half there is NO backstop at all**: an inline style never
 *   becomes CSS, so nothing else in the gate can see it. An earlier version of this comment
 *   claimed `distContract` covered it, which was exactly false for the half added with it.
 * - **`window.innerHeight` / `innerWidth` / `visualViewport` in a component** — the same bug in
 *   JavaScript, and unlike a computed unit it is greppable. Measuring the window and writing
 *   the result into a style is how a "full height" screen gets built in React, and in the
 *   federated mount that window is kilianmc.com's. Not banned in a `main.tsx`-only module for
 *   the same reason `fixed` is not; there is no such module with a `.tsx` extension today, so
 *   there is no exemption to keep alive.
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
// A DIGIT before the unit, so `.overview`, `overflow` and `--ct-view-x` are not viewport units;
// a word boundary after it, so `100vhx` is not one either. `q` is not in the list: it is an
// absolute length, not a viewport-relative one.
// `i`, because `100VH` is the same declaration.
const VIEWPORT_UNIT =
  /\d\s*(vh|vw|vmin|vmax|vi|vb|dvh|dvw|dvi|dvb|dvmin|dvmax|svh|svw|svi|svb|svmin|svmax|lvh|lvw|lvi|lvb|lvmin|lvmax)\b/i;
const hasViewportUnit = (source: string) => VIEWPORT_UNIT.test(stripComments(source));

/** A `sizes` attribute in JSX or HTML, quoted any of the three ways. */
const SIZES_ATTRIBUTE = /sizes\s*=\s*(["'`])[^"'`]*\1/g;

/** The same rule for components, minus the one place a viewport unit is legitimate. */
const hasViewportUnitInMarkup = (source: string) =>
  hasViewportUnit(stripComments(source).replace(SIZES_ATTRIBUTE, ''));

// `window.` is not required: `const { innerHeight } = window` and a bare `innerHeight` are
// the same read, and both are how the shell's viewport leaks into a remote's layout.
const VIEWPORT_MEASUREMENT = /\b(innerHeight|innerWidth|outerHeight|outerWidth|visualViewport)\b/;
const measuresTheViewport = (source: string) => VIEWPORT_MEASUREMENT.test(stripComments(source));

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

  it.each(sheets)('%s sizes nothing against the viewport', (_name, source) => {
    expect(hasViewportUnit(source)).toBe(false);
  });

  it.each(components)('%s sizes nothing against the viewport inline', (_name, source) => {
    expect(hasViewportUnitInMarkup(source)).toBe(false);
  });

  it.each(components)('%s does not measure the window', (_name, source) => {
    expect(measuresTheViewport(source)).toBe(false);
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
    ['viewport unit', hasViewportUnit, '.x { min-block-size: 100vh; }'],
    ['inline viewport unit', hasViewportUnitInMarkup, "<div style={{ blockSize: '100vh' }} />"],
    ['window measurement', measuresTheViewport, 'const h = window.innerHeight;'],
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

  it.each([
    ['100dvh', '.x { block-size: 100dvh; }'],
    ['calc with svh', '.x { block-size: calc(100svh - 2rem); }'],
    ['a fractional vw', '.x { inline-size: 33.3vw; }'],
    ['vmin', '.x { padding: 2vmin; }'],
  ])('the viewport detector sees %s', (_label, bad) => {
    expect(hasViewportUnit(bad)).toBe(true);
  });

  it('ignores a viewport unit inside a `sizes` attribute, and only there', () => {
    // `sizes` is resource selection: it picks which file to download, never a box size.
    expect(hasViewportUnitInMarkup('<img sizes="100vw" alt="" />')).toBe(false);
    expect(hasViewportUnitInMarkup('<img sizes="(min-width: 40rem) 50vw, 100vw" alt="" />')).toBe(
      false,
    );
    // The exemption must not leak to anything else on the same line.
    expect(
      hasViewportUnitInMarkup('<img sizes="100vw" style={{ inlineSize: \'100vw\' }} alt="" />'),
    ).toBe(true);
  });

  it('sees an UPPERCASE unit, which the missing `i` flag would have let through', () => {
    expect(hasViewportUnit('.x { block-size: 100VH; }')).toBe(true);
  });

  it.each([
    ['a destructured read', 'const { innerHeight } = window;'],
    ['a bare global', 'const h = innerHeight - 40;'],
    ['the visual viewport', 'window.visualViewport?.addEventListener("resize", onResize);'],
  ])('the window detector sees %s', (_label, bad) => {
    expect(measuresTheViewport(bad)).toBe(true);
  });

  it.each([
    ['a similarly-named property', 'const h = element.clientHeight;'],
    ['a container query read', 'const h = entry.contentBoxSize;'],
    ['a word merely containing it', 'const innerHeightLabel = "tall";'],
  ])('the window detector does not fire on %s', (_label, good) => {
    expect(measuresTheViewport(good)).toBe(false);
  });

  it('records what the unit pattern CANNOT see, so nobody trusts it further than it goes', () => {
    // A digit must be adjacent to the unit. Every one of these is a real viewport unit that
    // reaches the DOM and that this file does not catch — see the docstring.
    expect(hasViewportUnitInMarkup('<div style={{ blockSize: `${h}vh` }} />')).toBe(false);
    expect(hasViewportUnitInMarkup("<div style={{ blockSize: '100' + 'vh' }} />")).toBe(false);
    expect(hasViewportUnit('.x { block-size: #{$h}vh; }')).toBe(false);
  });

  it.each([
    ['a word ending in the letters', '.ct-app__overview { overflow: hidden; }'],
    ['a custom property that merely contains them', '.x { --ct-view-gap: 1rem; }'],
    ['every unit this project does use', '.x { padding: 1rem 2px 3% 4em; block-size: 5ch; }'],
    ['an env() inset', '.x { padding-block-end: max(1rem, env(safe-area-inset-bottom)); }'],
  ])('the viewport detector does not fire on %s', (_label, good) => {
    expect(hasViewportUnit(good)).toBe(false);
  });

  it('sees a violation in a NESTED source file, not just a top-level one', () => {
    // The recursion is the fix for a real blind spot, so it gets its own control: the scanned
    // set must contain something from a subdirectory of `src/`.
    expect(components.map(([name]) => name)).toContain('ui/UpdateBar.tsx');
    expect(components.some(([name]) => name.includes('/'))).toBe(true);
  });
});
