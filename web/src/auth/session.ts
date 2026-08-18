/**
 * The access token store. **In memory, for the lifetime of one mount, and nowhere else.**
 *
 * Not `localStorage`, not `sessionStorage`, not a cookie this code can read: in the
 * federated mount the app runs on the kilianmc.com origin, so web storage there belongs
 * to the portfolio and is shared with every other project on it. `remote.guard.test.tsx`
 * enforces that; this module is the reason it stays true.
 *
 * A factory rather than a module singleton, deliberately. `remote.tsx` builds one router,
 * one query client and one session per mount instance, so navigating away from the
 * project in the shell and back again starts clean instead of resurrecting a stale
 * principal.
 */

/** Mirrors `server/auth/tokens.py::Scope`. */
export type Scope = 'user' | 'demo';

export interface SessionSnapshot {
  readonly token: string | null;
  readonly scope: Scope | null;
}

/** One frozen object, so `useSyncExternalStore` sees a stable anonymous snapshot. */
const ANONYMOUS: SessionSnapshot = Object.freeze({ token: null, scope: null });

/**
 * Declared as function-typed PROPERTIES, not methods. These are closures over the factory's
 * state and never touch `this`, and the property form is what lets `useSyncExternalStore`
 * take `session.subscribe` / `session.get` directly — `unbound-method` correctly rejects
 * detaching a method, and the fix is to stop pretending these are methods.
 */
export interface SessionStore {
  readonly get: () => SessionSnapshot;
  readonly set: (token: string, scope: Scope) => void;
  readonly clear: () => void;
  readonly subscribe: (listener: () => void) => () => void;
  /** `Authorization` when we hold a token, an empty object when we do not. */
  readonly header: () => Record<string, string>;
  /**
   * Counts **deliberate session transitions** — every `set` and every `clear`, whether or not
   * the snapshot visibly changed. It exists so an in-flight refresh can tell whether the
   * session it is about to write into is still the one it started from.
   *
   * Without it, a refresh that resolves *after* a logout re-populates the store with a token
   * whose refresh family the server has already revoked: the nav shows a signed-in user who
   * cannot refresh, and the refresh response's `Set-Cookie` lands after logout cleared the
   * jar. The same read applies to a login or an "explore the demo" click landing mid-refresh
   * — in every case the deliberate action wins and the refresh must not resurrect anything.
   *
   * Bumped on `clear()` **unconditionally**, including from an already-anonymous store: a
   * demo mint starting from anonymous still has to invalidate a bootstrap refresh in flight.
   */
  readonly generation: () => number;
}

export function createSessionStore(): SessionStore {
  let snapshot: SessionSnapshot = ANONYMOUS;
  let generation = 0;
  const listeners = new Set<() => void>();

  function emit(): void {
    for (const listener of listeners) listener();
  }

  return {
    get: () => snapshot,
    generation: () => generation,

    set: (token, scope) => {
      generation += 1;
      snapshot = Object.freeze({ token, scope });
      emit();
    },

    clear: () => {
      // The generation bump is UNCONDITIONAL — see its docstring. Only the notification is
      // guarded, so a no-op clear does not re-render every subscriber; `authClient.ts` clears
      // before every POST /api/auth/*, most of them from an already-anonymous store.
      generation += 1;
      if (snapshot === ANONYMOUS) return;
      snapshot = ANONYMOUS;
      emit();
    },

    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    header: () => (snapshot.token === null ? {} : { authorization: `Bearer ${snapshot.token}` }),
  };
}
