/**
 * The landing page's photographs, as data.
 *
 * This module is the SINGLE source of truth for the width ladders, and it is deliberately
 * plain data with no imports: `scripts/gen-landing-images.mjs` imports this same file (Node 24
 * strips the types natively), so the `srcset` the browser is given and the files the generator
 * emits cannot drift apart. Licence and attribution for all three live in
 * `web/PHOTO-CREDITS.md` (outside `public/`: it is a provenance record, not
 * something to ship and precache).
 *
 * The originals are 12–22 MB each and live OUTSIDE the repo; the derivatives under
 * `public/landing/` are committed, because CI and Vercel build from a clone that has no access
 * to a photo library.
 */

export interface LandingImage {
  /** File-name stem under `public/landing/`, and the key everything else is derived from. */
  readonly slug: string;
  /** The original, relative to the photo-collection root. Read by the generator only. */
  readonly source: string;
  readonly alt: string;
  /**
   * Intrinsic size of the ORIGINAL, as `[w, h]`. Declared here rather than only read from the
   * file so the no-upscale rule is checkable **in CI**, where the originals do not exist: the
   * generator asserts this matches the real file (so the manifest cannot lie about it) and
   * `landingImages.test.ts` asserts every rung fits inside it.
   */
  readonly sourceSize: readonly [number, number];
  /**
   * The aspect the DERIVATIVES are cut to, as `[w, h]` — a deliberate crop, not necessarily the
   * original's ratio. The crop is centred and the climber is centred inside it, so every further
   * `object-fit: cover` step the CSS applies keeps him.
   *
   * ⚠️ `chimney-effort`'s 4:5 dates from a layout that rendered it tall; the band now sizes itself
   * from its copy (~352px) and crops a wide strip out of this. Nothing upscales — 4:5 is taller
   * than anything the CSS displays, so every rendering is a crop — but a wide band does discard
   * most of the pixels it downloads. Re-cutting these to 3:2 would recover that; it is deliberately
   * NOT done here, because it churns 2.5 MB of committed binaries for a page-weight tidy-up.
   *
   * ⚠️ A crop taller than the source's ratio makes **height**, not width, the binding constraint
   * on the ladder. That is why the guard checks both dimensions.
   */
  readonly aspect: readonly [number, number];
  /**
   * The ladder for AVIF and WebP. Every entry must be `<=` the original's width: upscaling a
   * photo to fill a rung is worse than serving the rung below it, so the generator throws
   * rather than doing it.
   *
   * **The bands stop at 1920 on purpose.** A 2560 rung was generated and measured first: 639 kB
   * of AVIF for the hero, which a 1512pt/DPR-2 laptop would have picked — a third of a megabyte
   * over the 1920 rung, to sharpen a decorative photographic band. A photograph tolerates a
   * slightly soft upscale far better than a page tolerates that download. It also nearly doubled
   * the committed weight of this directory (6.0 MB against 2.6 MB).
   */
  readonly widths: readonly number[];
  /**
   * The JPEG ladder — deliberately ONE rung, which is also the `<img src>`. Every browser in
   * the project's baseline (`baseline-widely-available`: Chrome 111, Safari 16.4, Firefox 114)
   * supports **AVIF**, so WebP is already the insurance layer and JPEG is insurance behind
   * insurance. It exists because it costs one file; a full ladder of it would cost real bytes
   * for a browser we do not claim to support.
   */
  readonly fallbackWidths: readonly number[];
  /** The rung used for the `<img src>`, i.e. what a browser with no `srcset` support gets. */
  readonly fallbackWidth: number;
  /**
   * Which part of the original the crop keeps, as a sharp `position` gravity. Defaults to
   * `centre`.
   *
   * ⚠️ It exists because for a slot whose displayed ratio EQUALS the derivative's ratio, the
   * generator's crop is the final framing — `object-position` has no pixels left to recover.
   * `shot-blue-sky` is the case: a landscape original in a 1:1 slot, with the climber centre-left
   * and empty sky to the right, so a centred crop clips his reaching arm and fills the frame with
   * sky. Checked by eye at all three gravities, not inferred.
   */
  readonly crop?: 'centre' | 'left' | 'right' | 'top' | 'bottom';
}

/**
 * ⚠️ `rope-detail`'s `sourceSize` is **960x640 and that is all there is** — it is the 960w thumb
 * StockSnap publishes, not the 4460px master. So its ladder stops at 960, and no layout slot on
 * the page may ask for more: at DPR 2 that caps the rendered tile at 480 CSS px, which is why
 * `_landing.scss` holds it to 22rem inside a card rather than letting it stretch.
 */
export const LANDING_IMAGES = {
  hero: {
    slug: 'hero-granite',
    source: 'final/orig-uc-2.jpg',
    alt: 'A roped climber high on a slabby granite face, following a thin crack.',
    sourceSize: [5760, 3840],
    aspect: [3, 2],
    widths: [640, 960, 1280, 1920],
    fallbackWidths: [960],
    fallbackWidth: 960,
  },
  effort: {
    slug: 'chimney-effort',
    source: 'final/orig-uc-6.jpg',
    // Descriptive, not empty. It was `alt: ''` while the copy sat ON TOP of it — the text said
    // everything the photo said, so a description would have been read out twice. Now the photo
    // is above its own copy and carries information the copy does not.
    alt: 'A climber in an orange helmet wedged deep inside a dark granite chimney, far below the lit slot above.',
    sourceSize: [5760, 3840],
    aspect: [4, 5],
    widths: [640, 960, 1280, 1920],
    fallbackWidths: [960],
    fallbackWidth: 960,
  },
  detail: {
    slug: 'rope-detail',
    source: 'final/orig-sp-8.jpg',
    alt: 'Chalked hands feeding a green rope through a climbing harness.',
    sourceSize: [960, 640],
    aspect: [3, 2],
    widths: [320, 480, 640, 960],
    fallbackWidths: [480],
    fallbackWidth: 480,
  },
  /**
   * ⚠️ The next three are TEMPORARY stand-ins for app screenshots, which cannot exist until the
   * plan UI and the session player do. They are photographs of climbing, NOT of this software, so
   * every alt text says so and every visible caption says so — a stock photo passed off as a
   * screenshot is the one thing worse than an empty frame. Stage 2 replaces all three, and these
   * entries and their derivatives go with them.
   *
   * Ratios are per slot and each derivative is cut to the same ratio its slot displays, so the CSS
   * never crops a second time — which also means the `crop` gravity below is the final framing.
   * The two narrow bento tiles are **square**: a portrait crop pushes the figure on
   * `shot-summit`'s pinnacle off the right edge, and on a phone these tiles are FULL width, where
   * a portrait frame is ~477px of a single card.
   */
  shotPlan: {
    slug: 'shot-gym-wall',
    source: 'orig-ur-0.jpg',
    alt: 'Stand-in photograph, not a screenshot: an indoor gym wall covered in coloured holds, with a climber traversing it.',
    sourceSize: [6000, 4000],
    aspect: [16, 9],
    widths: [420, 660, 990, 1320],
    fallbackWidths: [660],
    fallbackWidth: 660,
  },
  shotSession: {
    slug: 'shot-blue-sky',
    source: 'orig-uc-0.jpg',
    alt: 'Stand-in photograph, not a screenshot: a climber high on a sunlit rock face against a clear blue sky.',
    sourceSize: [5472, 3648],
    aspect: [1, 1],
    widths: [360, 540, 740],
    fallbackWidths: [540],
    fallbackWidth: 540,
    crop: 'left',
  },
  shotDiary: {
    slug: 'shot-summit',
    source: 'orig-um-3.jpg',
    alt: 'Stand-in photograph, not a screenshot: a climber standing on a narrow mountain summit above a green valley.',
    sourceSize: [5760, 3840],
    aspect: [1, 1],
    widths: [360, 540, 740],
    fallbackWidths: [540],
    fallbackWidth: 540,
  },
} as const satisfies Record<string, LandingImage>;

export const LANDING_FORMATS = [
  { extension: 'avif', mime: 'image/avif' },
  { extension: 'webp', mime: 'image/webp' },
] as const;

export const LANDING_DIR = 'landing';

/** `landing/<slug>-<width>.<extension>`, the one place the file-name shape is written. */
export function landingFile(image: LandingImage, width: number, extension: string): string {
  return `${LANDING_DIR}/${image.slug}-${width}.${extension}`;
}

export function landingHeight(image: LandingImage, width: number): number {
  const [w, h] = image.aspect;
  return Math.round((width * h) / w);
}
