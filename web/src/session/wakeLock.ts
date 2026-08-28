import { useEffect, useState, useSyncExternalStore } from 'react';

/**
 * Screen Wake Lock, as a **user-owned toggle** and a progressive enhancement.
 *
 * ⚠️ **Never acquired silently and never on Start.** The only honest justification is that it
 * saves unlocking a phone with chalky hands between sets, so the climber owns the choice.
 *
 * ⚠️ **`wakeLockAvailable()` false means HIDE the control** — not disable it, and no toast, no
 * "unsupported browser" notice. Firefox on Android has no `navigator.wakeLock` at all, and an
 * installed iOS PWA below 18.4 exposes one that never holds. A control promising something
 * impossible is worse than no control; the OS screen timeout is a fine outcome.
 *
 * ⚠️ **`held` IS THE SENTINEL'S REAL STATE, NOT THE USER'S INTENT.** The OS releases a lock
 * silently whenever the tab is backgrounded, so the switch renders from `held` and the hook
 * re-acquires on `visibilitychange`. A switch reading "on" over a released lock is a lie the
 * climber discovers when the screen dies mid-set.
 *
 * ⚠️ **Never load-bearing.** `useSessionRun` resyncs from wall-clock time on every
 * `visibilitychange` whether or not a lock was ever held, so the lock may be absent, refused,
 * toggled off or silently released and the session is still correct.
 */

export const KEEP_SCREEN_ON_KEY = 'ct:keepScreenOn';

/** The oldest iOS that holds a wake lock inside an installed PWA. */
const IOS_WAKE_LOCK_MAJOR = 18;
const IOS_WAKE_LOCK_MINOR = 4;

function isIos(): boolean {
  const agent = navigator.userAgent;
  if (/iPad|iPhone|iPod/.test(agent)) return true;
  // iPadOS 13+ in desktop mode reports as a Mac; the touch count is the only tell.
  return navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
}

/** Installed, by either signal: iOS Safari's own legacy flag or the standard display mode. */
function isStandalone(): boolean {
  const legacy = (navigator as Navigator & { standalone?: boolean }).standalone;
  if (legacy === true) return true;
  try {
    return window.matchMedia('(display-mode: standalone)').matches;
  } catch {
    return false;
  }
}

/** ⚠️ An **unparseable** iOS version reads as too old. A desktop-mode iPad UA carries the Mac
 * version, and guessing high would ship the very control this rule exists to hide. */
function iosHoldsWakeLock(): boolean {
  const match = /OS (\d+)[._](\d+)/.exec(navigator.userAgent);
  if (match === null) return false;
  const major = Number(match[1]);
  const minor = Number(match[2]);
  if (!Number.isFinite(major) || !Number.isFinite(minor)) return false;
  if (major !== IOS_WAKE_LOCK_MAJOR) return major > IOS_WAKE_LOCK_MAJOR;
  return minor >= IOS_WAKE_LOCK_MINOR;
}

/** The whole decision behind rendering the toggle at all. */
export function wakeLockAvailable(): boolean {
  try {
    if (typeof navigator === 'undefined') return false;
    if (typeof navigator.wakeLock?.request !== 'function') return false;
    if (isStandalone() && isIos() && !iosHoldsWakeLock()) return false;
    return true;
  } catch {
    return false;
  }
}

// The preference — `theme.ts`'s store shape, for `theme.ts`'s reason: external state that is
// read during render, which `set-state-in-effect` correctly refuses to let an effect produce.

function readPreference(): boolean {
  try {
    return window.localStorage.getItem(KEEP_SCREEN_ON_KEY) === 'true';
  } catch {
    return false;
  }
}

let preference = readPreference();
const preferenceListeners = new Set<() => void>();

function preferenceSnapshot(): boolean {
  return preference;
}

function subscribePreference(onChange: () => void): () => void {
  preferenceListeners.add(onChange);
  return () => {
    preferenceListeners.delete(onChange);
  };
}

export function getKeepScreenOn(): boolean {
  return preference;
}

/** What the climber asked for, persisted. Saying it and doing it are two different things —
 * `useWakeLock` owns the doing, and `held` owns the truth. */
export function setKeepScreenOn(next: boolean): void {
  if (next === preference) return;
  preference = next;
  try {
    window.localStorage.setItem(KEEP_SCREEN_ON_KEY, String(next));
  } catch {
    // A blocked or full store costs the choice its persistence, not its effect this session.
  }
  for (const listener of preferenceListeners) listener();
}

export function useKeepScreenOn(): boolean {
  return useSyncExternalStore(subscribePreference, preferenceSnapshot, preferenceSnapshot);
}

// The sentinel — one per document, so module state rather than component state: two players
// cannot exist, and a lock that outlived one component would be invisible to the next.

let sentinel: WakeLockSentinel | null = null;
let acquiring = false;
let held = false;
/**
 * ⚠️ **The cancellation flag for an acquire IN FLIGHT, and the fix for a real bug.**
 *
 * `request()` is a round trip to the browser process, so a release can land while one is in
 * the air. Without this the resolved sentinel was published anyway: `held` went true over a
 * lock nobody wanted, the effect never re-ran (its `active` dep had not changed), and from
 * then on `held` and the preference disagreed — which makes every other click a visible
 * no-op. `sessionResume.test.tsx` carries both halves as regressions.
 */
let wanted = false;
const heldListeners = new Set<() => void>();

function heldSnapshot(): boolean {
  return held;
}

function subscribeHeld(onChange: () => void): () => void {
  heldListeners.add(onChange);
  return () => {
    heldListeners.delete(onChange);
  };
}

function publishHeld(next: boolean): void {
  if (next === held) return;
  held = next;
  for (const listener of heldListeners) listener();
}

/** Let go of one sentinel. Already-gone is the common case, not a failure. */
async function releaseSentinel(target: WakeLockSentinel): Promise<void> {
  if (target.released) return;
  try {
    await target.release();
  } catch {
    // The OS released it first.
  }
}

/**
 * Ask for a lock. **Rejection is a normal, expected outcome** — low battery and OS policy both
 * refuse — so it is reflected in `held` and never surfaced as an error.
 *
 * Hidden tabs are skipped rather than attempted: `request()` rejects outright while hidden, and
 * the `visibilitychange` listener will call this again the moment the tab comes back.
 *
 * ⚠️ **Safe to call when the preference is ALREADY on.** That is what makes a click on the
 * player's toggle do something after the OS has silently dropped the lock: the stored
 * preference has not changed, so `setKeepScreenOn` is a no-op and only this re-arms it.
 */
export async function acquireWakeLock(): Promise<void> {
  wanted = true;
  if (acquiring) return;
  if (sentinel !== null && !sentinel.released) return;
  if (!wakeLockAvailable()) return;
  if (document.visibilityState !== 'visible') return;
  acquiring = true;
  try {
    const next = await navigator.wakeLock.request('screen');
    if (!wanted) {
      // Released while this was in the air — see `wanted`.
      publishHeld(false);
      await releaseSentinel(next);
      return;
    }
    sentinel = next;
    next.addEventListener('release', () => {
      if (sentinel === next) sentinel = null;
      publishHeld(false);
    });
    publishHeld(!next.released);
  } catch {
    publishHeld(false);
  } finally {
    acquiring = false;
  }
}

/** Release on finish, on abort and on unmount — never leak a lock past the run. */
export async function releaseWakeLock(): Promise<void> {
  wanted = false;
  const current = sentinel;
  sentinel = null;
  publishHeld(false);
  if (current === null) return;
  await releaseSentinel(current);
}

export interface WakeLockView {
  /** Render the toggle only when this is `true`. There is no disabled state. */
  readonly available: boolean;
  /** ⚠️ **The switch's checked value.** The sentinel's real state, never the click. */
  readonly held: boolean;
  /** What the caller asked for, after availability. For a "reconnecting" hint, nothing more. */
  readonly wanted: boolean;
}

/**
 * Hold a screen wake lock for as long as `wanted` stays true, and tell the truth about it.
 *
 * Pass `keepScreenOn && status === 'running'`: flipping `wanted` to `false` on finish or abort
 * releases through the effect's cleanup, so "release on finish" needs no separate call site and
 * cannot be forgotten.
 */
export function useWakeLock(wanted: boolean): WakeLockView {
  const [available] = useState(wakeLockAvailable);
  const active = wanted && available;
  const isHeld = useSyncExternalStore(subscribeHeld, heldSnapshot, heldSnapshot);

  useEffect(() => {
    if (!active) {
      void releaseWakeLock();
      return;
    }
    void acquireWakeLock();
    const onVisibility = (): void => {
      if (document.visibilityState === 'visible') void acquireWakeLock();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      void releaseWakeLock();
    };
  }, [active]);

  return { available, held: isHeld, wanted: active };
}
