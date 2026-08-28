import { IconMuted, IconSound } from '../ui/icons';

/**
 * The cue mute, icon-only, in the player's top corner opposite "Keep screen on".
 *
 * ⚠️ **This replaced the "Test sound" button, it did not sit beside it.** The iOS hardware
 * silent switch mutes Web Audio with nothing reporting it, so a climber has to hear a cue before
 * the first hang to know they will hear the rest — and a button whose only job is to prove that
 * is one nobody presses. Unmuting plays a cue instead: the test is the press, in the state where
 * the answer matters.
 *
 * ⚠️ **`available === false` means RENDER NOTHING**, the same rule `KeepScreenOn` follows: with
 * neither `AudioContext` nor `navigator.vibrate` there is nothing to mute, and a switch over two
 * channels that do not exist is worse than no switch.
 *
 * The a11y contract is `ui/ThemeSwitch.tsx`'s: the `aria-label` says what pressing DOES rather
 * than naming the icon, a matching `title` gives a pointer the same words, and the state is
 * announced separately through a polite live region that is always in the DOM.
 */
export function SoundToggle({
  available,
  soundOn,
  onToggle,
}: {
  available: boolean;
  soundOn: boolean;
  onToggle: () => void;
}) {
  if (!available) return null;

  const action = soundOn ? 'Mute the cues' : 'Unmute the cues';

  return (
    <>
      <button
        type="button"
        // A real modifier class, never an interpolation: `markupCss.test.ts` sees both literals.
        className={
          soundOn
            ? 'ct-app__button ct-app__button--icon ct-app__button--primary'
            : 'ct-app__button ct-app__button--icon'
        }
        aria-label={action}
        title={action}
        onClick={onToggle}
      >
        {soundOn ? <IconSound /> : <IconMuted />}
      </button>
      <span className="ct-app__sr-only" aria-live="polite">
        {soundOn ? 'Cues: on' : 'Cues: muted'}
      </span>
    </>
  );
}
