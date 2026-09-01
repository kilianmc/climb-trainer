import { IconSleep } from '../ui/icons';

/**
 * The "Keep screen on" control — icon-only, and **only inside a running session**.
 *
 * ⚠️ **`available === false` means RENDER NOTHING.** Not a disabled button, not a toast, not an
 * "unsupported browser" line: Firefox on Android has no `navigator.wakeLock` and an installed
 * iOS PWA below 18.4 has one that never holds, and a control promising something impossible is
 * worse than no control. The OS screen timeout is a fine outcome.
 *
 * ⚠️ **`held` is the SENTINEL's real state, never the click.** The OS releases a lock silently
 * whenever the tab is backgrounded and can refuse one outright on low battery, so a player
 * rendered from intent is a lie the climber discovers when the screen dies mid-set. The caller
 * must therefore make the press act on what is SHOWN — see `useSessionRun.toggleKeepScreenOn`.
 *
 * The a11y contract is `ui/ThemeSwitch.tsx`'s, which is this tree's other icon-only two-state
 * button: the `aria-label` says what pressing DOES rather than naming the icon, the state is
 * announced separately through an always-present polite live region, and the hover text is a
 * `title` so the label is available to a mouse without a second element in the bar.
 */
export function KeepScreenOn({
  available,
  held,
  onToggle,
}: {
  available: boolean;
  held: boolean;
  onToggle: () => void;
}) {
  if (!available) return null;

  const action = held ? 'Let the screen turn off' : 'Keep the screen on';

  return (
    <>
      <button
        type="button"
        // The fill is the only visual carrier of the state, so it is a real modifier class and
        // not an interpolation — `markupCss.test.ts` sees both literals.
        className={
          held
            ? 'ct-app__button ct-app__button--icon ct-app__button--primary'
            : 'ct-app__button ct-app__button--icon'
        }
        aria-label={action}
        title={action}
        onClick={onToggle}
      >
        <IconSleep />
      </button>
      <span className="ct-app__sr-only" aria-live="polite">
        {held ? 'Screen: staying on' : 'Screen: turning off as usual'}
      </span>
    </>
  );
}
