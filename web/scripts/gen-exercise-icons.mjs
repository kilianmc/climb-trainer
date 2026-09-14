#!/usr/bin/env node
/**
 * Slices the exercise-illustration composites into one WebP per icon.
 *
 *   npm --prefix web run images:icons            # fill in whatever is missing
 *   npm --prefix web run images:icons -- --force # re-encode everything
 *   CT_ICON_SRC=/some/dir npm --prefix web run images:icons
 *
 * The composites are Kilian's originals (1.4 MB each) and live at `web/art/exercise-icons/`,
 * which is inside the repo but outside `public/`: they are build INPUT, never served bytes, and
 * committing them is what makes a re-slice reproducible from a clean clone. That differs from
 * `gen-landing-images.mjs`, whose 12–22 MB stock photographs stay outside the repo entirely —
 * the trade is the same one, weighed against a two-hundredth of the size.
 *
 * The slice list and the disc geometry are imported from `src/library/exerciseIcons.ts`, not
 * restated here: that module is what the `<img src>` is built from, so a slug listed in one place
 * and emitted in the other is a 404 in production. Node 24 strips the types natively.
 *
 * Idempotent: an output that already exists is skipped, which is what makes it safe to re-run
 * after adding one icon to the manifest. `--force` exists for a quality change.
 *
 * ## Why there are two mask paths, and the measurements behind them
 *
 * `whitebg.png` already carries alpha and its art is the disc: the content reaches at most 2 px
 * past the fitted radius on all seven icons, and the annulus 4–12 px outside each disc edge
 * measures a mean alpha of 0.0–0.1 / 255. There is no baked halo. What there IS: fully
 * transparent pixels carrying light RGB underneath (mean luminance 85 beside `power-endurance`),
 * which blooms into a white glow the moment anything resizes or flattens without premultiplying.
 * So the alpha is clamped to the disc, and the RGB under alpha 0 is zeroed at the source.
 *
 * `blackbg.png` is opaque, and its "disc" is a 2 px ring at luminance 25–38 over a flat field of
 * 11 — the interior is the background colour, so a rectangular crop is a black square and a
 * plain circular mask is nearly right. Nearly: with the labels excluded, content reaches past
 * the ring on every icon, by 1–7 px on eight of them and by **27 px on `pancake`**, whose
 * straddled feet are 13% of its ink. So the mask is the UNION of the disc and a matte over the
 * content outside it, and the matte un-mixes each edge pixel against the measured background so
 * a light theme gets no dark fringe.
 *
 * The labels are cropped off by scanning outward from the disc's bounding box to the first empty
 * row or column and discarding everything beyond it: the nearest label sits 8 px below a disc
 * edge while `pancake` overspills 27 px sideways, so no radial bound can separate the two, and a
 * gap in the ink can. Art contiguous with the disc always survives.
 */
import { existsSync, mkdirSync, statSync } from 'node:fs';
import { argv, env, exit, stderr, stdout } from 'node:process';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

import {
  ICON_DISC_DIAMETER,
  ICON_SIDE,
  ICON_SLICES,
  iconPath,
} from '../src/library/exerciseIcons.ts';

const OUT_DIR = fileURLToPath(new URL('../public/exercise-icons/', import.meta.url));
const SRC_DIR =
  env.CT_ICON_SRC ?? fileURLToPath(new URL('../art/exercise-icons/', import.meta.url));
const force = argv.includes('--force');

/** Luminance floor for "this is ink, not the background field". The ring peaks at 38. */
const INK = 20;
/** Alpha floor for the same question on an alpha-carrying composite. */
const INK_ALPHA = 40;
/** Slack, in px, before the empty-line scan starts — the ring itself is ink. */
const GAP_SCAN_MARGIN = 4;

const lum = (r, g, b) => r * 0.299 + g * 0.587 + b * 0.114;

function kb(path) {
  return `${(statSync(path).size / 1024).toFixed(0)} kB`;
}

/** The whole composite as RGBA, plus the readers the mask paths need. */
async function readGrid(file) {
  const source = `${SRC_DIR}${file}`;
  if (!existsSync(source)) {
    throw new Error(`${file} is not in ${SRC_DIR}. Point CT_ICON_SRC at the directory holding it.`);
  }
  const { data, info } = await sharp(source)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const { width, height, channels } = info;
  const at = (x, y) => {
    const i = (y * width + x) * channels;
    return [data[i], data[i + 1], data[i + 2], data[i + 3]];
  };
  const hasAlpha = (await sharp(source).metadata()).hasAlpha === true;
  const background = hasAlpha ? [0, 0, 0] : fieldColour(at, width, height);
  const isInk = hasAlpha ? (x, y) => at(x, y)[3] > INK_ALPHA : (x, y) => lum(...at(x, y)) > INK;
  return { width, height, at, hasAlpha, background, isInk };
}

/** The flat background field, as the median of a border band. Measured, never assumed. */
function fieldColour(at, width, height) {
  const samples = [[], [], []];
  for (let x = 0; x < width; x += 3) {
    for (const y of [1, 3, height - 2, height - 4]) {
      const p = at(x, y);
      for (let c = 0; c < 3; c++) samples[c].push(p[c]);
    }
  }
  return samples.map((channel) => {
    channel.sort((a, b) => a - b);
    return channel[Math.floor(channel.length / 2)];
  });
}

/**
 * The box of ink around the disc, found by scanning outward to the first empty line. This is what
 * drops the text label; see the docstring for why a radial bound cannot.
 */
function inkBox(grid, cx, cy, r, half) {
  const x0 = Math.max(0, cx - half);
  const x1 = Math.min(grid.width - 1, cx + half);
  const y0 = Math.max(0, cy - half);
  const y1 = Math.min(grid.height - 1, cy + half);
  const rowHasInk = (y) => {
    for (let x = x0; x <= x1; x++) if (grid.isInk(x, y)) return true;
    return false;
  };
  const colHasInk = (x) => {
    for (let y = y0; y <= y1; y++) if (grid.isInk(x, y)) return true;
    return false;
  };
  const scan = (from, to, step, hasInk) => {
    let last = from - step;
    for (let v = from; step > 0 ? v <= to : v >= to; v += step) {
      if (!hasInk(v)) return last;
      last = v;
    }
    return to;
  };
  return {
    top: scan(cy - r - GAP_SCAN_MARGIN, y0, -1, rowHasInk),
    bottom: scan(cy + r + GAP_SCAN_MARGIN, y1, 1, rowHasInk),
    left: scan(cx - r - GAP_SCAN_MARGIN, x0, -1, colHasInk),
    right: scan(cx + r + GAP_SCAN_MARGIN, x1, 1, colHasInk),
  };
}

/** Brightest luminance in a 5x5 neighbourhood: the solid foreground an edge pixel is mixed with. */
function neighbourhoodPeak(grid, x, y) {
  let peak = 0;
  for (let dx = -2; dx <= 2; dx++) {
    for (let dy = -2; dy <= 2; dy++) {
      const nx = x + dx;
      const ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= grid.width || ny >= grid.height) continue;
      const value = lum(...grid.at(nx, ny));
      if (value > peak) peak = value;
    }
  }
  return peak;
}

/** One slice as a square RGBA buffer at source resolution, disc-centred and label-free. */
function cut(grid, slice, half) {
  const [cx, cy, r] = slice.disc;
  const box = inkBox(grid, cx, cy, r, half);
  const side = half * 2;
  const out = Buffer.alloc(side * side * 4);
  const bg = grid.background;
  const bgLum = lum(...bg) + 3;
  for (let oy = 0; oy < side; oy++) {
    for (let ox = 0; ox < side; ox++) {
      const x = cx - half + ox;
      const y = cy - half + oy;
      const i = (oy * side + ox) * 4;
      if (x < 0 || y < 0 || x >= grid.width || y >= grid.height) continue;
      if (y < box.top || y > box.bottom || x < box.left || x > box.right) continue;
      const distance = Math.hypot(x - cx, y - cy);
      const [pr, pg, pb, pa] = grid.at(x, y);
      if (grid.hasAlpha) {
        // Clamped to the disc: it is the whole of the art, and the clamp is what drops the
        // scattered alpha noise across the transparent field.
        if (distance > r + 3) continue;
        const alpha = pa >= 250 ? 255 : pa;
        if (alpha === 0) continue;
        out[i] = pr;
        out[i + 1] = pg;
        out[i + 2] = pb;
        out[i + 3] = alpha;
        continue;
      }
      const inside = Math.max(0, Math.min(1, (r + 1.5 - distance) / 2));
      if (inside >= 0.999) {
        out[i] = pr;
        out[i + 1] = pg;
        out[i + 2] = pb;
        out[i + 3] = 255;
        continue;
      }
      // Outside the disc: recover the coverage from how far this pixel is from the flat field
      // toward the solid ink beside it, then un-mix the field back out of its colour.
      const peak = Math.max(neighbourhoodPeak(grid, x, y), bgLum + 30);
      const matte = Math.max(0, Math.min(1, (lum(pr, pg, pb) - bgLum) / (peak - bgLum)));
      const alpha = Math.max(inside, matte);
      if (alpha <= 0.02) continue;
      const unmix = (channel, base) =>
        Math.max(0, Math.min(255, Math.round((channel - (1 - alpha) * base) / alpha)));
      const keepOriginal = inside >= matte;
      out[i] = keepOriginal ? pr : unmix(pr, bg[0]);
      out[i + 1] = keepOriginal ? pg : unmix(pg, bg[1]);
      out[i + 2] = keepOriginal ? pb : unmix(pb, bg[2]);
      out[i + 3] = Math.round(alpha * 255);
    }
  }
  return { out, side };
}

mkdirSync(OUT_DIR, { recursive: true });
try {
  const grids = new Map();
  for (const slice of ICON_SLICES) {
    const name = `${slice.slug}.webp`;
    const target = `${OUT_DIR}${name}`;
    if (!force && existsSync(target)) {
      stdout.write(`  skip  ${name}  (${kb(target)})\n`);
      continue;
    }
    if (!grids.has(slice.grid)) grids.set(slice.grid, await readGrid(slice.grid));
    const grid = grids.get(slice.grid);
    const [, , r] = slice.disc;
    // The disc lands at a fixed fraction of the output on every icon, so a list mixing icons
    // and placeholders does not jump. Never above 1: nothing is upscaled.
    const half = Math.round((ICON_SIDE * r) / ICON_DISC_DIAMETER);
    if (ICON_SIDE > half * 2) {
      throw new Error(
        `${slice.slug}: ${ICON_SIDE}px of output from ${half * 2}px of source would upscale. ` +
          `Lower ICON_SIDE or raise ICON_DISC_DIAMETER in src/library/exerciseIcons.ts.`,
      );
    }
    const { out, side } = cut(grid, slice, half);
    await sharp(out, { raw: { width: side, height: side, channels: 4 } })
      .resize({ width: ICON_SIDE, height: ICON_SIDE, kernel: 'lanczos3' })
      .webp({ quality: 88, effort: 6, alphaQuality: 100 })
      .toFile(target);
    stdout.write(`  write ${iconPath(slice.slug)}  (${kb(target)})  from ${slice.grid}\n`);
  }
} catch (cause) {
  stderr.write(`${cause instanceof Error ? cause.message : String(cause)}\n`);
  exit(1);
}
