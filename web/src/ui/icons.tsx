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
