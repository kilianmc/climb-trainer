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
}

export function createSessionStore(): SessionStore {
  let snapshot: SessionSnapshot = ANONYMOUS;
  const listeners = new Set<() => void>();

  function emit(): void {
    for (const listener of listeners) listener();
  }

  return {
    get: () => snapshot,

    set: (token, scope) => {
      snapshot = Object.freeze({ token, scope });
      emit();
    },

    clear: () => {
      // Guarded so a no-op clear does not re-render every subscriber. `dropToken` in
      // `authClient.ts` runs before every POST /api/auth/*, most of them anonymous.
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
