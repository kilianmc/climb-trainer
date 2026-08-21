import { useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query';

import type { Profile, ProfilePatch, Vocabulary } from '../api/types';
import { useAuth } from '../auth/AuthProvider';

/**
 * The two reads and the one write behind onboarding and the profile editor.
 *
 * ## ⚠️ THE RULE THIS FILE IS BUILT ON: the query cache holds SERVER RESPONSES ONLY
 *
 * Nothing here writes a guess into the cache. The optimistic view is derived at render time
 * from the variables of the mutations that are still pending (`useProfileView`), so an
 * in-flight write is an *overlay* on server truth rather than an edit to it.
 *
 * Three rounds of review found three bugs in this layer and every one of them came from
 * having two writers for one cache entry. In order:
 *
 * 1. A snapshot taken in `onMutate` and restored in `onError` is only correct while exactly
 *    one write is in flight. `mutation.js:94` dispatches `pending` and runs `onMutate`
 *    **before** `retryer.start()`, while the `scope` gate is `canRun()` **inside** the
 *    retryer (`mutation.js:86`) — so `scope` serialises the network call and not
 *    `onMutate`. A second `mutate()` snapshotted a cache that already held the first one's
 *    guess, and restoring it restored a fabrication: measured at **71% against a truth of
 *    57%**, for the full ten-minute `staleTime`, while the alert said the answer had not
 *    been counted.
 * 2. Replacing the snapshot with `invalidateQueries` moved the bug rather than removing it.
 *    The refetch was issued from the failing mutation's `onError`, before the next write
 *    committed, so it resolved second and overwrote a newer `onSuccess` — measured **71 at
 *    +5 ms, then 57** once the read landed, i.e. a write that really did persist reading as
 *    unanswered.
 * 3. And when that refetch itself failed — the ordinary case, since whatever kills the PATCH
 *    usually kills the GET — `query.js`'s `case "error"` reducer sets `status: "error"`
 *    **unconditionally**, data or no data ("flag existing data as invalidated if we get a
 *    background error"). `isError` flipped, the route swapped the wizard for a load-error
 *    paragraph, and the user's unsaved draft went with it.
 *
 * Deriving the overlay instead removes all three by construction: there is no snapshot, the
 * error path issues **no request at all**, and the cache can only ever hold something the
 * server said. It is also cheaper — a failed write no longer wakes Neon for a GET nobody
 * asked for.
 *
 * ## Why the timing works, from the installed source
 *
 * Read in `@tanstack/query-core@5.101.4`, `build/modern/mutation.js`:
 *
 * - `execute()` dispatches `{ type: 'pending', variables }` at line 94, **synchronously**,
 *   before `onMutate` and before the retryer. So the overlay is established by the click and
 *   renders **on the next tick** — `useMutationState` delivers through
 *   `notifyManager.schedule` -> `systemSetTimeoutZero`, so the bar still reads the old number
 *   in the click handler itself and the new one after the macrotask flush. Measured; and it
 *   is the same scheduler an `onMutate` + `setQueryData` went through, so nothing regressed.
 *   The Tier-1 "the UI never waits on the database" rule is satisfied with no cache write.
 * - On success the order is `await retryer.start()` -> `await options.onSuccess` ->
 *   `await options.onSettled` -> `dispatch({ type: 'success' })`. The cache is therefore
 *   updated **before** the mutation leaves `pending`, so the overlay is replaced by real
 *   data with no frame in between and the bar cannot flicker backwards.
 * - On failure the order is `await options.onError` -> `await options.onSettled` ->
 *   `dispatch({ type: 'error' })`. The overlay drops when the mutation stops being pending,
 *   and there is nothing to roll back.
 * - `scope: { id }` still earns its keep: `canRun` gates the retryer and `runNext` runs in
 *   `execute()`'s `finally`, so requests are serialised and `onSuccess` therefore fires in
 *   commit order. Without it a slow earlier response could install itself over a later one.
 *
 * ## Staleness
 *
 * The vocabulary is reference data only a deploy can change, so refetching it is pure Neon
 * awake time: `Infinity`. The profile is written by this client and replaced by every PATCH
 * response, so ten minutes bounds it without making the dashboard — where every
 * authenticated session lands, and which used to issue no SQL at all — refetch on every
 * visit. ⚠️ A second TAB is stale for up to those ten minutes and focusing it will not
 * refresh it (`router.tsx` sets `refetchOnWindowFocus: false`, because a gym phone flaps
 * between focused and blurred constantly). Benign: the tab that did the writing is correct,
 * and the number is a progress bar.
 */

export const PROFILE_KEY = ['profile'] as const;
export const VOCABULARY_KEY = ['vocabulary'] as const;

/**
 * Declared so `useProfileView` can find *our* pending mutations and nobody else's.
 * `matchMutation` (query-core `utils.js`) returns false for any mutation without a
 * `mutationKey`, so a future unrelated mutation cannot leak into the overlay.
 */
export const PROFILE_PATCH_KEY = ['profile', 'patch'] as const;

const PROFILE_STALE_TIME_MS = 10 * 60_000;

/**
 * ⚠️ **`enabled` is not decoration: both of these are authenticated reads.**
 *
 * Logging out clears the query cache (`auth/authClient.ts`), and a mounted observer whose
 * query has just been removed fetches again — measured on the real nav path, **one extra
 * `GET /api/profile`**, issued after the token was dropped. In production that is a 401,
 * which `auth/refresh.ts` answers with a refresh POST, which is a **Postgres write** on a
 * path that previously did none. `queryObserver.js:445/451/461` gate every fetch decision on
 * `resolveQueryBoolean(options.enabled, query) !== false`, so this closes it at the source.
 *
 * The `_authed` guard means an authenticated screen never renders without a session anyway;
 * this covers the tick between the token going and the navigation landing.
 */
export function useVocabulary() {
  const { request, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: VOCABULARY_KEY,
    queryFn: () => request<Vocabulary>('/api/vocabulary'),
    staleTime: Infinity,
    enabled: isAuthenticated,
  });
}

function useProfileQuery() {
  const { request, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: PROFILE_KEY,
    queryFn: () => request<Profile>('/api/profile'),
    staleTime: PROFILE_STALE_TIME_MS,
    enabled: isAuthenticated,
  });
}

/**
 * The optimistic overlay: what one pending patch would make of a profile.
 *
 * Applied at render time and never written anywhere, so it cannot outlive the request it
 * describes. The two `*_reviewed_at` guesses are what make the bar move for the equipment
 * and injury steps, whose honest answer can be an empty list — a merge that only copied the
 * rows would leave those two looking unanswered until the response landed.
 * `primary_discipline` is deliberately NOT guessed: the server derives it from the chosen
 * grade, and inventing it here would put a value on screen that the response then silently
 * changes. `null` in a patch means "not in this request", which is the server's rule too,
 * so `??` is the right operator throughout.
 */
function withPatch(profile: Profile, patch: ProfilePatch): Profile {
  // All three hoisted to `?? null` for one reason and one idiom: "was this field in the
  // request?" is asked twice for each of them below.
  const equipment = patch.equipment_ids ?? null;
  const ratings = patch.aspect_ratings ?? null;
  const injuries = patch.injuries ?? null;
  const now = new Date().toISOString();

  return {
    ...profile,
    target_grade_id: patch.target_grade_id ?? profile.target_grade_id,
    sessions_per_week: patch.sessions_per_week ?? profile.sessions_per_week,
    available_weekdays: patch.available_weekdays ?? profile.available_weekdays,
    show_body_metrics: patch.show_body_metrics ?? profile.show_body_metrics,
    equipment_ids: equipment ?? profile.equipment_ids,
    equipment_reviewed_at: equipment === null ? profile.equipment_reviewed_at : now,
    injuries_reviewed_at: injuries === null ? profile.injuries_reviewed_at : now,
    aspect_ratings:
      ratings === null
        ? profile.aspect_ratings
        : ratings.map((rating) => ({ ...rating, rated_at: now })),
    injuries:
      injuries === null
        ? profile.injuries
        : injuries.map((injury) => ({
            injury_area_id: injury.injury_area_id,
            note: injury.note ?? null,
            started_on: now.slice(0, 10),
          })),
  };
}

export interface ProfileView {
  /** Server state plus every in-flight patch. `undefined` until the first load lands. */
  profile: Profile | undefined;
  /**
   * There is **nothing to show** and the load failed — the only condition under which a
   * screen may replace itself with an error.
   *
   * ⚠️ Not `isError`: `query.js`'s error reducer sets `status: "error"` even when data is
   * present, so `isError` cannot tell "nothing to show" from "stale but perfectly usable".
   * `queryObserver.js:331` derives `isLoadingError` as `isError && !hasData`, which is
   * exactly this question. Gating a screen on `isError` destroyed the user's draft.
   */
  isLoadingError: boolean;
  /** Nothing else will retry: `refetchOnWindowFocus` is off. */
  retry: () => void;
}

export function useProfileView(): ProfileView {
  const query = useProfileQuery();
  // `useMutationState` (react-query `useMutationState.js`) runs `mutationCache.findAll` on
  // every cache notification and passes the result through `replaceEqualDeep`, so this array
  // is referentially stable while nothing relevant changes. `findAll` preserves insertion
  // order, so the reduce below applies the patches oldest-first.
  const pending = useMutationState({
    filters: { mutationKey: PROFILE_PATCH_KEY, status: 'pending' },
    // The mutation cache is untyped by design; the `mutationKey` filter above is what makes
    // this cast safe — every match was built by `useProfilePatch`.
    select: (mutation) => mutation.state.variables as ProfilePatch | undefined,
  });

  const server = query.data;
  return {
    profile:
      server === undefined
        ? undefined
        : // Explicit generic: without it the accumulator is inferred from the ARRAY's
          // element type (`ProfilePatch | undefined`) rather than from the seed.
          pending.reduce<Profile>(
            (view, patch) => (patch === undefined ? view : withPatch(view, patch)),
            server,
          ),
    isLoadingError: query.isLoadingError,
    retry: () => {
      void query.refetch();
    },
  };
}

export interface ProfileScreen extends ProfileView {
  vocabulary: Vocabulary | undefined;
  /** Which of the two reads is the one with nothing to show. Both can be true. */
  profileFailed: boolean;
  vocabularyFailed: boolean;
}

/**
 * What the wizard and the editor both need. One hook so the "may I render?" decision cannot
 * be got right in one route and wrong in the other — which is how it went wrong once.
 */
export function useProfileScreen(): ProfileScreen {
  const view = useProfileView();
  const vocabulary = useVocabulary();
  return {
    profile: view.profile,
    vocabulary: vocabulary.data,
    profileFailed: view.isLoadingError,
    vocabularyFailed: vocabulary.isLoadingError,
    isLoadingError: view.isLoadingError || vocabulary.isLoadingError,
    // Only what failed. The vocabulary is `staleTime: Infinity` reference data, so refetching
    // it because the PROFILE failed is a wasted request against the compute budget.
    retry: () => {
      if (view.isLoadingError) view.retry();
      if (vocabulary.isLoadingError) void vocabulary.refetch();
    },
  };
}

/**
 * Caller hooks, and they must be passed HERE rather than to `mutate(vars, { … })`.
 *
 * Per-call options live on the observer, and `mutationObserver.js` reassigns
 * `#mutateOptions` and removes the observer from the in-flight mutation when a newer
 * `mutate()` arrives — so a superseded mutation's failure would report to nobody. These are
 * attached to the mutation itself (`mutation.js` calls `this.options.onError`), which fires
 * with no observer involved. Both receive the patch, so a caller can say WHICH step it was
 * without capturing a `step` closure — the closure named whatever was on screen when the
 * message rendered.
 */
export interface ProfilePatchHandlers {
  onError?: (error: unknown, patch: ProfilePatch) => void;
  onSuccess?: (profile: Profile, patch: ProfilePatch) => void;
}

export function useProfilePatch(handlers: ProfilePatchHandlers = {}) {
  const { request } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: PROFILE_PATCH_KEY,
    // Serialises the REQUESTS, so `onSuccess` fires in commit order and a slow earlier
    // response cannot install itself over a later one.
    scope: { id: 'profile' },
    mutationFn: (patch: ProfilePatch) =>
      request<Profile>('/api/profile', { method: 'PATCH', json: patch }),
    // The ONLY write to the cache in this file, and it is the server's own answer to the
    // request that just committed. No `onMutate`, and nothing on the error path: see the
    // rule at the top.
    onSuccess: (profile, patch) => {
      queryClient.setQueryData(PROFILE_KEY, profile);
      handlers.onSuccess?.(profile, patch);
    },
    onError: (error, patch) => {
      handlers.onError?.(error, patch);
    },
  });
}
