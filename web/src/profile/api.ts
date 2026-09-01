import { useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query';

import type { Profile, ProfilePatch, Vocabulary } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { BUILD_ID } from '../buildId';

/**
 * The two reads and the one write behind onboarding and the profile editor.
 *
 * ## ⚠️ THE RULE THIS FILE IS BUILT ON: the query cache holds SERVER RESPONSES ONLY
 *
 * Nothing here writes a guess into the cache. The optimistic view is derived at render time
 * from the variables of still-pending mutations (`useProfileView`), so an in-flight write is an
 * *overlay* on server truth rather than an edit to it. **No `onMutate`, no snapshot, and nothing
 * at all on the error path** — a failed write issues no request, which is also one less Neon
 * wake. Three review rounds found three bugs here and all three came from two writers for one
 * cache entry: a snapshot restored a fabrication once a second `mutate()` was in flight
 * (measured **71% against a truth of 57%** for the full ten-minute `staleTime`); replacing it
 * with `invalidateQueries` on error resolved second and overwrote a newer `onSuccess` (**71 at
 * +5 ms, then 57**); and when that refetch itself failed — the ordinary case — the route swapped
 * the wizard for a load-error paragraph and the user's unsaved draft went with it.
 *
 * ## Why the timing works — read from the INSTALLED source, not reasoned about
 *
 * The installed `build/modern/mutation.js`, by CONSTRUCT (`api/libraryCitations.test.ts`):
 *
 * - `execute()` dispatches `{ type: "pending", variables, isPaused }` **synchronously**, before
 *   `onMutate` and before the retryer, whose gate it passes as
 *   `canRun: () => this.#mutationCache.canRun(this)`. So `scope` serialises the network call, NOT
 *   `onMutate` — which is why a snapshot could ever see another write's guess. The overlay is
 *   established by the click and renders next tick (`useMutationState` -> `notifyManager.schedule`
 *   -> `systemSetTimeoutZero`; measured, and the same scheduler a `setQueryData` went through).
 * - Success order: `await retryer.start()` -> `await this.options.onSuccess?.(data,` ->
 *   `onSettled` -> `dispatch({ type: "success" })`: the cache is updated **before** the mutation
 *   leaves `pending`, so the overlay is replaced by real data and the bar cannot flicker back.
 * - Failure order: `onError` -> `onSettled` -> `dispatch({ type: 'error' })`. The overlay drops
 *   when the mutation stops being pending, and there is nothing to roll back.
 * - `query.js`'s `case "error"` reducer sets `status: "error"` **unconditionally**, data or no
 *   data — which is why a route must gate on `data === undefined` and never on `isError`.
 * - `scope: { id }` still earns its keep: `canRun` gates the retryer and `runNext` runs in
 *   `execute()`'s `finally`, so `onSuccess` fires in commit order.
 *
 * **Staleness.** The vocabulary is reference data only a deploy can change, so refetching it is
 * pure Neon awake time: `Infinity`. The profile is replaced by every PATCH response, so ten
 * minutes bounds it without making the dashboard refetch on every visit. ⚠️ A second TAB is
 * stale for up to those ten minutes and focusing it will not refresh it
 * (`refetchOnWindowFocus: false`, because a gym phone flaps between focused and blurred).
 */

export const PROFILE_KEY = ['profile'] as const;
export const VOCABULARY_KEY = ['vocabulary', BUILD_ID] as const;

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
 * path that previously did none. `queryObserver.js` gates every fetch decision on
 * `resolveQueryValue(options.enabled, query) !== false`, so this closes it at the source.
 *
 * The `_authed` guard means an authenticated screen never renders without a session anyway;
 * this covers the tick between the token going and the navigation landing.
 */
export function useVocabulary() {
  const { request, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: VOCABULARY_KEY,
    queryFn: () => request<Vocabulary>(`/api/vocabulary?v=${encodeURIComponent(BUILD_ID)}`),
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
 * describes. The `injuries_reviewed_at` guess is what makes the bar move for the injury step,
 * whose honest answer can be an empty list — a merge that only copied the rows would leave it
 * looking unanswered until the response landed.
 *
 * ⚠️ **It does NOT guess `_decide_grades`'s clearing rule.** The server nulls
 * `current_grade_id` when a new target moves to the other ladder, and this overlay cannot see
 * that: it would need the vocabulary to know both grades' disciplines. The consequence is
 * bounded and acceptable — for the few hundred milliseconds a target-grade PATCH is in
 * flight, a bar that had credited the aspect step keeps crediting it, and `onSuccess` then
 * installs the server's own answer. It cannot go the other way (credit something unanswered),
 * because clearing only ever removes an answer.
 * `primary_discipline` is deliberately NOT guessed: the server derives it from the chosen
 * grade, and inventing it here would put a value on screen that the response then silently
 * changes. `null` in a patch means "not in this request", which is the server's rule too,
 * so `??` is the right operator throughout.
 */
function withPatch(profile: Profile, patch: ProfilePatch): Profile {
  // Both hoisted to `?? null` for one reason and one idiom: "was this field in the request?"
  // is asked twice for each of them below.
  const ratings = patch.aspect_ratings ?? null;
  const injuries = patch.injuries ?? null;
  const now = new Date().toISOString();

  return {
    ...profile,
    target_grade_id: patch.target_grade_id ?? profile.target_grade_id,
    current_grade_id: patch.current_grade_id ?? profile.current_grade_id,
    sessions_per_week: patch.sessions_per_week ?? profile.sessions_per_week,
    available_weekdays: patch.available_weekdays ?? profile.available_weekdays,
    strength_aspect_id: patch.strength_aspect_id ?? profile.strength_aspect_id,
    weakness_aspect_id: patch.weakness_aspect_id ?? profile.weakness_aspect_id,
    display_name: patch.display_name ?? profile.display_name,
    show_body_metrics: patch.show_body_metrics ?? profile.show_body_metrics,
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
   * `queryObserver.js` derives `isLoadingError` as `isError && !hasData`, which is
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

/**
 * `POST /api/profile/reset` — un-answer the four onboarding steps.
 *
 * ⚠️ **Same cache rule as `useProfilePatch`, and the same scope.** `onSuccess` writing the
 * server's own answer is the only cache write; nothing happens on the error path. The shared
 * `scope: { id: 'profile' }` is what stops a reset and an in-flight step PATCH from landing
 * out of order — Query serialises same-scope mutations, so the reset cannot be overtaken by a
 * write that was already on the wire.
 *
 * It is deliberately NOT part of `useProfilePatch`: the two send different methods to
 * different paths, and a mutation whose variables mean "a patch, or nothing at all" is the
 * kind of union that grows a bug. The `PROFILE_PATCH_KEY` is shared, though, so the
 * optimistic overlay in `useProfileView` sees a pending reset the same way it sees a pending
 * patch — it applies `{}`, which changes nothing, so the bar simply waits for the response
 * rather than guessing an emptier profile than the server may end up with.
 */
export function useProfileReset(handlers: ProfilePatchHandlers = {}) {
  const { request } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: PROFILE_PATCH_KEY,
    scope: { id: 'profile' },
    mutationFn: () => request<Profile>('/api/profile/reset', { method: 'POST' }),
    onSuccess: (profile) => {
      queryClient.setQueryData(PROFILE_KEY, profile);
      handlers.onSuccess?.(profile, {});
    },
    onError: (error) => {
      handlers.onError?.(error, {});
    },
  });
}
