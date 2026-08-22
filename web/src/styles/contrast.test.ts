import { readFileSync } from 'node:fs';
import { cwd } from 'node:process';

import { describe, expect, it } from 'vitest';

/**
 * WCAG AA (4.5:1) on every documented text-on-surface pair, in BOTH schemes.
 *
 * This is in scope per the testing policy's "project-wide invariants that silently rot": on
 * opaque surfaces contrast is decidable from the tokens alone — which is one of the practical
 * benefits of having rejected translucency — and nothing else in the gate can tell that a
 * retuned surface has just made the muted text unreadable in dark mode. It is not restating the
 * implementation: the assertion is a computed ratio, not the hex values.
 *
 * `vitest.config.ts` sets `css: false`, so there are no computed styles to read here and no
 * point trying. The SOURCE TEXT is parsed instead, which is also why `_tokens.scss` keeps light
 * and dark in two flat mixins with bare hex literals.
 *
 * `process.cwd()`, not `import.meta.url`: under jsdom the latter is an `http://localhost` URL
 * that `fileURLToPath` rejects. Vitest runs from `web/`.
 */
const SOURCE = readFileSync(`${cwd()}/src/styles/_tokens.scss`, 'utf8');

/**
 * Relative luminance, WCAG 2.x §"relative luminance". THROWS on anything it cannot parse rather
 * than coercing: an earlier version silently treated an unparsed value as black, which made
 * `#6F7570` (same colour, uppercase) pass against near-white surfaces at a fictional 21:1.
 */
function luminance(colour: string): number {
  const hex = /^#([0-9a-fA-F]{3,8})$/.exec(colour.trim())?.[1];
  if (hex === undefined || ![3, 4, 6, 8].includes(hex.length)) {
    throw new Error(`not a hex colour this calculator understands: ${JSON.stringify(colour)}`);
  }
  // 3/4-digit shorthand expands per digit; the 4th and 8th digits are alpha, which a token used
  // as an opaque surface must not have — so they are rejected rather than quietly ignored.
  const full = hex.length <= 4 ? [...hex].map((digit) => digit + digit).join('') : hex;
  if (full.length === 8) throw new Error(`surfaces must be opaque, got an alpha in ${colour}`);
  const channels = [0, 2, 4].map((offset) => parseInt(full.slice(offset, offset + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
}

function contrast(a: string, b: string): number {
  const [lighter, darker] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((lighter ?? 0) + 0.05) / ((darker ?? 0) + 0.05);
}

/** The declarations in one `@mixin <name>-values` block. Neither block nests, so `[^}]*` is
 *  sufficient and stays readable — that flatness is a deliberate property of `_tokens.scss`. */
function values(name: 'light' | 'dark'): Record<string, string> {
  const block = new RegExp(String.raw`@mixin ${name}-values \{([^}]*)\}`).exec(SOURCE)?.[1];
  expect(block, `no "@mixin ${name}-values" block in _tokens.scss`).toBeDefined();

  const tokens: Record<string, string> = {};
  // Every declaration in the block is captured, whatever its value, and the colour-ness of a
  // value is decided by `luminance` (which throws). Matching only `#[0-9a-f]{6}` here is what
  // let a mis-cased or shorthand hex fall out of the set unnoticed.
  for (const [, key, value] of (block ?? '').matchAll(/--ct-([\w-]+):\s*([^;]+);/g)) {
    if (key !== undefined && value !== undefined) tokens[key] = value.trim();
  }
  return tokens;
}

/** Fails loudly on a missing token instead of substituting one. */
function tone(tokens: Record<string, string>, name: string): string {
  const value = tokens[name];
  expect(value, `--ct-${name} is missing from this scheme`).toBeDefined();
  return value ?? '';
}

const light = values('light');
// `declare` emits light unconditionally and the dark block overrides inside the media query, so
// the effective dark palette is the union. Merging also means a token added to only one list
// would be tested against the wrong scheme rather than skipped.
const dark = { ...light, ...values('dark') };

const SURFACES = ['bg', 'surface-1', 'surface-2', 'surface-3', 'hover', 'pressed'] as const;
const CARD_SURFACES = ['bg', 'surface-1', 'surface-2', 'surface-3'] as const;

/** Every pair the design system actually renders, foreground first. */
const TEXT_PAIRS: [string, string][] = [
  ...['fg', 'fg-muted'].flatMap((fg): [string, string][] => SURFACES.map((s) => [fg, s])),
  // Accent, danger and warning are text tones (links, badges, field errors, the grade-clash
  // helper line), never used on `hover` or `pressed`, which are neutral-button states.
  // `warning` is `.ct-app__caption--warning`, which renders inside a card — so `surface-1`,
  // and the other card surfaces too, because a card's own surface steps with its nesting.
  // It is text ONLY and never a fill, so unlike the two above it has no `--fg` partner below.
  ...['accent', 'danger', 'warning'].flatMap((fg): [string, string][] =>
    CARD_SURFACES.map((s) => [fg, s]),
  ),
  // …and the reverse: the tone as a FILL, with its paired foreground on top.
  ['accent-fg', 'accent'],
  ['accent-fg', 'accent-pressed'],
  ['danger-fg', 'danger'],
];

/** WCAG 1.4.11 non-text contrast: 3:1, not 4.5:1. Input and button outlines are the only
 *  borders load-bearing enough to need it — the hairlines are decorative separators. */
const NON_TEXT_PAIRS: [string, string][] = SURFACES.map((s) => ['border-strong', s]);

describe.each([
  ['light', light],
  ['dark', dark],
])('%s scheme', (_scheme, tokens) => {
  it.each(TEXT_PAIRS)('renders --ct-%s on --ct-%s at AA 4.5:1', (fg, bg) => {
    expect(contrast(tone(tokens, fg), tone(tokens, bg))).toBeGreaterThanOrEqual(4.5);
  });

  it.each(NON_TEXT_PAIRS)('outlines --ct-%s on --ct-%s at 3:1', (fg, bg) => {
    expect(contrast(tone(tokens, fg), tone(tokens, bg))).toBeGreaterThanOrEqual(3);
  });
});

describe('positive control', () => {
  // Without these the suite above would pass identically on a calculator that returned a large
  // constant, or on a parser that returned nothing and left every lookup undefined.
  it('computes the two ends of the scale correctly', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrast('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
    // Symmetric, so a pair does not pass merely by being written in the other order.
    expect(contrast('#1b6b47', '#ffffff')).toBeCloseTo(contrast('#ffffff', '#1b6b47'), 10);
  });

  it('rejects a pair that only looks acceptable', () => {
    // 4.48:1 — the classic mid-grey that reviewers wave through. If this ever passes, every
    // assertion above has stopped meaning anything.
    expect(contrast('#777777', '#ffffff')).toBeLessThan(4.5);
    expect(contrast('#767676', '#ffffff')).toBeGreaterThanOrEqual(4.5);
  });

  it('refuses a value it cannot parse instead of treating it as black', () => {
    // Every one of these used to be silently read as #000000, which passes against a light
    // surface at up to 21:1 and fails only in dark mode — the asymmetry that hid it.
    expect(() => luminance('var(--ct-bg)')).toThrow(/not a hex colour/);
    expect(() => luminance('none')).toThrow(/not a hex colour/);
    expect(() => luminance('rgb(20 23 28 / 0.5)')).toThrow(/not a hex colour/);
    expect(() => luminance('#14171c80')).toThrow(/opaque/);
    // …and it does accept the forms that are legitimate, case-insensitively.
    expect(luminance('#FFFFFF')).toBeCloseTo(luminance('#ffffff'), 12);
    expect(luminance('#fff')).toBeCloseTo(luminance('#ffffff'), 12);
  });

  it('fails on a missing token rather than comparing a substitute', () => {
    expect(() => tone({ 'surface-1': '#ffffff' }, 'surface-9')).toThrow();
  });

  it('actually parsed both schemes, with matching keys', () => {
    const lightKeys = Object.keys(light).sort();
    expect(lightKeys.length).toBeGreaterThan(10);
    // A token declared in only one scheme keeps the other scheme's value, which is how an
    // unreadable dark surface ships while every pair above still passes.
    expect(Object.keys(values('dark')).sort()).toEqual(lightKeys);
    expect(light['surface-3']).not.toBe(dark['surface-3']);
  });
});
