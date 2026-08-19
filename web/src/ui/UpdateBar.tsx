import { useSyncExternalStore } from 'react';

import { dismissUpdate, getSnapshot, subscribe, updateSW } from '../pwa/updatePrompt';
import '../styles/update-bar.scss';

/**
 * The `registerType: 'prompt'` half of the PWA: a new build is precached but does nothing until
 * the visitor asks for it.
 *
 * ⚠️ Rendered from `main.tsx` ONLY. It imports the module that registers the service worker, and
 * `remote.tsx` shares the route tree — so putting this in `__root.tsx` or any route would scope a
 * service worker to kilianmc.com. See `pwa/updatePrompt.ts`.
 *
 * The wrapper is always mounted so the live region exists before it has anything to say; an
 * `aria-live` region inserted together with its own content is announced unreliably. It never
 * moves focus: someone mid-set does not want the caret yanked out of a rep counter. Both controls
 * are real buttons at the `--ct-tap` floor, and "Later" is a word rather than an × so it has an
 * accessible name and a hittable width without an `aria-label`.
 */
export function UpdateBar() {
  const waiting = useSyncExternalStore(subscribe, getSnapshot, () => false);

  return (
    <div className="ct-update-bar" role="status" aria-live="polite">
      {waiting && (
        <div className="ct-update-bar__panel">
          <p className="ct-update-bar__text">New version available</p>
          <button
            type="button"
            className="ct-update-bar__action"
            onClick={() => {
              void updateSW();
            }}
          >
            Reload
          </button>
          <button type="button" className="ct-update-bar__dismiss" onClick={dismissUpdate}>
            Later
          </button>
        </div>
      )}
    </div>
  );
}
