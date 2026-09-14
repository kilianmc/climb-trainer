/** SINGLE source of truth for the illustrations, on the `ui/landingImages.ts` precedent:
 *  `scripts/gen-exercise-icons.mjs` cuts from it and `test_exercise_icon_map.py` guards it. */

/** Relative to `web/public/`, and the `publicUrl` argument's prefix. */
export const ICON_DIR = 'exercise-icons';

/** The slot is 13rem and 4:3, so height binds at 156 CSS px: 312 is over 2x for it, and no
 *  source disc is upscaled to reach 244. */
export const ICON_SIDE = 312;
export const ICON_DISC_DIAMETER = 244;

export interface IconSlice {
  /** File-name stem under `public/exercise-icons/`, and the key the maps below point at. */
  readonly slug: string;
  /** Which composite in `web/art/exercise-icons/`. Read by the generator only. */
  readonly grid: string;
  /** `[cx, cy, r]` in composite px, from circle-fitting the ring — NOT from the grid, whose
   *  nine discs vary from r=122 to r=138. */
  readonly disc: readonly [number, number, number];
  readonly alt: string;
}

export const ICON_SLICES = [
  {
    slug: 'strength',
    grid: 'whitebg.png',
    disc: [218, 247, 143],
    alt: 'A climber gripping a bar overhead with both arms bent.',
  },
  {
    slug: 'power',
    grid: 'whitebg.png',
    disc: [584, 247, 144],
    alt: 'A climber throwing for a distant hold, feet off the wall.',
  },
  {
    slug: 'power-endurance',
    grid: 'whitebg.png',
    disc: [949, 247, 144],
    alt: 'A climber pulling through steep ground on a bouldering wall.',
  },
  {
    slug: 'technique',
    grid: 'whitebg.png',
    disc: [1317, 247, 144],
    alt: 'A climber stepping high onto a foothold, hips turned to the wall.',
  },
  {
    slug: 'endurance',
    grid: 'whitebg.png',
    disc: [378, 680, 142],
    alt: 'A climber moving steadily up a wall of scattered holds.',
  },
  {
    slug: 'mobility',
    grid: 'whitebg.png',
    disc: [767, 680, 142],
    alt: 'A climber reaching overhead into a long side bend.',
  },
  {
    slug: 'flexibility',
    grid: 'whitebg.png',
    disc: [1157, 680, 142],
    alt: 'A climber holding a high foot on the wall in a deep split.',
  },
  {
    slug: 'finger-strength',
    grid: 'blackbg.png',
    disc: [309, 156, 122],
    alt: 'A hand crimping a small hold.',
  },
  {
    slug: 'hangboard-routine',
    grid: 'blackbg.png',
    disc: [767, 154, 138],
    alt: 'A climber hanging from a hangboard with both hands.',
  },
  {
    slug: 'front-lever',
    grid: 'blackbg.png',
    disc: [1228, 161, 130],
    alt: 'A climber held horizontal beneath a bar in a front lever.',
  },
  {
    slug: 'reverse-wrist-curls',
    grid: 'blackbg.png',
    disc: [309, 486, 124],
    alt: 'A forearm curling a dumbbell back at the wrist.',
  },
  {
    slug: 'pancake',
    grid: 'blackbg.png',
    disc: [767, 488, 127],
    alt: 'A climber sitting in a wide straddle, folding forward over the floor.',
  },
  {
    slug: 'dyno',
    grid: 'blackbg.png',
    disc: [1229, 489, 128],
    alt: 'A climber flying between holds, both feet cut loose.',
  },
  {
    slug: 'four-by-four',
    grid: 'blackbg.png',
    disc: [310, 807, 123],
    alt: 'A climber on a boulder problem beside four numbered laps.',
  },
  {
    slug: 'autobelay',
    grid: 'blackbg.png',
    disc: [766, 810, 127],
    alt: 'A climber in a harness clipped to an auto-belay line.',
  },
  {
    slug: 'push-ups',
    grid: 'blackbg.png',
    disc: [1228, 811, 127],
    alt: 'A climber in a push-up position, shoulders set over the hands.',
  },
] as const satisfies readonly IconSlice[];

export type IconSlug = (typeof ICON_SLICES)[number]['slug'];

const BY_SLUG: ReadonlyMap<string, IconSlice> = new Map(
  ICON_SLICES.map((slice) => [slice.slug, slice]),
);

/** `climbing_aspect.key` -> icon, the FALLBACK tier. Three aspects are deliberately absent —
 *  there is no art for them — and `flexibility` is art with no aspect to hang it on. */
export const ASPECT_ICONS = {
  finger_strength: 'finger-strength',
  general_strength: 'strength',
  power: 'power',
  power_endurance: 'power-endurance',
  endurance: 'endurance',
  technique: 'technique',
  mobility: 'mobility',
} as const satisfies Record<string, IconSlug>;

/** `exercise.key` -> icon, and it WINS over the aspect: an exercise with its own art shows it. */
export const EXERCISE_ICONS = {
  max_hangs_20mm: 'hangboard-routine',
  hangboard_repeaters: 'hangboard-routine',
  hangboard_min_edge_hangs: 'hangboard-routine',
  weighted_max_hangs: 'hangboard-routine',
  open_hand_drag_hangs: 'hangboard-routine',
  hangboard_density_hangs: 'hangboard-routine',
  front_lever_progression: 'front-lever',
  reverse_wrist_curls: 'reverse-wrist-curls',
  dyno_and_swing_practice: 'dyno',
  boulder_four_by_four: 'four-by-four',
  auto_belay_interval_laps: 'autobelay',
  auto_belay_endurance_laps: 'autobelay',
  push_ups_with_scapular_control: 'push-ups',
  ring_dips_and_push_ups: 'push-ups',
  banded_hip_and_hamstring_flow: 'pancake',
} as const satisfies Record<string, IconSlug>;

/** Path relative to `web/public/`. Hand this to `publicUrl`, never to a bare `src`. */
export function iconPath(slug: string): string {
  return `${ICON_DIR}/${slug}.webp`;
}

/** The exercise's own icon, else its aspect's, else null — which the caller draws as the
 *  placeholder mark, never as nothing. */
export function iconFor(exerciseKey: string, aspectKey: string | null): IconSlice | null {
  const slug =
    exerciseKey in EXERCISE_ICONS
      ? EXERCISE_ICONS[exerciseKey as keyof typeof EXERCISE_ICONS]
      : aspectKey !== null && aspectKey in ASPECT_ICONS
        ? ASPECT_ICONS[aspectKey as keyof typeof ASPECT_ICONS]
        : null;
  return slug === null ? null : (BY_SLUG.get(slug) ?? null);
}
