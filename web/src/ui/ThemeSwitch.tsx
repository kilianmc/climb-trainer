import { otherThemeChoice, setThemeChoice, useThemeChoice, type ThemeChoice } from '../theme';
import { IconMoon, IconSun } from './icons';

/**
 * Light/dark, as a sun and a moon. Two states, no visible text — Kilian's call (round 5).
 *
 * ⚠️ **This is the tree's first icon-only control, and `ui/icons.tsx` names the price of
 * admission**: its own `aria-label` and the 44px `--ct-tap` floor on both axes. Both are here,
 * and so is a third thing that a two-state icon toggle gets wrong more often than either:
 *
 * - **The label says what pressing DOES** ("Switch to dark theme"), not what the icon is. A
 *   sun-shaped button labelled "Light" is ambiguous in exactly the way that matters — is that
 *   the current state, or the effect? — and the icon carries the state visually anyway.
 * - **The state is announced separately**, through a visually hidden polite live region that is
 *   always in the DOM (a region added at the same moment as its text is frequently not announced
 *   at all — the same rule `ProfileProgress` follows). It sits OUTSIDE the button on purpose: put
 *   inside, its text would be competing with the button's own `aria-label` for the name.
 * - **A visible label on hover and focus**, like every other icon-only control in the nav — it
 *   was the one without (round 8). `&__nav-tip` rather than `&__nav-label`: this control is
 *   icon-only at EVERY width, so its label is a bubble always and never an inline word.
 * - **`aria-pressed` is deliberately absent.** This is not a toggle that turns one thing on and
 *   off; it swaps between two named states, and "pressed: false" on a moon would announce as
 *   "dark, not pressed", which is worse than the label alone.
 */
const LABELS: Record<ThemeChoice, string> = {
  light: 'light',
  dark: 'dark',
};

export function ThemeSwitch() {
  const choice = useThemeChoice();
  const other = otherThemeChoice(choice);

  return (
    <>
      <button
        type="button"
        className="ct-app__button ct-app__button--quiet ct-app__button--icon"
        aria-label={`Switch to ${LABELS[other]} theme`}
        onClick={() => {
          setThemeChoice(other);
        }}
      >
        {choice === 'dark' ? <IconMoon /> : <IconSun />}
        <span className="ct-app__nav-tip">{`Switch to ${LABELS[other]}`}</span>
      </button>
      <span className="ct-app__sr-only" aria-live="polite">{`Theme: ${LABELS[choice]}`}</span>
    </>
  );
}
