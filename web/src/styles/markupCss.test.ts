// @vitest-environment node
// Needs no DOM, and Sass is a Node API. Under jsdom `import.meta.url` is an `http://localhost`
// URL, which is also why `process.cwd()` is used below rather than a URL-relative path —
// the same reason `designGuard.test.ts` and `contrast.test.ts` give.
import { readFileSync, readdirSync } from 'node:fs';
import { cwd } from 'node:process';

import { compile } from 'sass';
import { describe, expect, it } from 'vitest';

import { stripComments } from '../test/sourceScan';

/**
 * Markup and CSS must describe each other, in BOTH directions: every `ct-app__*` class the
 * components use has a rule behind it, and every `ct-app__*` selector the stylesheet defines is
 * used by something.
 *
 * ⚠️ **A class name in markup with no matching rule fails SILENTLY, and this is the only thing
 * in the gate that can see it.** It happened twice during the onboarding redesign: a scripted
 * rewrite of `_profile.scss` swallowed unrelated rules and left twelve classes unstyled — the
 * select chevron, the checkboxes, the slider rows, the disclosure panels, the grade warning —
 * while `tsc`, ESLint, `designGuard`, `distContract` and `contrast` were all green, and always
 * will be: it is a relationship between two files, not a property of either. Both directions,
 * because the same swallowed span leaves dead selectors when the markup is the half that changed.
 *
 * **The stylesheet is compiled in process** by the `sass` this repo already depends on. A source
 * scan cannot work — the partials use `&__suffix`, so the literal `ct-app__choice` appears
 * nowhere in `_profile.scss`, and resolving it means writing a Sass compiler badly. Reading
 * `dist/` would make the guard depend on a production build for a question that has nothing to
 * do with bundling (which is `distContract.test.ts`'s job, correctly). `app.scss` is the entry:
 * it is the design system and the only stylesheet the federated mount gets. ~150 ms.
 *
 * ⚠️ **One blind spot: INTERPOLATED class names.** `` `ct-app__bento--${area}` `` trips both
 * directions at once, and `INTERPOLATED` below is the narrowest possible exemption for the one
 * place it happens. **The pattern is deliberately NOT loosened to hide it** — matching a
 * trailing `*` means the truncated stem is seen and has to be exempted on purpose, where a
 * pattern that quietly dropped incomplete tokens would drop genuine typos with them. A false
 * positive costs a minute; a false negative costs a broken screen every other check calls green.
 *
 * Every detector is fed a synthetic violation AND a synthetic compliant input. The synthetic
 * names are independent literals, never derived from the sets they test: a control assembled
 * from its own constant would cheerfully confirm a typo to itself.
 */
const SRC = `${cwd()}/src`;

/** The design-system entry. Both mounts load this and nothing else from `styles/`. */
const ENTRY = `${SRC}/styles/app.scss`;

/**
 * Markup side. `*`, not `+`: an interpolation leaves a truncated stem, and the point is to SEE
 * it and exempt it by name rather than to let the pattern swallow it. See the docstring.
 */
const MARKUP_CLASS = /ct-app__[A-Za-z0-9_-]*/g;

/** Stylesheet side. A leading dot, so `container: ct-app/inline-size` is not a class, and `+`,
 *  because a bare `.ct-app__` cannot be a real selector. */
const SELECTOR_CLASS = /\.(ct-app__[A-Za-z0-9_-]+)/g;

/**
 * Test code is not markup. `.test.ts(x)` files carry deliberate fixture strings
 * (`designGuard.test.ts` has `.ct-app__root` and `.ct-app__overview`, `distContract.test.ts`
 * has `.ct-app__a`) and `src/test/` is helpers for them. Counting either would let a fixture
 * silence a dead-rule report, or invent an orphan out of nothing.
 */
function isTestFile(relative: string): boolean {
  return /\.test\.tsx?$/.test(relative) || relative.startsWith('test/');
}

/** Recursive, for the reason `designGuard.test.ts` records: a one-level read is blind to
 *  `src/ui/`, `src/profile/` and `src/routes/`, i.e. to nearly all of the markup. */
function sources(dir = SRC): [string, string][] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry): [string, string][] => {
    const path = `${dir}/${entry.name}`;
    const relative = path.slice(SRC.length + 1);
    if (entry.isDirectory()) return sources(path);
    if (!entry.isFile() || !/\.tsx?$/.test(entry.name) || isTestFile(relative)) return [];
    return [[relative, readFileSync(path, 'utf8')]];
  });
}

/**
 * Comments are stripped first, exactly as the other source-scanning guards do. Several
 * components document a class in prose (`Marketing.tsx` explains `ct-app__bleed`,
 * `status.tsx` explains `ct-app__status`), and a class that survives only in a comment is
 * NOT in use — counting it would silence the dead-rule half of this guard. It changes nothing
 * today: every class named in a comment is also really rendered.
 */
function classesInMarkup(source: string): Set<string> {
  const found = new Set<string>();
  for (const [name] of stripComments(source).matchAll(MARKUP_CLASS)) found.add(name);
  return found;
}

/**
 * Every class in a SELECTOR position in the compiled CSS.
 *
 * A character walk rather than a regex over the whole file, because the two things that must
 * not be counted are both positional: a class name inside a *declaration value*
 * (`content: ".ct-app__x"`) is not a definition, and neither is one inside a comment. Text
 * accumulates until `{` — where it is a prelude and is read — and is discarded at `;` or `}`,
 * which is where every declaration ends. At-rule preludes (`@container ct-app (…)`) are read
 * too and harmlessly contribute nothing: they carry no leading dot.
 *
 * Known limit, stated rather than implied: quoting is not tracked, so a `{`, `;` or `}` inside
 * a quoted string would confuse the walk. Nothing in this design system's output contains one
 * — verified — and the failure mode is a loud over- or under-report on the next run, not a
 * silent one.
 */
function selectorClasses(css: string): Set<string> {
  const found = new Set<string>();
  let prelude = '';
  for (const character of css.replace(/\/\*[\s\S]*?\*\//g, '')) {
    if (character === '{') {
      for (const [, name] of prelude.matchAll(SELECTOR_CLASS))
        if (name !== undefined) found.add(name);
      prelude = '';
    } else if (character === '}' || character === ';') {
      prelude = '';
    } else {
      prelude += character;
    }
  }
  return found;
}

/**
 * ⚠️ **The whole allowlist, and it is one runtime-assembled class name.**
 *
 * `web/src/ui/Marketing.tsx` renders `` `ct-app__card ct-app__bento--${area}` `` over the
 * three bento areas. Both halves are listed because the one interpolation trips both
 * directions — see the docstring. `keeps its exemptions REAL` below fails if either half stops
 * being needed, because a dead exemption is worse than no exemption (`designGuard.test.ts`
 * makes the same argument about its one `:root` carve-out).
 */
const INTERPOLATED: { readonly used: readonly string[]; readonly defined: readonly string[] } = {
  // The truncated stem the source literally contains.
  used: ['ct-app__bento--'],
  // The real classes the interpolation produces, which therefore look unused.
  defined: ['ct-app__bento--plan', 'ct-app__bento--diary', 'ct-app__bento--session'],
};

/** Markup classes with no rule behind them — the regression this file was written for. */
function withoutRules(used: Iterable<string>, defined: ReadonlySet<string>): string[] {
  return [...used].filter((name) => !defined.has(name) && !INTERPOLATED.used.includes(name)).sort();
}

/** Selectors no markup uses — the other half of the same swallowed span. */
function withoutMarkup(defined: Iterable<string>, used: ReadonlySet<string>): string[] {
  return [...defined]
    .filter((name) => !used.has(name) && !INTERPOLATED.defined.includes(name))
    .sort();
}

const markup = sources();

/** class -> the files that render it, so a failure names somewhere to go. */
const used = new Map<string, string[]>();
for (const [file, source] of markup) {
  for (const name of classesInMarkup(source)) {
    used.set(name, [...(used.get(name) ?? []), file]);
  }
}

const compiled = compile(ENTRY, { style: 'expanded' }).css;
const defined = selectorClasses(compiled);

describe('markup and CSS describe each other', () => {
  it('scanned both sides, rather than vacuously agreeing on nothing', () => {
    // Without this every assertion below passes on an empty scan and an empty compile — the
    // exact vacuity CLAUDE.md records for the FastAPI route-enumeration walk.
    expect(markup.length).toBeGreaterThanOrEqual(15);
    expect(compiled).toContain('.ct-app {');
    expect(used.size).toBeGreaterThanOrEqual(60);
    expect(defined.size).toBeGreaterThanOrEqual(60);
    // Sentinels present on both sides, so neither set is merely large.
    expect([...used.keys()]).toContain('ct-app__card');
    expect([...defined]).toContain('ct-app__card');
  });

  it('scans no test file, whose fixtures are not markup', () => {
    expect(markup.filter(([file]) => isTestFile(file))).toEqual([]);
    // …and does scan the files the redesign actually broke.
    const files = markup.map(([file]) => file);
    expect(files).toContain('profile/steps.tsx');
    expect(files).toContain('ui/Marketing.tsx');
  });

  it('uses no class the stylesheet leaves without a rule', () => {
    // The failure prints `class -> file`, because the useful next question is always which
    // component is now unstyled.
    expect(
      withoutRules(used.keys(), defined).map(
        (name) => `${name} (used in ${(used.get(name) ?? []).join(', ')})`,
      ),
    ).toEqual([]);
  });

  it('defines no selector the markup never uses', () => {
    expect(withoutMarkup(defined, new Set(used.keys()))).toEqual([]);
  });

  it('keeps its exemptions REAL rather than merely unused', () => {
    // If `Marketing.tsx` stops interpolating, every line of `INTERPOLATED` must go with it.
    for (const name of INTERPOLATED.used) expect([...used.keys()]).toContain(name);
    for (const name of INTERPOLATED.defined) expect([...defined]).toContain(name);
    // And the pattern is still strict enough to SEE the stem rather than swallow it, which is
    // the property that makes exempting it by name meaningful at all.
    expect(classesInMarkup('`ct-app__bento--${area}`')).toContain('ct-app__bento--');
  });
});

describe('positive control', () => {
  it('reports a markup class the real stylesheet does not define', () => {
    // The regression, reproduced: an independently spelled class name against the REAL
    // compiled set. If this ever passes, deleting a rule is invisible again.
    expect(withoutRules(classesInMarkup('<p className="ct-app__nowhere" />'), defined)).toEqual([
      'ct-app__nowhere',
    ]);
  });

  it('reports a real selector the markup never uses', () => {
    expect(
      withoutMarkup(selectorClasses('.ct-app__unused { color: red; }'), new Set(used.keys())),
    ).toEqual(['ct-app__unused']);
  });

  it('does not report a class that IS matched, in either direction', () => {
    // The other half of the control: a detector that reports everything is as useless as one
    // that reports nothing.
    expect(withoutRules(classesInMarkup('<p className="ct-app__card" />'), defined)).toEqual([]);
    expect(
      withoutMarkup(selectorClasses('.ct-app__card { padding: 0; }'), new Set(used.keys())),
    ).toEqual([]);
  });

  it('applies the interpolation exemption, and only to its own two halves', () => {
    expect(withoutRules(['ct-app__bento--'], defined)).toEqual([]);
    expect(withoutMarkup(['ct-app__bento--plan'], new Set(used.keys()))).toEqual([]);
    // A neighbouring modifier is NOT covered by it.
    expect(withoutMarkup(['ct-app__bento--ghost'], new Set(used.keys()))).toEqual([
      'ct-app__bento--ghost',
    ]);
  });

  it.each([
    ['styles/designGuard.test.ts', true],
    ['onboardingSubmit.test.tsx', true],
    ['test/sourceScan.ts', true],
    ['profile/steps.tsx', false],
    ['ui/reveal.ts', false],
    // Not a test file merely for containing the word.
    ['ui/latestNews.tsx', false],
  ])('classifies %s as test code: %s', (path, expected) => {
    expect(isTestFile(path)).toBe(expected);
  });

  it.each([
    ['a plain attribute', '<div className="ct-app__ghost" />', ['ct-app__ghost']],
    [
      'a template literal',
      '<div className={`ct-app__card ct-app__reveal--in`} />',
      ['ct-app__card', 'ct-app__reveal--in'],
    ],
    [
      'a class list built by concatenation',
      "const c = 'ct-app__nav' + (app ? ' ct-app__nav--app' : '');",
      ['ct-app__nav', 'ct-app__nav--app'],
    ],
    // A hyphenated element plus a double-hyphen modifier must survive whole; truncating at the
    // first `-` would make every modifier look like its base class and hide the difference.
    [
      'a modifier on a hyphenated element',
      '"ct-app__rail-node--done"',
      ['ct-app__rail-node--done'],
    ],
  ])('the markup detector sees %s', (_label, source, expected) => {
    expect([...classesInMarkup(source)].sort()).toEqual([...expected].sort());
  });

  it('ignores a class named only in a comment, in both comment forms', () => {
    expect(classesInMarkup('// ct-app__ghost is documented here\n').size).toBe(0);
    expect(classesInMarkup('/**\n * ct-app__ghost is documented here\n */\n').size).toBe(0);
    // The exemption must not leak past the comment on the same line.
    expect([...classesInMarkup('<p className="ct-app__card" /> // ct-app__ghost')]).toEqual([
      'ct-app__card',
    ]);
  });

  it.each([
    ['a plain rule', '.ct-app__x { color: red; }', ['ct-app__x']],
    [
      'a descendant selector inside a container query',
      '@container ct-app (min-width: 34rem) { .ct-app__card > .ct-app__prose { margin: 0 } }',
      ['ct-app__card', 'ct-app__prose'],
    ],
    [
      'a selector list with pseudo-classes',
      '.ct-app__a:hover, .ct-app__b:focus-visible { outline: 0; }',
      ['ct-app__a', 'ct-app__b'],
    ],
    [
      'a compound selector',
      'button.ct-app__button.ct-app__button--primary { border: 0; }',
      ['ct-app__button', 'ct-app__button--primary'],
    ],
  ])('the stylesheet detector sees %s', (_label, css, expected) => {
    expect([...selectorClasses(css)].sort()).toEqual([...expected].sort());
  });

  it.each([
    ['a declaration VALUE', '.ct-app__x::before { content: ".ct-app__ghost"; }'],
    [
      'the last declaration in a block, with no semicolon',
      '.ct-app__x { font-family: ".ct-app__ghost" }',
    ],
    ['a CSS comment', '/* .ct-app__ghost was here */\n.ct-app__x { color: red; }'],
  ])('the stylesheet detector does not treat %s as a definition', (_label, css) => {
    expect([...selectorClasses(css)]).toEqual(['ct-app__x']);
  });

  it('does not mistake the container NAME for a class', () => {
    // `container: ct-app/inline-size` is a real declaration in the compiled output, and
    // `ct-app` is a prefix of every class here.
    expect(selectorClasses('.ct-app { container: ct-app/inline-size; }').size).toBe(0);
  });
});
