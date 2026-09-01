import { readFileSync, readdirSync } from 'node:fs';
import { cwd } from 'node:process';

import { describe, expect, it } from 'vitest';

import { stripComments } from '../test/sourceScan';

/**
 * Closed design decisions, scanned at SOURCE level. **There is no stylelint in this repo**, so
 * this is not a lint rule restated.
 *
 * ⚠️ **This is the WEAKER half of two guards and is not a substitute for the other.** A per-file
 * scan cannot see the invariant that matters — *which bundle* a declaration lands in — which
 * `distContract.test.ts` asserts on the built remote stylesheet and is what catches
 * `@use 'global';` in `app.scss`. What this adds is reach: a `backdrop-filter` in a partial
 * nothing `@use`s yet, and an inline `position: 'fixed'` in a component, which is never CSS.
 *
 * - **`backdrop-filter` / translucent glass** — evaluated and REJECTED (Kilian, 2026-08-12): a
 *   blur pass every frame on a phone awake mid-session, and worse legibility at arm's length
 *   with chalky hands. A future agent "helpfully improving" the look is the realistic regression.
 * - **`:root` outside `global.scss`** — every other stylesheet can reach the route tree, which
 *   in the federated mount is injected into kilianmc.com's document.
 * - **`@import`** — deprecated in Dart Sass, and it re-emits a partial once per importer.
 * - **Viewport units in a stylesheet** (`vh`/`vw`/`dvh`/`svh`/`lvh`/`vmin`/`vmax`) — a hard rule
 *   beside `position: fixed` that had **no detector at all** until this line. **No exemption**,
 *   not even for the `main.tsx`-only sheets: neither wants one, and a dead exemption is worse
 *   than none. The `.tsx` sources are scanned too, because an inline
 *   `style={{ blockSize: '100vh' }}` never becomes CSS and would otherwise pass the whole gate;
 *   `sizes="…"` is stripped first, since `<LandingPicture>`'s `100vw` is resource selection and
 *   can never move a box. ⚠️ **The pattern needs a digit adjacent to the unit, so anything
 *   COMPUTED slips past** — `#{$h}vh`, `` `${h}vh` ``, `'100' + 'vh'`. For the Sass half
 *   `distContract` would still catch a `fixed` (not a unit); **for the `.tsx` half there is NO
 *   backstop at all**, because an inline style never becomes CSS.
 * - **`window.innerHeight` / `innerWidth` / `visualViewport` in a component** — the same bug in
 *   JavaScript, and unlike a computed unit it is greppable. Measuring the window and writing it
 *   into a style is how a "full height" screen gets built in React, and in the federated mount
 *   that window is kilianmc.com's.
 * - **`matchMedia` with a WIDTH feature** — the width `@media` rule above, rewritten in
 *   TypeScript: `matchMedia('(min-width: 64rem)')` asks the same wrong window. The CALL is
 *   legitimate and stays; only the query text is judged, which is why the five asking
 *   `prefers-color-scheme`, `prefers-reduced-motion` and `display-mode` pass. Scanned over
 *   `.ts` and `.tsx` minus `*.test.*` — nothing in a test ships a layout decision, and
 *   without that exclusion this file's own controls would red it. ⚠️ **Only a query written
 *   literally at the call site is visible**: `matchMedia(query)` and `'(min-' + 'width: …)'`
 *   slip past, the same gap as the computed unit above (an interpolated *threshold* is still
 *   caught — the feature name stays literal). If a width genuinely must reach JS, observe
 *   `.ct-app` with a `ResizeObserver`; that is the app's own box in both mounts.
 * - **Inline `position: 'fixed'` in a component** — positioned against kilianmc.com's viewport in
 *   the federated mount, and structurally invisible to `distContract.test.ts`. `position: fixed`
 *   in a *stylesheet* is deliberately NOT scanned: it is illegitimate only once it reaches the
 *   remote bundle, which is a question about the bundle, not about a source file.
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

/** Each `@media` prelude on its own. `@container` cannot match the `\b` after `@media`, and a
 *  Sass interpolation only truncates the REPORTED text — the feature name comes first. */
const MEDIA_PRELUDE = /@media\b([^{]*)\{/g;

/** A width asked of the VIEWPORT, range form and logical spelling included. The four screen
 *  sizes are `@container ct-app` sizes instead, and `_sizes.scss` is where that is argued. */
const WIDTH_FEATURE = /\b(?:min-|max-)?(?:width|inline-size)\b/;

const widthMediaQueries = (source: string): string[] =>
  [...stripComments(source).matchAll(MEDIA_PRELUDE)]
    .map(([, prelude]) => (prelude ?? '').trim())
    .filter((prelude) => WIDTH_FEATURE.test(prelude));

/** A `sizes` attribute in JSX or HTML, quoted any of the three ways. */
const SIZES_ATTRIBUTE = /sizes\s*=\s*(["'`])[^"'`]*\1/g;

/** The same rule for components, minus the one place a viewport unit is legitimate. */
const hasViewportUnitInMarkup = (source: string) =>
  hasViewportUnit(stripComments(source).replace(SIZES_ATTRIBUTE, ''));

// `window.` is not required: `const { innerHeight } = window` and a bare `innerHeight` are
// the same read, and both are how the shell's viewport leaks into a remote's layout.
const VIEWPORT_MEASUREMENT = /\b(innerHeight|innerWidth|outerHeight|outerWidth|visualViewport)\b/;
const measuresTheViewport = (source: string) => VIEWPORT_MEASUREMENT.test(stripComments(source));

/** A `matchMedia` query written literally at the call site, captured. Bare and `window.`-
 *  prefixed read alike, exactly as `VIEWPORT_MEASUREMENT` above. */
const MATCH_MEDIA_CALL = /matchMedia\s*\(\s*(['"`])([^'"`]*)\1/g;

const widthMatchMedia = (source: string): string[] =>
  [...stripComments(source).matchAll(MATCH_MEDIA_CALL)]
    .map(([, , query]) => (query ?? '').trim())
    .filter((query) => WIDTH_FEATURE.test(query));

const sheets = sources('.scss');
const components = sources('.tsx');
// `sources` matches on `endsWith`, so `.ts` and `.tsx` are disjoint sets and both are needed.
const TEST_FILE = /\.test\.tsx?$/;
const shipped = [...sources('.ts'), ...sources('.tsx')].filter(([name]) => !TEST_FILE.test(name));

describe('the stylesheets', () => {
  it('are all found, recursively', () => {
    // Without this every `it.each` below would vacuously pass on an empty list — the exact
    // failure mode recorded in CLAUDE.md for the route-enumeration walk.
    const names = sheets.map(([name]) => name);
    expect(names).toContain(`styles/${GLOBAL}`);
    expect(names).toContain('styles/_tokens.scss');
    expect(sheets.length).toBeGreaterThanOrEqual(9);
    expect(components.length).toBeGreaterThanOrEqual(10);
    // `.ts` too, or the two legitimate `matchMedia` calls below would go unscanned and the
    // rule's negative controls would be synthetic rather than live in-repo.
    const shippedNames = shipped.map(([name]) => name);
    expect(shippedNames).toContain('theme.ts');
    expect(shippedNames).toContain('session/wakeLock.ts');
    expect(shippedNames).not.toContain('styles/designGuard.test.ts');
    expect(shipped.length).toBeGreaterThanOrEqual(40);
  });

  it.each(sheets)('%s uses no backdrop-filter and no @import', (_name, source) => {
    expect(hasBackdropFilter(source)).toBe(false);
    expect(hasSassImport(source)).toBe(false);
  });

  it.each(sheets)('%s sizes nothing against the viewport', (_name, source) => {
    expect(hasViewportUnit(source)).toBe(false);
  });

  it.each(sheets)('%s asks no WIDTH question of the viewport', (_name, source) => {
    expect(widthMediaQueries(source)).toEqual([]);
  });

  it.each(components)('%s sizes nothing against the viewport inline', (_name, source) => {
    expect(hasViewportUnitInMarkup(source)).toBe(false);
  });

  it.each(components)('%s does not measure the window', (_name, source) => {
    expect(measuresTheViewport(source)).toBe(false);
  });

  it.each(shipped)('%s asks matchMedia no WIDTH question', (_name, source) => {
    expect(widthMatchMedia(source)).toEqual([]);
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

  it.each([
    ['min-width', '@media (min-width: 48rem) { .x { color: red } }'],
    ['max-width in a compound query', '@media screen and (max-width: 600px) { .x { color: red } }'],
    ['the range form', '@media (width >= 48rem) { .x { color: red } }'],
    ['the logical spelling', '@media (min-inline-size: 64rem) { .x { color: red } }'],
  ])('the width-media detector sees %s', (_label, bad) => {
    expect(widthMediaQueries(bad)).toHaveLength(1);
    expect(widthMediaQueries(`// never do this: ${bad}\n`)).toEqual([]);
  });

  it.each([
    [
      'the container query that replaces it',
      '@container ct-app (min-inline-size: 64rem) { .x { color: red } }',
    ],
    [
      'a reduced-motion query',
      '@media (prefers-reduced-motion: reduce) { .x { transition: none } }',
    ],
    ['a colour-scheme query', '@media (prefers-color-scheme: dark) { .x { color: red } }'],
    ['a declaration merely naming the property', '.x { min-inline-size: 100%; }'],
  ])('the width-media detector does not fire on %s', (_label, good) => {
    expect(widthMediaQueries(good)).toEqual([]);
  });

  it.each([
    ['min-width', "const wide = window.matchMedia('(min-width: 64rem)').matches;"],
    ['max-width', 'if (matchMedia("(max-width: 600px)").matches) collapse();'],
    ['the range form', 'const wide = window.matchMedia(`(width >= 64rem)`).matches;'],
    ['the logical spelling', "const wide = matchMedia('(min-inline-size: 48rem)').matches;"],
    ['an interpolated THRESHOLD', 'window.matchMedia(`(min-width: ${bp}px)`).matches;'],
  ])('the width-matchMedia detector sees %s', (_label, bad) => {
    expect(widthMatchMedia(bad)).toHaveLength(1);
    expect(widthMatchMedia(`// never do this: ${bad}\n`)).toEqual([]);
  });

  it.each([
    ['the colour-scheme read in `theme.ts`', "window.matchMedia('(prefers-color-scheme: dark)')"],
    ['the reduced-motion read the routes make', "matchMedia('(prefers-reduced-motion: reduce)')"],
    ['the standalone read in `wakeLock.ts`', "window.matchMedia('(display-mode: standalone)')"],
    ['the ResizeObserver that replaces it', 'ro.observe(node); // entry.contentRect.width'],
  ])('the width-matchMedia detector does not fire on %s', (_label, good) => {
    expect(widthMatchMedia(good)).toEqual([]);
  });

  it('records what the matchMedia pattern CANNOT see, for the same reason as the unit one', () => {
    // The feature name has to be literal at the call site. Both of these reach the DOM as a
    // width question and neither is catchable by a source scan — see the docstring.
    expect(widthMatchMedia('const mq = window.matchMedia(query);')).toEqual([]);
    expect(widthMatchMedia("matchMedia('(min-' + 'width: 64rem)')")).toEqual([]);
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
    expect(components.map(([name]) => name)).toContain('ui/ThemeSwitch.tsx');
    expect(components.some(([name]) => name.includes('/'))).toBe(true);
  });
});
