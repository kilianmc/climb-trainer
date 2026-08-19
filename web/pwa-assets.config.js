/**
 * Icon generation, run ON DEMAND — `npm --prefix web run generate:icons` — never from the Vite
 * build: the generator pulls in `sharp`, and a Vercel build has no reason to re-derive
 * deterministic output from a source file that changes once a year. The PNGs it emits are
 * committed, so the manifest's `icons` array can be hand-written against real filenames.
 *
 * Deliberately plain JS with a STRING preset name and no imports. `@vite-pwa/assets-generator`
 * is not a dependency of this project (its `sharp` carries four high-severity libvips CVEs, and
 * it would add ~200 packages to every production install for a script that runs once a year), so
 * `defineConfig`/`minimal2023Preset` are unavailable here and `tsc -b` must not be asked to
 * resolve them. The npm script pins the generator's version instead.
 */
export default {
  headLinkOptions: { preset: '2023' },
  preset: 'minimal-2023',
  images: ['public/mark.svg'],
};
