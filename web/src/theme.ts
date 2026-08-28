import { useSyncExternalStore } from 'react';

/**
 * Light / Dark, and the one place the choice is kept.
 *
 * Two states, no third position: the **first visit** reads `prefers-color-scheme` through
 * `matchMedia` and starts there, and after that it is a plain toggle. Cost accepted — once a
 * choice is stored, changing the OS scheme no longer moves the app.
 *
 * `data-theme` is set on `.ct-app` and `_tokens.scss::overrides` re-declares the tokens behind
 * an attribute selector: **a media query carries no specificity**, so the attribute beats
 * `declare`'s `prefers-color-scheme` block whatever the source order. ⚠️ **The attribute goes on
 * `.ct-app` and nowhere else** — not `<html>`, not `<body>`, which belong to kilianmc.com in the
 * federated mount. `global.scss` bridges the standalone document canvas with
 * `body:has(.ct-app[data-theme=…])`, legal there because that file never ships to the shell.
 * Stored under `ct:theme`, namespaced because in the federated mount `localStorage` is the
 * SHELL's storage.
 *
 * ## ⚠️ Two known gaps. Kilian's call: documented, not fixed
 *
 * 1. **`index.html`'s two `theme-color` metas follow the OS, not the override**, because they
 *    select with `media="(prefers-color-scheme: …)"`. Closing it needs JS (a meta tag cannot
 *    read a `data-` attribute) and that JS must be **standalone-only**, since in the federated
 *    mount the document head belongs to the portfolio. Not worth the machinery for a strip of
 *    browser chrome.
 * 2. **The choice cannot be applied before first paint.** The usual fix is a blocking inline
 *    `<script>`, and CSP here is `script-src 'self'` with no `unsafe-inline` — the right
 *    response to which is not to weaken the policy for a flash. One light frame before React
 *    mounts, and what flashes is the document canvas, not any app surface.
 */
export type ThemeChoice = 'light' | 'dark';

const KEY = 'ct:theme';

function isChoice(value: unknown): value is ThemeChoice {
  return value === 'light' || value === 'dark';
}

/** What the OS asks for, and the seed for a first visit. */
function osPrefers(): ThemeChoice {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function read(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(KEY);
    return isChoice(stored) ? stored : osPrefers();
  } catch {
    return osPrefers();
  }
}

let choice: ThemeChoice = read();
const listeners = new Set<() => void>();

/** A snapshot, and a stable one: `useSyncExternalStore` compares it by identity. */
function snapshot(): ThemeChoice {
  return choice;
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

export function setThemeChoice(next: ThemeChoice): void {
  if (next === choice) return;
  choice = next;
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    // A blocked or full store costs the choice its persistence, not its effect.
  }
  for (const listener of listeners) listener();
}

/** The other one. */
export function otherThemeChoice(current: ThemeChoice): ThemeChoice {
  return current === 'dark' ? 'light' : 'dark';
}

/**
 * ⚠️ `useSyncExternalStore` rather than `useState` + an effect: the store is read during
 * render and `react-hooks`' `set-state-in-effect` rule rejects the alternative — correctly,
 * since this is external state and not a render result.
 */
export function useThemeChoice(): ThemeChoice {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
