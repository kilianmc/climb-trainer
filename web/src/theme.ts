import { useSyncExternalStore } from 'react';

/**
 * System / Light / Dark, and the one place the choice is kept.
 *
 * ## Two states, seeded from the OS
 *
 * Kilian's call (round 5): a sun and a moon, no third position. The OS preference is still
 * honoured where it matters — **the first visit reads `prefers-color-scheme` and starts there**,
 * so a dark-mode visitor opens dark — and after that it is a plain toggle. The cost is real and
 * accepted: once a choice is stored, changing the OS scheme no longer moves the app.
 *
 * ## How the override wins
 *
 * `data-theme` is set on the `.ct-app` element and `_tokens.scss::overrides` re-declares the
 * token block behind an attribute selector: a media query carries no specificity, so the
 * attribute beats `declare`'s `prefers-color-scheme` block regardless of source order. With the
 * System position gone the attribute is now always present — the media query is what seeds the
 * FIRST choice (through `matchMedia`), not what applies it.
 *
 * ⚠️ **The attribute goes on `.ct-app` and nowhere else.** Not `<html>`, not `<body>`: in the
 * federated mount those belong to kilianmc.com, and this app writes to its own element only.
 * `global.scss` bridges the standalone document canvas with `body:has(.ct-app[data-theme=…])`,
 * which is legal there because that file never ships to the shell.
 *
 * ## Storage
 *
 * `ct:theme`, namespaced per CLAUDE.md's rule that in the federated mount `localStorage` is the
 * SHELL's storage. It is the second `ct:` key in the app and the only durable one that matters
 * — the access token is deliberately in memory and never here.
 *
 * ## ⚠️ Two known gaps, both structural, neither a correctness bug
 *
 * Kilian's call: **documented, not fixed.** They are recorded here rather than in an issue
 * because the next person to touch this file is the one who needs to know.
 *
 * **1. `index.html`'s two `theme-color` metas follow the OS, not the override.** They select
 * with `media="(prefers-color-scheme: …)"`, so a manual choice leaves the browser's own chrome
 * (the address bar, the task switcher) on the OS scheme while the page is on the chosen one.
 * Closing it needs JS — a meta tag cannot read a `data-` attribute — and that JS must be
 * **standalone-only**: in the federated mount the document head belongs to kilianmc.com, so
 * writing `theme-color` there would recolour the portfolio's own chrome. It therefore belongs
 * beside `main.tsx` behind a mount check, which is the same shape as the service-worker rule,
 * and it is not worth that machinery for a strip of browser UI.
 *
 * **2. There is no way to apply the choice before first paint.** The usual fix is a blocking
 * inline `<script>` in `index.html` that sets the attribute before the body renders; CSP here
 * is `script-src 'self'` with no `unsafe-inline`, and the correct response to that is not to
 * weaken the policy for a flash. So a visitor whose OS is light and whose stored choice is
 * dark sees one light frame before React mounts. `.ct-app` is the only themed element and it
 * does not exist until then, so what flashes is the document canvas from `global.scss`.
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
