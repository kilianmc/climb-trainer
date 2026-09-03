// @vitest-environment node
// Needs no DOM, and under jsdom `import.meta.url` is an http: URL that fileURLToPath rejects.
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path/posix';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * Properties of the BUILT output that have no source-level substitute.
 *
 * ## Why this reads `dist/` when `publicRoutes.test.ts` deliberately stopped doing so
 *
 * CLAUDE.md records that an ordering dependency on `build` was *removed* from
 * `publicRoutes.test.ts`, because the fact it guards (a route file exists and is unguarded) is
 * readable from the sources, so depending on a build order made a security guard weaker for no
 * gain. **The invariant here is the opposite shape.** "No `:root` reaches kilianmc.com" is not a
 * property of any source file — it is a property of *which bundle a declaration lands in*, and
 * `@use` is what decides that. A per-source-file scan with per-file exemptions was measurably
 * blind to it: adding one line, `@use 'global';`, to `app.scss` emits `:root{…}` and
 * `body{background:…}` straight into the remote's stylesheet with the whole gate green.
 *
 * So the ordering dependency is accepted, and it FAILS LOUDLY rather than skipping — `dist/` is
 * missing only if `build` has not run, which the gate and CI both do first. A guard that skips
 * itself when its input is absent is a guard that reports success for having looked at nothing.
 *
 * ## How the remote's stylesheet is identified
 *
 * The MF Vite plugin emits **no** `mf-manifest.json` (checked on the installed one: `dist/` has no
 * `.json` at all), so there is nothing authoritative to read and globbing `assets/*.css` would
 * guess. It is derived from the import graph instead, which is exactly what the browser does:
 *
 *   1. `dist/remoteEntry.js` is the published entry — the name is pinned by `vite.config.ts`'s
 *      `filename` and by `vercel.json`'s ACAO rule, so it is not a guess. It is a stub that
 *      statically imports one chunk under `assets/`.
 *   2. Walk every `./x.js` specifier, static and dynamic, transitively from there.
 *   3. Collect every `.css` literal in the reachable chunks. Vite records a lazily-imported
 *      chunk's stylesheets as plain relative paths in its `__vite__mapDeps` table, and MF's
 *      generated `./App` loader turns them into cross-origin `<link>`s at `get('./App')` time —
 *      the mechanism CLAUDE.md describes as failing with "Unable to preload CSS" when the ACAO
 *      header is missing. So the literals are findable, and they are what the shell loads.
 */
const DIST = fileURLToPath(new URL('../dist/', import.meta.url));

function distFile(rel: string): string {
  const path = `${DIST}${rel}`;
  if (!existsSync(path)) {
    throw new Error(
      `web/dist/${rel} is missing. This guard asserts properties of the BUILT output, so ` +
        `\`npm --prefix web run build\` must run first — \`check:web\` and CI both build before ` +
        `test (issue #26). It fails rather than skipping on purpose.`,
    );
  }
  return readFileSync(path, 'utf8');
}

/** The remote's reachable chunks and the stylesheets they name, derived per the comment above. */
function remoteGraph(): { chunks: string[]; css: string[] } {
  const entry = 'remoteEntry.js';
  const seen = new Set<string>();
  const css = new Set<string>();
  const queue = [entry];

  while (queue.length > 0) {
    const rel = queue.shift();
    if (rel === undefined || seen.has(rel)) continue;
    seen.add(rel);
    const source = distFile(rel);
    const here = dirname(rel);

    for (const [, spec] of source.matchAll(/["'`](\.\/[^"'`\s]+?\.js)["'`]/g)) {
      const next = join(here, spec ?? '');
      // Skipped rather than thrown on: the MF runtime also builds entry URLs at runtime, so not
      // every `.js` literal in a chunk is a real sibling chunk. The reachable-count assertion
      // below is what stops this from silently degrading to "walked nothing".
      if (existsSync(`${DIST}${next}`)) queue.push(next);
    }
    for (const [, raw] of source.matchAll(/["'`]((?:\.\/)?[^"'`\s]+?\.css)["'`]/g)) {
      const spec = raw ?? '';
      // Two shapes occur. Vite's `__vite__mapDeps` table records paths relative to the build
      // ROOT (`assets/x.css`), because that is what the browser resolves against `base`; an
      // importer-relative `./x.css` would resolve against the chunk. Try both, and FAIL if a
      // literal resolves to nothing — a silently dropped stylesheet is an unchecked stylesheet.
      const resolved = (spec.startsWith('./') ? [join(here, spec)] : [spec, join(here, spec)]).find(
        (candidate) => existsSync(`${DIST}${candidate}`),
      );
      expect(
        resolved,
        `stylesheet literal "${spec}" in ${rel} matches no file in dist/`,
      ).toBeDefined();
      if (resolved !== undefined) css.add(resolved);
    }
  }

  expect(seen.size, 'the walk from remoteEntry.js reached almost no chunks').toBeGreaterThan(5);
  expect(
    [...css],
    'no stylesheet was found in the remote graph — the derivation above has broken, ' +
      'not the CSS. Do NOT relax this into a skip.',
  ).not.toEqual([]);
  return { chunks: [...seen], css: [...css] };
}

const GRAPH = remoteGraph();

/**
 * Every selector list in a stylesheet, at-rules descended into rather than treated as opaque so
 * a `:root` inside `@media (prefers-color-scheme: dark)` cannot hide. At-rule preludes contain
 * `@` and are excluded by the character class; the `}`/`{` boundaries are what pick up a
 * selector that follows another rule or opens inside an at-rule block.
 */
function selectorLists(css: string): string[] {
  return [...css.matchAll(/(?:^|\}|\{)\s*([^{}@]+?)\s*\{/g)].map(([, list]) => list ?? '');
}

const hasRootSelector = (css: string) => /:root\b/.test(css);
const hasFixedPosition = (css: string) => /position\s*:\s*fixed\b/.test(css);
const unscopedSelectors = (css: string) =>
  selectorLists(css).filter((list) =>
    list.split(',').some((one) => !one.trim().startsWith('.ct-app')),
  );

describe('the stylesheet the federated mount loads', () => {
  const sheets = GRAPH.css;

  it('is identified, and is a real file', () => {
    for (const sheet of sheets) expect(distFile(sheet).length).toBeGreaterThan(100);
  });

  it.each(sheets)('%s scopes every selector under .ct-app', (sheet) => {
    // This is the one that matters. In the federated mount this file is injected into
    // kilianmc.com's document, so anything outside `.ct-app` restyles the live portfolio —
    // off-repo blast radius, and nothing on this side would fail.
    expect(unscopedSelectors(distFile(sheet))).toEqual([]);
  });

  it.each(sheets)('%s declares no :root and positions nothing fixed', (sheet) => {
    const css = distFile(sheet);
    expect(hasRootSelector(css)).toBe(false);
    // A `fixed` element in the shell is positioned against kilianmc.com's viewport, floating
    // over the portfolio's own chrome. Only the `main.tsx`-only bundle may use it.
    expect(hasFixedPosition(css)).toBe(false);
  });

  it('positive control: each detector sees its own violation, and the scope check is not vacuous', () => {
    // Every assertion above passes on an empty list, which is indistinguishable from a broken
    // parser. These are the exact emissions that `@use 'global';` in `app.scss` would add to
    // the file under test.
    expect(hasRootSelector(':root{color-scheme:light dark}')).toBe(true);
    expect(hasFixedPosition('.x{position:fixed;inset:auto 0 0}')).toBe(true);
    expect(unscopedSelectors('body{margin:0}')).toEqual(['body']);
    expect(unscopedSelectors('@media (prefers-color-scheme:dark){:root{--x:1}}')).toEqual([
      ':root',
    ]);
    expect(unscopedSelectors('html .ct-app{color:red}')).toEqual(['html .ct-app']);
    // A comma list is only clean if EVERY part is scoped.
    expect(unscopedSelectors('.ct-app__a,body{color:red}')).toEqual(['.ct-app__a,body']);
    // …and the real thing must be seen as clean, or the check above is passing by accident.
    expect(unscopedSelectors('.ct-app *,.ct-app *::before{box-sizing:border-box}')).toEqual([]);
    expect(
      selectorLists('@container ct-app (min-inline-size:34rem){.ct-app__bento{gap:1rem}}'),
    ).toEqual(['.ct-app__bento']);
  });
});

/**
 * `--ct-bg` has to be repeated as a literal in three places CSS cannot reach — the manifest's
 * `background_color` and `theme_color`, and the two scheme-scoped `theme-color` metas. Nothing
 * else notices when a retuned background leaves the browser chrome and the install splash a
 * different colour from the app.
 *
 * Asserted against the EFFECTIVE values in `dist/`, not against the `LIGHT_BG` constant: an
 * earlier version matched the constant, which left `background_color: '#fff'` written literally
 * beside it perfectly green.
 */
describe('the values duplicated outside the stylesheets', () => {
  const tokens = readFileSync(
    fileURLToPath(new URL('./styles/_tokens.scss', import.meta.url)),
    'utf8',
  );

  function bg(scheme: 'light' | 'dark'): string {
    const found = new RegExp(
      String.raw`@mixin ${scheme}-values \{[^}]*--ct-bg:\s*(#[0-9a-fA-F]{6});`,
    ).exec(tokens)?.[1];
    expect(found, `no --ct-bg in the ${scheme} token block`).toMatch(/^#[0-9a-fA-F]{6}$/);
    return (found ?? '').toLowerCase();
  }

  it('parsed both schemes, so the assertions below are not comparing undefined', () => {
    expect(bg('light')).not.toBe(bg('dark'));
  });

  it("matches the built manifest's background_color and theme_color", () => {
    const manifest = JSON.parse(distFile('manifest.webmanifest')) as Record<string, unknown>;
    expect(manifest.background_color).toBe(bg('light'));
    expect(manifest.theme_color).toBe(bg('light'));
    // The service worker is registered against these; a wrong scope silently narrows what it
    // controls, and a wrong start_url breaks the installed launcher entry.
    expect(manifest.scope).toBe('/');
    expect(manifest.start_url).toBe('/');
  });

  it('matches both theme-color metas in the built index.html', () => {
    const html = distFile('index.html');
    for (const scheme of ['light', 'dark'] as const) {
      const meta = new RegExp(
        String.raw`name="theme-color" media="\(prefers-color-scheme: ${scheme}\)" content="(#[0-9a-fA-F]{6})"`,
      ).exec(html)?.[1];
      expect(meta?.toLowerCase(), `no ${scheme} theme-color meta`).toBe(bg(scheme));
    }
  });
});

/** That everything `dist/index.html` boots stays precached — the reasoning is in the archive,
 * under *PWA — only the decisions a reader would otherwise reverse*. */
type PrecacheEntry = { url: string; revision: string | null };

/** Named, and taking source text, so the positive control can run the real parser. */
function precacheEntries(sw: string): PrecacheEntry[] {
  return [...sw.matchAll(/\{url:"([^"]+)",revision:(null|"[0-9a-f]{32}")\}/g)].map(
    ([, url, revision]) => ({
      url: url ?? '',
      revision: revision === 'null' ? null : (revision ?? '').slice(1, -1),
    }),
  );
}

/** What the browser fetches to boot, root-relative so it compares against a manifest `url`. */
function bootHrefs(html: string): string[] {
  const entry = [...html.matchAll(/<script[^>]*\btype="module"[^>]*\bsrc="([^"]+)"/g)];
  const linked = [
    ...html.matchAll(/<link[^>]*\brel="(?:modulepreload|stylesheet)"[^>]*\bhref="([^"]+)"/g),
  ];
  return [...entry, ...linked].map(([, href]) => (href ?? '').replace(/^\//, ''));
}

/** The URLs carrying no content hash, derived rather than listed so a new icon is covered. */
function unhashedUrls(html: string, webmanifest: string): string[] {
  const { icons = [] } = JSON.parse(webmanifest) as { icons?: { src?: string }[] };
  const rels = /<link[^>]*\brel="(?:icon|apple-touch-icon)"[^>]*\bhref="([^"]+)"/g;
  const named = [...html.matchAll(rels)].map(([, href]) => href ?? '');
  const all = ['index.html', 'remoteEntry.js', 'manifest.webmanifest']
    .concat(
      icons.map((icon) => icon.src ?? ''),
      named,
    )
    .map((url) => url.replace(/^\//, ''));
  return [...new Set(all)];
}

// Twice the 613,576 bytes measured today, so a route split moves the count and not this.
const PRECACHE_BYTE_CEILING = 1_250_000;

describe('the precache manifest baked into dist/sw.js', () => {
  const entries = precacheEntries(distFile('sw.js'));
  const precached = new Set(entries.map((entry) => entry.url));
  const html = distFile('index.html');
  const hrefs = bootHrefs(html);
  const unhashed = unhashedUrls(html, distFile('manifest.webmanifest'));

  it('parsed a manifest out of the worker, so nothing below passes on an empty list', () => {
    expect(distFile('sw.js')).toContain('.precache(');
    // 43 today.
    expect(entries.length, 'no precache entry was parsed out of dist/sw.js').toBeGreaterThan(30);
  });

  it.each(unhashed)('precaches %s, and with a real revision', (url) => {
    const entry = entries.find((one) => one.url === url);
    expect(entry, `${url} carries no content hash and is not precached at all`).toBeDefined();
    expect(
      entry?.revision,
      `${url} is precached with revision:null. Its URL never changes, so that pins an ` +
        `installed app to the copy it first cached, as a widened dontCacheBustURLsMatching would.`,
    ).toMatch(/^[0-9a-f]{32}$/);
  });

  it('parsed the boot hrefs, so the arm below is not iterating an empty list', () => {
    // 22 today: the module script, 19 modulepreloads and 2 stylesheets.
    expect(hrefs.length, 'no boot href was parsed out of dist/index.html').toBeGreaterThan(15);
  });

  it.each(hrefs)('precaches the boot href %s', (href) => {
    expect(precached.has(href), `dist/index.html loads ${href} but it is not precached`).toBe(true);
  });

  it.each(GRAPH.chunks)('precaches %s, reachable from remoteEntry.js', (chunk) => {
    expect(
      precached.has(chunk),
      `${chunk} is reachable from remoteEntry.js but is not precached`,
    ).toBe(true);
  });

  it('precaches an app, not the whole of dist/', () => {
    // A missing manifest URL throws here rather than being scored as zero bytes.
    const bytes = entries.reduce((sum, entry) => sum + statSync(`${DIST}${entry.url}`).size, 0);
    expect(bytes, 'nothing was measured').toBeGreaterThan(100_000);
    expect(
      bytes,
      `${bytes} bytes precached. Widening globPatterns to an image extension puts dist/landing/ ` +
        `into a phone's Cache Storage; if this is real growth, re-measure and say so here.`,
    ).toBeLessThan(PRECACHE_BYTE_CEILING);
  });

  it('positive control: both revision shapes are seen, and a quoted-key list is not', () => {
    const minified =
      'T={},function(e){E().precache(e)}([{url:"remoteEntry.js",' +
      'revision:"79242c895399ca4beaa955aeb8f95e35"},{url:"assets/router-Cm_t8u6o.js",' +
      'revision:null}])';
    expect(precacheEntries(minified)).toEqual([
      { url: 'remoteEntry.js', revision: '79242c895399ca4beaa955aeb8f95e35' },
      { url: 'assets/router-Cm_t8u6o.js', revision: null },
    ]);
    expect(precacheEntries('[{"url":"remoteEntry.js","revision":null}]')).toEqual([]);
    expect(precacheEntries('[{url:"a.js",revision:"nope"}]')).toEqual([]);
    expect(
      bootHrefs(
        '<script type="module" crossorigin src="/assets/a.js"></script>' +
          '<link rel="modulepreload" crossorigin href="/remoteEntry.js">' +
          '<link rel="stylesheet" crossorigin href="/assets/b.css">',
      ),
    ).toEqual(['assets/a.js', 'remoteEntry.js', 'assets/b.css']);
    // An icon is not a boot href, and `unhashedUrls` is what covers it instead.
    expect(bootHrefs('<link rel="icon" href="/favicon.ico" sizes="48x48" />')).toEqual([]);
    expect(
      unhashedUrls('<link rel="apple-touch-icon" href="/a.png" />', '{"icons":[{"src":"b.png"}]}'),
    ).toEqual(['index.html', 'remoteEntry.js', 'manifest.webmanifest', 'b.png', 'a.png']);
  });
});
