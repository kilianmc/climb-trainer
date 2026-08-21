import { useId } from 'react';

/**
 * The completion bar, and the single polite live region that goes with it.
 *
 * The accessibility contract here is fixed by the plan and every clause of it is a real
 * failure mode:
 *
 * - **`role="progressbar"` with an accessible NAME.** A nameless progressbar is the most
 *   common failure of this component — the value is announced with nothing to attach it
 *   to ("42 percent" of what?). The name comes from `aria-labelledby` pointing at the
 *   visible label, so the sighted and announced names cannot drift apart.
 * - **Never colour alone.** The percentage is TEXT, in `--ct-fg` on `--ct-surface-1`,
 *   which `contrast.test.ts` already proves at 4.5:1 in both schemes. The fill is
 *   decoration; it carries a hairline so it is still visible without relying on hue.
 * - **One live region, announcing at step boundaries only.** Per-percent announcements
 *   flood a screen reader and convey nothing. The region is rendered ALWAYS, empty when
 *   there is nothing to say — a live region added to the DOM at the same moment as its
 *   text is frequently not announced at all.
 * - **The fill transition sits under `prefers-reduced-motion`** (`_profile.scss`) while
 *   the number updates instantly, because reduced motion is not reduced information.
 *
 * No `position: fixed` and no viewport units: both mounts share this route tree, and in
 * the federated mount both resolve against kilianmc.com's viewport.
 */
export interface ProfileProgressProps {
  /** 0-100. Always a real count of what is done — see `completion.ts`. */
  percent: number;
  /** Visible and announced name of the bar. */
  label: string;
  /**
   * Announced politely when it changes. Pass a step-boundary sentence, or `null` where
   * there are no boundaries (the profile editor).
   */
  announcement?: string | null;
}

export function ProfileProgress({ percent, label, announcement = null }: ProfileProgressProps) {
  const labelId = useId();

  return (
    <div className="ct-app__progress">
      <p className="ct-app__progress-head">
        <span id={labelId}>{label}</span>
        <span className="ct-app__progress-value">{percent}% complete</span>
      </p>
      <div
        className="ct-app__progress-track"
        role="progressbar"
        aria-labelledby={labelId}
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span className="ct-app__progress-fill" style={{ inlineSize: `${percent}%` }} />
      </div>
      <p className="ct-app__sr-only" aria-live="polite">
        {announcement ?? ''}
      </p>
    </div>
  );
}
