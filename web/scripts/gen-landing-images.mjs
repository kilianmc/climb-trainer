#!/usr/bin/env node
/**
 * Emits the landing page's responsive derivatives from the originals.
 *
 *   npm --prefix web run images:landing            # fill in whatever is missing
 *   npm --prefix web run images:landing -- --force # re-encode everything
 *   CT_PHOTO_SRC=/some/dir npm --prefix web run images:landing
 *
 * The originals are 2–22 MB each and live outside the repo (default:
 * `~/Pictures/climb-trainer-photo-src`; `source` is a path relative to that root). The DERIVATIVES are committed, because CI and
 * Vercel build from a clone that has no photo library — so this script is a one-off authoring
 * tool, never part of `build`.
 *
 * The ladder is imported from `src/ui/landingImages.ts`, not restated here: that module is what
 * the `srcset` is built from, so a rung listed in one place and emitted in the other is a 404 in
 * production. Node 24 strips the types natively, which is what makes one source of truth
 * possible across a `.mjs` script and a `.ts` module.
 *
 * Idempotent: an output that already exists is skipped. That is what makes it safe to re-run
 * after adding a single rung, and it is why `--force` exists for a quality change.
 */
import { existsSync, mkdirSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { argv, env, exit, stderr, stdout } from 'node:process';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

import {
  LANDING_DIR,
  LANDING_FORMATS,
  LANDING_IMAGES,
  landingFile,
  landingHeight,
} from '../src/ui/landingImages.ts';

const OUT_DIR = fileURLToPath(new URL('../public/landing/', import.meta.url));
const SRC_DIR = env.CT_PHOTO_SRC ?? `${homedir()}/Pictures/climb-trainer-photo-src`;
const force = argv.includes('--force');

/**
 * Encoder settings, chosen by measuring the output rather than by reputation: these are
 * large-format photographs on a page a visitor reads once, so the target is "no visible
 * artefacts at 1x" and not the smallest possible file.
 *
 * Measured on the hero at 1920px before choosing:
 *
 *   AVIF  q40 197 kB   q45 261 kB   q48 282 kB   q52 349 kB
 *   WebP  q70 592 kB   q74 627 kB   q78 706 kB
 *
 * q48/q74 is the knee — above it the file grows faster than the picture improves, and granite
 * texture is close to the worst case an image codec can be handed. `chromaSubsampling: '4:4:4'`
 * on AVIF keeps the one saturated thing in these photos (a green rope, an orange helmet) from
 * smearing, and it is nearly free: **1.5% larger than 4:2:0, measured** (282 vs 279 kB), which is
 * why it is on here and left at the default for JPEG.
 */
const ENCODERS = {
  avif: (pipeline) => pipeline.avif({ quality: 48, effort: 6, chromaSubsampling: '4:4:4' }),
  webp: (pipeline) => pipeline.webp({ quality: 74, effort: 5 }),
  jpg: (pipeline) => pipeline.jpeg({ quality: 80, mozjpeg: true, progressive: true }),
};

function kb(path) {
  return `${(statSync(path).size / 1024).toFixed(0)} kB`;
}

/**
 * Every derivative to emit for one photo: the modern formats over `widths`, plus JPEG over the
 * shorter `fallbackWidths`. Flattened here so the "no upscaling" check below sees the whole set.
 */
function derivatives(image) {
  return [
    ...LANDING_FORMATS.flatMap(({ extension }) =>
      image.widths.map((width) => ({ width, extension })),
    ),
    ...image.fallbackWidths.map((width) => ({ width, extension: 'jpg' })),
  ];
}

async function generate(image) {
  const source = `${SRC_DIR}/${image.source}`;
  if (!existsSync(source)) {
    throw new Error(
      `${image.source} is not in ${SRC_DIR}. The originals are deliberately NOT in this repo; ` +
        `point CT_PHOTO_SRC at the directory holding them.`,
    );
  }

  const { width: sourceWidth, height: sourceHeight } = await sharp(source).metadata();
  const [declaredW, declaredH] = image.sourceSize;

  // The manifest declares the original's size so `landingImages.test.ts` can enforce the
  // no-upscale rule in CI, where the originals do not exist. That only works if the declaration
  // is true, so it is checked here — the one place the real file is available.
  if (sourceWidth !== declaredW || sourceHeight !== declaredH) {
    throw new Error(
      `${image.slug}: sourceSize says ${declaredW}x${declaredH} but ${image.source} is ` +
        `${sourceWidth}x${sourceHeight}. Fix src/ui/landingImages.ts — the CI-side upscale guard ` +
        `trusts that number.`,
    );
  }

  // ⚠️ BOTH dimensions, and the height one is not theoretical: `chimney-effort` is cut to 4:5
  // from a 3:2 original, so its 1920px rung needs 2400px of source HEIGHT while asking for only
  // a third of the source width. A width-only check (which is what this was) would wave through
  // a crop tall enough to upscale, and an upscaled photo does not fail — it just looks soft.
  for (const { width, extension } of derivatives(image)) {
    const height = landingHeight(image, width);
    if (width > sourceWidth || height > sourceHeight) {
      throw new Error(
        `${image.slug}: the ${width}.${extension} rung needs ${width}x${height} but ` +
          `${image.source} is only ${sourceWidth}x${sourceHeight}. Upscaling is not acceptable — ` +
          `shorten the ladder or flatten the crop in src/ui/landingImages.ts, and check no ` +
          `layout slot demands more.`,
      );
    }
  }

  for (const { width, extension } of derivatives(image)) {
    const name = landingFile(image, width, extension).slice(LANDING_DIR.length + 1);
    const target = `${OUT_DIR}${name}`;
    if (!force && existsSync(target)) {
      stdout.write(`  skip  ${name}  (${kb(target)})\n`);
      continue;
    }
    // `fit: 'cover'` with the height derived from the declared aspect, so a source whose real
    // ratio drifts is cropped to the ratio the `<img>` announces rather than silently letterboxed.
    const pipeline = sharp(source).resize({
      width,
      height: landingHeight(image, width),
      fit: 'cover',
    });
    await ENCODERS[extension](pipeline).toFile(target);
    stdout.write(`  write ${name}  (${kb(target)})\n`);
  }
}

mkdirSync(OUT_DIR, { recursive: true });
try {
  for (const image of Object.values(LANDING_IMAGES)) {
    stdout.write(`${image.slug}  <- ${image.source}\n`);
    await generate(image);
  }
} catch (cause) {
  stderr.write(`${cause instanceof Error ? cause.message : String(cause)}\n`);
  exit(1);
}
