/**
 * Inline SVG icons.
 *
 * **Inline markup, never `<img src="…svg">`, and that is a CSP constraint, not a preference.**
 * The production document policy is `img-src 'self' data:` — an external icon URL is simply
 * blocked, and even a self-hosted one is a separate request that cannot inherit `currentColor`
 * or the surrounding font size. As React elements they cost nothing at runtime beyond the markup
 * and they recolour with the text they sit beside.
 *
 * **Every icon here is `aria-hidden` with `focusable="false"`, and every icon on the page has a
 * text label next to it.** Two reasons, in order:
 *
 *  1. an icon that is not hidden joins the accessible name of its button, so
 *     `getByRole('button', { name: 'Explore the demo' })` would stop matching — and more to the
 *     point, a screen reader would read the decoration;
 *  2. icon-ONLY controls are deferred to the session player, deliberately. The precedent in this
 *     tree is PR #7's update bar, which dismisses with the word "Later" rather than a bare "x".
 *     Icons here buy visual clarity, not compactness. If an icon-only control ever does ship it
 *     needs its own `aria-label` **and** the 44px `--ct-tap` floor on both axes.
 *
 * `focusable="false"` is for IE/legacy Edge, where an inline `<svg>` is otherwise a tab stop —
 * outside our support baseline, but it is one attribute and it is the reason it is here.
 */
import type { SVGProps } from 'react';

/** `viewBox` is fixed by the shared 24px grid, so it is not a caller's to set. */
type IconProps = Omit<SVGProps<SVGSVGElement>, 'viewBox' | 'children'>;

/**
 * The shared frame. Stroke-based on a 24px grid, sized in `em` by `_landing.scss` so an icon
 * tracks its label, and `stroke="currentColor"` so it inherits the button or heading colour
 * including the disabled and pressed states.
 */
function Icon({
  className = 'ct-app__icon',
  children,
  ...props
}: IconProps & { children: SVGProps<SVGSVGElement>['children'] }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

/** Explore/open the demo. A play glyph, filled so it reads at 16px where a stroked one does not. */
export function IconPlay(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 5.5 19 12 8 18.5z" fill="currentColor" />
    </Icon>
  );
}

/** Log in — an arrow entering a doorway, not a padlock: this is an action, not a state. */
export function IconSignIn(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M14 3h5a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1h-5" />
      <path d="M10 8l4 4-4 4" />
      <path d="M14 12H3" />
    </Icon>
  );
}

/** Create account. */
export function IconUserPlus(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="9.5" cy="8" r="3.5" />
      <path d="M3 20c0-3.3 2.9-5.5 6.5-5.5s6.5 2.2 6.5 5.5" />
      <path d="M19 8.5v5M16.5 11h5" />
    </Icon>
  );
}

/** The target grade the whole plan is built around. */
export function IconTarget(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/** The guided session player: work and rest, counted. */
export function IconTimer(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="13" r="8" />
      <path d="M12 9v4l2.5 2" />
      <path d="M9 2h6" />
    </Icon>
  );
}

/** The training diary. */
export function IconJournal(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
      <path d="M4 17h15" />
      <path d="M8 7h7M8 11h7" />
    </Icon>
  );
}

/** Equipment and access — what the plan is filtered against. */
export function IconSliders(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 21V14M5 10V3M12 21v-9M12 8V3M19 21v-5M19 12V3" />
      <path d="M2.5 12h5M9.5 8h5M16.5 14h5" />
    </Icon>
  );
}

/**
 * The nav's five glyphs, and the theme switch's three.
 *
 * All eight are on the shared `Icon` frame, so they are one family with the icons above: the
 * same 24px grid, the same 1.75 stroke, `currentColor`, `aria-hidden` and `focusable="false"`.
 * ⚠️ In the nav they sit **beside a visible label** and add nothing to the accessible name —
 * they are decoration on a control that already reads correctly with images off.
 */

/** Dashboard: the overview, as tiles. */
export function IconGrid(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </Icon>
  );
}

/**
 * The plan: a week, laid out in blocks.
 *
 * ⚠️ Redrawn in round 6, and the reason is SHAPE, not concept. It was a calendar — an upright
 * rounded rectangle with a header rule — and `IconJournal` is an upright rounded rectangle with
 * horizontal rules. At 16px, icon-only, those two silhouettes are the same object. This one is now
 * landscape with VERTICAL dividers, so the pair differs in both aspect ratio and internal line
 * direction, which is what the eye actually sorts on at that size.
 */
export function IconCalendar(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="2.75" y="7" width="18.5" height="10" rx="2" />
      <path d="M8.9 7v10M15.1 7v10" />
    </Icon>
  );
}

/** The profile: the person whose plan it is. */
export function IconUser(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="8" r="3.75" />
      <path d="M4.75 20.5a7.25 7.25 0 0 1 14.5 0" />
    </Icon>
  );
}

/** Theme: light. */
export function IconSun(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="4.25" />
      <path d="M12 2.5v2.25M12 19.25v2.25M2.5 12h2.25M19.25 12h2.25M5.25 5.25l1.6 1.6M17.15 17.15l1.6 1.6M18.75 5.25l-1.6 1.6M6.85 17.15l-1.6 1.6" />
    </Icon>
  );
}

/** Theme: dark. */
export function IconMoon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
    </Icon>
  );
}

/**
 * Keep the screen on / let it sleep, in the session player's control bar.
 *
 * A crescent **with the two z's**, and the z's are the whole reason this is not `IconMoon`: the
 * bare crescent is already spoken for by the theme switch, two screens away, and one glyph
 * meaning "dark" in the nav and "screen timeout" in the player is the kind of collision nobody
 * notices until they are looking at both at once.
 */
export function IconSleep(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M16.5 15.5A6.5 6.5 0 0 1 8 7a6.5 6.5 0 1 0 8.5 8.5z" />
      <path d="M15.5 3h4l-4 5h4" />
    </Icon>
  );
}

/**
 * Log out — the power symbol (IEC 5009), not an arrow leaving a door.
 *
 * Kilian's call (round 6). It also survives the icon-only nav better than the arrow did: a broken
 * ring with a stem is a silhouette people read instantly at 16px, where a door-and-arrow becomes
 * two ambiguous strokes.
 */
export function IconPower(props: IconProps) {
  return (
    <Icon {...props}>
      {/* A LONG stem and a WIDE gap, deliberately: `IconTimer` is also a ring with a mark at
          twelve o'clock, and at 16px a short stem over a nearly-closed ring is the same
          silhouette as a stopwatch. This one is unmistakably broken open. */}
      <path d="M12 2.75v8.25" />
      <path d="M7 7.1a7.2 7.2 0 1 0 10 0" />
    </Icon>
  );
}

/**
 * The brand mark, as a THEMED tile — the same drawing as `web/public/mark.svg`, inlined.
 *
 * ## Why it is inline and not that file
 *
 * An `<img src>` cannot inherit anything from the host document's CSS: no `currentColor`, no
 * custom properties. So an external file can only ever be the one green it was authored in,
 * which is exactly what a themed tile cannot be. `public/mark.svg` therefore **stays untouched**
 * as the PWA icon source (`pwa-assets.config.ts` generates every launcher icon from it, and its
 * opaque background and hardcoded hexes are deliberate — a maskable icon a launcher crops must
 * not be transparent). This is a second expression of the same drawing, and the two must be kept
 * in step by hand.
 *
 * ## Why it does not use the shared `Icon` frame
 *
 * Checked rather than assumed: `Icon` is `fill="none"` + `stroke="currentColor"` on a **fixed
 * 24px grid**, and `IconProps` deliberately `Omit`s `viewBox` ("not a caller's to set"). A filled
 * tile needs a fill, and this drawing's coordinates are on a 512 grid. Forcing it in would mean
 * loosening that type for one caller. It keeps the family's conventions instead — `aria-hidden`,
 * `focusable="false"`, sized in `em` so it tracks the title beside it.
 *
 * ## The three tones, and the geometry
 *
 * Tile `--ct-accent`, holds knocked out in `--ct-accent-fg`, and the route a QUIET tone between
 * the two (`_chrome.scss` carries the measurements). That is the app's existing BUTTON pairing
 * plus a mix of it, so no new colour pair enters the system — `contrast.test.ts:87` already
 * asserts `['accent-fg', 'accent']` in both schemes.
 *
 * ⚠️ **Not one coordinate, stroke width or radius is changed from `mark.svg`.** The only edit is
 * the `viewBox`: `0 0 512 512` becomes `122 118 284 284`, which crops the maskable icon's
 * safe-zone padding — the drawing occupies just 48% of that 512 square, because a launcher may
 * crop it to a circle. Nothing here will. Cropping rather than re-weighting is what keeps this
 * the same drawing: at a 22px render the 18-unit stroke lands at ~1.5px against the icon
 * family's 1.75px, and the 26-unit holds at ~2.2px radius, so it reads at nav size without
 * touching the artwork.
 */
export function BrandMark() {
  return (
    <svg
      className="ct-app__brand-mark"
      viewBox="122 118 284 284"
      aria-hidden="true"
      focusable="false"
    >
      {/* The tile. `currentColor` so one CSS declaration themes it. */}
      <rect x="122" y="118" width="284" height="284" fill="currentColor" />
      {/* ⚠️ Two classes, not one: the route is a QUIET tone and the holds are the bright
          knockout, which is the figure-ground relationship `mark.svg` is drawn with. Knocking
          both out at full strength reads as a fat zigzag with lumps. See `_chrome.scss` for the
          measured tones. */}
      <path
        className="ct-app__brand-route"
        d="M168 352 L232 264 L312 296 L352 176"
        strokeWidth={18}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle className="ct-app__brand-hold" cx="168" cy="352" r="26" />
      <circle className="ct-app__brand-hold" cx="232" cy="264" r="26" />
      <circle className="ct-app__brand-hold" cx="312" cy="296" r="26" />
      <circle className="ct-app__brand-hold" cx="352" cy="176" r="34" />
    </svg>
  );
}

/**
 * Home, for the signed-out nav.
 *
 * A peaked roof over a body, checked against the six already in the nav before settling on it:
 * `IconGrid` is four squares, `IconCalendar` a landscape strip, `IconTimer` and `IconPower` rings,
 * `IconUser` a head and shoulders, `IconJournal` an upright rect with rules — and this is the only
 * one with a diagonal apex, which is what the eye sorts on at 16px. It does share the upright body
 * with `IconJournal`, and the roof is what separates them.
 */
export function IconHome(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.25 11 12 3.75 20.75 11" />
      <path d="M5.6 9.35V20.25h12.8V9.35" />
    </Icon>
  );
}

/** The burger. Three rules, and nothing clever. */
export function IconMenu(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.75 6.5h16.5M3.75 12h16.5M3.75 17.5h16.5" />
    </Icon>
  );
}

/**
 * Injuries — a dressing, at an angle.
 *
 * The one glyph in the section-heading set with no existing candidate: nothing in this file was
 * medical. Diagonal, so it does not collide with any of the uprights.
 */
export function IconBandage(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="1.9" y="8.4" width="20.2" height="7.2" rx="3.6" transform="rotate(-45 12 12)" />
      <path d="M9.6 9.6 14.4 14.4M14.4 9.6 9.6 14.4" />
    </Icon>
  );
}

/**
 * The session player's control set — eight glyphs, all icon-only, all on the shared frame.
 *
 * ⚠️ **This is the place the file's own "icon-only controls are deferred to the session player"
 * note was pointing at**, so the price of admission is paid by every caller: an `aria-label`
 * that says what pressing DOES, a matching `title` for the pointer, and the 44px `--ct-tap`
 * floor `&__button--icon` supplies. The glyphs are chosen for SILHOUETTE, because on this screen
 * they sit in a row with chalky hands and no labels between them: a filled triangle (start), a
 * ring-and-arrow (restart), two bars (pause), a double chevron (next set), a chevron into a bar
 * (end this one now), a tick, a cross, and a speaker. No two share an outline.
 */

/** Pause — two bars. Filled, like `IconPlay`, so the pair reads as one control at 16px. */
export function IconPause(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="7" y="5" width="3.5" height="14" rx="1.2" fill="currentColor" stroke="none" />
      <rect x="13.5" y="5" width="3.5" height="14" rx="1.2" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/**
 * Restart — a ring with an arrowhead, deliberately NOT a second play triangle.
 *
 * A running item offers Resume and Restart side by side, and two triangles there is a control
 * whose two meanings are "carry on" and "throw that away and do it again". The circular arrow is
 * the one glyph everybody already reads as "from the top".
 */
export function IconRestart(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20.5 3.5v4.2h-4.2" />
    </Icon>
  );
}

/** Next set — a double chevron. Rightward like `IconPlay`, but hollow and doubled. */
export function IconNextSet(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M6 6l6 6-6 6" />
      <path d="M13 6l6 6-6 6" />
    </Icon>
  );
}

/** "Didn't finish it" — a chevron into a bar. Neither the double chevron (which logs the sets
 *  it crosses) nor the cross (which ends the item): it sits in the same row as both. */
export function IconEndPhase(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7 6l6 6-6 6" />
      <path d="M17 5.5v13" />
    </Icon>
  );
}

/** "I did this one" — a tick. */
export function IconCheck(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />
    </Icon>
  );
}

/** "I did not do this" — a cross, the tick's counterpart and never a close button here. */
export function IconCross(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M6 6l12 12M18 6 6 18" />
    </Icon>
  );
}

/** Cues on — a speaker with two waves. */
export function IconSound(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 9.5h3.2L12 5.5v13L7.2 14.5H4z" />
      <path d="M15.6 9.2a4 4 0 0 1 0 5.6" />
      <path d="M18.2 6.6a7.6 7.6 0 0 1 0 10.8" />
    </Icon>
  );
}

/** Cues off — the same speaker, struck through. The silhouette differs by the diagonal. */
export function IconMuted(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 9.5h3.2L12 5.5v13L7.2 14.5H4z" />
      <path d="M16 9.5l5 5M21 9.5l-5 5" />
    </Icon>
  );
}
