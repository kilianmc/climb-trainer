import { useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import type { ActivePlanResponse, PlanAbandoned, PlanTree, Profile } from '../api/types';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthProvider';

import { canPreview, nextMonday, previewKeyParts } from './blueprint';

/**
 * The one read that costs a generation, the one read that says what the climber HAS, and the two
 * writes between them.
 *
 * ## ⚠️ THE RULE THIS FILE IS BUILT ON: the query cache holds SERVER RESPONSES ONLY
 *
 * `web/src/profile/api.ts` carries the full reasoning and the measurements — three consecutive
 * review rounds, three bugs, every one of them from having two writers for one cache entry. The
 * same rule binds here and it is what shapes both mutations below:
 *
 * - **No `onMutate`, no snapshot, and nothing at all on the error path.** `onSuccess` writes the
 *   server's own answer to the write that just committed, and that is the only cache write in
 *   this file.
 * - **The optimistic view is DERIVED at render time from the pending mutation's own variables**
 *   (`useActivePlanView` below), so a failed write needs no rollback and issues no request.
 * - So there is no `invalidateQueries` anywhere in here. The 409 recovery is a read taken
 *   *inside* the mutation function (see `useCreatePlan`), which keeps it under the same `scope`
 *   serialisation as everything else rather than racing a later write from an `onError`.
 *
 * ## Verified against `web/node_modules/@tanstack/query-core@5.101.4`, `build/modern/`
 *
 * Every claim this file makes about Query is something read there, per CLAUDE.md's standing rule:
 *
 * - `mutation.js:82` — `retry: this.options.retry ?? 0`. **A mutation does not retry by
 *   default**, so the 409 arrives at the `catch` in `mutationFn` once and is not re-sent.
 * - `mutation.js:94` — `execute()` dispatches `{ type: 'pending', variables }` **synchronously**,
 *   before the retryer and before `onMutate`. That is what makes the derived overlay land on the
 *   click rather than on the response.
 * - `mutation.js:135-144` — on success the order is `await retryer.start()` -> `await
 *   options.onSuccess` -> `await options.onSettled` -> `dispatch({ type: 'success' })`. The cache
 *   is written **before** the mutation leaves `pending`, so the overlay is replaced by real data
 *   with no frame in between.
 * - `mutationCache.js:60-67` — `canRun` returns true only when this mutation is the *first
 *   pending* one in its scope; `mutation.js:194` calls `runNext` in `execute()`'s `finally`, and
 *   `mutationCache.js:75` continues the next paused mutation in the scope. So `scope: { id:
 *   'plan' }` serialises the REQUESTS: a create and an abandon can never be on the wire at once,
 *   and a double-tap sends its second POST only after the first has fully settled.
 * - `queryClient.js:92-103` — `setQueryData` runs `functionalUpdate` and then
 *   `if (data === void 0) return void 0`, writing nothing. That is what lets `useAbandonPlan`
 *   say "leave the cache alone" by returning the value it was given.
 * - `queryObserver.js:331` — `isLoadingError: isError && !hasData`, which is the "there is
 *   genuinely nothing to show" question every screen here must gate on instead of `isError`.
 * - `queryClient.js:141-147` — `cancelQueries` defaults to `{ revert: true }` and calls
 *   `query.cancel` on every match; `query.js:268-270` restores `#revertState` for a
 *   `CancelledError` with `revert`. So cancelling an in-flight read **removes a writer** rather
 *   than adding one — see `cancelStaleRead` below.
 */

/** `POST /api/plans/preview`. The parts are appended per call — see `usePlanPreview`. */
export const PLAN_PREVIEW_KEY = ['plan', 'preview'] as const;
/** `GET /api/plans/active`. Holds the whole `{plan}` envelope, exactly as the server sent it. */
export const ACTIVE_PLAN_KEY = ['plan', 'active'] as const;

/**
 * Declared so `useActivePlanView` can find *our* pending abandon and nobody else's.
 * `matchMutation` (query-core `utils.js`) returns false for any mutation with no `mutationKey`,
 * so an unrelated future mutation cannot leak into the overlay.
 */
export const PLAN_CREATE_KEY = ['plan', 'create'] as const;
export const PLAN_ABANDON_KEY = ['plan', 'abandon'] as const;

/**
 * ONE scope for both writes, and it is the invariant that makes the client cheap.
 *
 * Creating a plan stands the previous one down in the same server transaction, and abandoning
 * one is a write against the row a create is about to replace — so the two must never overlap.
 * `canRun` gates the retryer (`mutationCache.js:60`), so a second click waits for the first to
 * settle rather than racing it. A double-tap therefore sends its second `POST /api/plans` only
 * after the first returned, which the server answers with a legitimate **201** that stands the
 * first plan down. The 409 is what arrives from a *second tab or device*, where nothing on this
 * client can serialise anything.
 */
const PLAN_WRITE_SCOPE = { id: 'plan' } as const;

/**
 * Ten minutes, matching the profile's, and for the same reason: this client is the only thing
 * that writes a plan, and every `POST` replaces the entry outright. ⚠️ A second TAB is stale for
 * up to ten minutes and focusing it will not refresh it (`router.tsx` sets
 * `refetchOnWindowFocus: false`, because a gym phone flaps between focused and blurred). Benign
 * — the tab that did the writing is correct, and the worst case is a Start that comes back 409
 * and installs the truth.
 */
const ACTIVE_PLAN_STALE_TIME_MS = 10 * 60_000;

/**
 * Drop any `GET /api/plans/active` still on the wire, before a mutation installs its answer.
 *
 * ## The ordering this closes, and it is PLAUSIBLE rather than reproduced
 *
 * `ACTIVE_PLAN_KEY` has three writers: the `queryFn`, and the two `onSuccess` handlers below.
 * A mount-time read issued *before* a Start and resolving *after* it would write the OLD plan
 * over the new one, and the screen would then hold it for `staleTime` (ten minutes, with
 * `refetchOnWindowFocus` off). Measured server timings make it unlikely — `GET /api/plans/active`
 * is 0.050 s against `POST /api/plans`' 0.243 s, so the read has to be nearly a fifth of a
 * second older to lose — but "unlikely" is not "impossible", and a cold Neon wake lands on the
 * read as easily as on the write.
 *
 * ## Why this does not breach one-writer-per-cache-entry
 *
 * It adds no writer. `cancelQueries` defaults to `revert: true` (`queryClient.js:142`), and
 * `query.js:268-270` restores the pre-fetch state for a reverted `CancelledError` — so the
 * cancelled read writes **nothing at all**, and the mutation's `setQueryData` immediately after
 * is still the only thing that writes. It is the opposite of the PR #9 bug: that was an extra
 * READ fired from an error handler, this removes one.
 *
 * `await`ed, because `mutation.js:135-144` awaits `onSuccess` before dispatching `success` —
 * so the cancel is settled before the write, and the button stays busy until the cache is true.
 */
async function cancelStaleRead(queryClient: ReturnType<typeof useQueryClient>): Promise<void> {
  await queryClient.cancelQueries({ queryKey: ACTIVE_PLAN_KEY });
}

/**
 * `POST /api/plans/preview` — the plan the generator would build, never written.
 *
 * ## `useQuery`, not `useMutation`
 *
 * This is a **read expressed as a POST**, and Query's split between the two hooks is about cache
 * semantics, not HTTP verbs: the response is a pure function of the inputs, it is safe to serve
 * from cache, and it must not be re-sent when the screen remounts. `POST` is the verb only
 * because a per-user body on a cacheable verb is the `/api/library` CDN trap (`server/plans/
 * routes.py` carries that reasoning, and answers `private, no-store`). A mutation would give the
 * screen no cache at all and would re-generate a 32-week plan on every visit.
 *
 * ## The key IS the inputs, which is what removes the invalidation wiring
 *
 * `previewKeyParts` is `start_date` plus every profile field the planner reads plus an injury
 * fingerprint. So a profile change produces a **new key and a new fetch** with nothing to
 * invalidate, going back to the screen is a **cache hit**, and `staleTime: Infinity` is then
 * simply true rather than a bet — the same inputs against the same deploy cannot yield a
 * different plan. Nothing here has to know that a profile PATCH happened.
 *
 * ⚠️ **The hook keeps the name `usePlanPreview`.** Renaming it to something plan-shaped was
 * considered when `useActivePlan` landed and rejected: the distinction between the plan the
 * climber *has* and the plan we would *offer* is the only thing separating these two hooks —
 * their response type is now identical (`PlanTree`) — so the two names have to keep carrying it.
 *
 * ⚠️ **Never persisted.** The whole app persists no query cache
 * (`CLAUDE.md`, the federated-`localStorage` rule), and this is the one endpoint where doing it
 * would be an actual data leak rather than a policy breach: the body names the user's open
 * injuries.
 *
 * ## `enabled`, all three parts
 *
 * - **`isAuthenticated`** for the measured reason in `profile/api.ts:88-100`: logging out clears
 *   the cache, a still-mounted observer refetches, that is a 401, and the refresh path answers a
 *   401 with a **Postgres write**.
 * - **`canPreview(profile)`** because the client holds the profile and can see a refusal before
 *   asking for one — see `blueprint.ts`. The 422 stays as defence in depth; it is just not the
 *   normal way this screen learns that a step is unanswered.
 * - **`wanted`**, which is new and is a compute decision. Generating a 32-week plan is the most
 *   expensive read in the app, and a climber who already has a plan running did not ask for a
 *   different one by arriving on the screen. So `/plan` leaves this off until either
 *   `GET /api/plans/active` says there is nothing running or the user asks for an alternative.
 *   That makes the two reads **sequential** on the empty-state path, which is the trade taken
 *   deliberately: one extra round trip for a new account, against a wasted generation on every
 *   visit for every account in the steady state.
 */
export function usePlanPreview(profile: Profile | undefined, wanted = true) {
  const { request, isAuthenticated } = useAuth();

  // Fixed for the life of the mount. It is a query-key input, so re-deriving it every render
  // would be a new key the moment the clock crosses midnight mid-render — and a new key is a
  // new 32-week generation.
  const startDate = useMemo(() => nextMonday(new Date()), []);

  // Derived only when the answer is actually askable. A key is required even while the query
  // is disabled, so the unplannable case gets `null` — which cannot collide with a real key,
  // and means the parts are never derived from a profile that has no plan in it.
  const parts =
    profile !== undefined && canPreview(profile) ? previewKeyParts(profile, startDate) : null;

  return useQuery({
    queryKey: [...PLAN_PREVIEW_KEY, parts],
    // A body is mandatory — a bodyless POST is a 422 — and `json` is what sets the content-type
    // FastAPI's `strict_content_type` requires.
    queryFn: () =>
      request<PlanTree>('/api/plans/preview', {
        method: 'POST',
        json: { start_date: startDate },
      }),
    staleTime: Infinity,
    enabled: wanted && isAuthenticated && parts !== null,
  });
}

/**
 * `GET /api/plans/active` — the plan this climber is on, or `null`.
 *
 * ## ⚠️ `{"plan": null}` IS THE EMPTY STATE, and it arrives as a 200
 *
 * "No plan yet" is the state every new account is in, so it is an ordinary render with a Start
 * button and **not** an error. `server/plans/routes.py::ActivePlanResponse` explains why the
 * server refuses to spell it as a 404: `apiFetch` throws on 4xx, the retry predicate treats 4xx
 * as unwinnable, and a route gate would see `data === undefined` and swap itself for a
 * fallback — three layers each needing a special case for the expected answer.
 *
 * `select` is what makes that legible downstream: the **cache holds the envelope the server
 * sent** (so `setQueryData` in both mutations writes a server-shaped value), while observers see
 * `PlanTree | null`, where `undefined` means only "the first read has not landed".
 *
 * ⚠️ `?? null` rather than `response.plan` bare. The field is required on the wire, so an
 * absent one should be unreachable — but the two readings of absent are "no plan" and "still
 * loading", and only the first is safe: the second parks the screen on a spinner forever. Same
 * argument `blueprint.ts::unanswered` makes, and the same test harness (`routeGuard.test.tsx`
 * answers every request with a token payload) is what would find it.
 *
 * Enabled on `isAuthenticated` for the measured reason in `profile/api.ts`. It is **not** gated
 * on the profile being plannable: a climber can have a running plan and then clear a grade, and
 * the plan does not stop existing because the answers behind it moved.
 */
export function useActivePlan() {
  const { request, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ACTIVE_PLAN_KEY,
    queryFn: () => request<ActivePlanResponse>('/api/plans/active'),
    select: (response) => response.plan ?? null,
    staleTime: ACTIVE_PLAN_STALE_TIME_MS,
    enabled: isAuthenticated,
  });
}

export interface ActivePlanView {
  /**
   * `undefined` — the first read has not landed, so nothing can be decided yet.
   * `null` — there is no plan, which is a normal screen.
   * A `PlanTree` — the plan the climber is on, with every `id` filled.
   */
  plan: PlanTree | null | undefined;
  /**
   * There is **nothing to show** and the read failed — the only condition under which a screen
   * may replace itself with an error.
   *
   * ⚠️ Not `isError`: `query.js`'s error reducer sets `status: "error"` even when data is
   * present, so a failing background refetch would otherwise blow away a plan the climber is
   * reading. `queryObserver.js:331` derives `isLoadingError` as `isError && !hasData`, which is
   * exactly this question.
   */
  isLoadingError: boolean;
  /** Nothing else will retry: `refetchOnWindowFocus` is off app-wide. */
  retry: () => void;
}

/**
 * Server truth, plus the one optimistic thing this screen can honestly guess.
 *
 * **An abandon in flight is rendered as "no plan", derived from the pending mutation's own
 * variables and written nowhere.** That is the whole optimistic surface: the click is a Tier-1
 * write, so the UI must not wait on Postgres, and `mutation.js:94` dispatches `pending`
 * synchronously — so the overlay is established by the click. If the request fails the overlay
 * simply drops when the mutation leaves `pending` and the plan is back, with no rollback and no
 * request issued.
 *
 * ⚠️ **A pending CREATE gets no overlay, deliberately.** The optimistic value would be a whole
 * plan tree — 2,421 prescribed sets the server has not generated yet — and inventing one is
 * precisely what "the cache holds server responses only" forbids. So a create in flight is
 * rendered as a busy button and nothing more, which is honest: until the response lands, nobody
 * knows what the plan says.
 *
 * The id is compared rather than assumed, because an abandon can name a plan that is not the
 * active one (a second tab stood a different plan down); guessing `null` for that would hide a
 * plan the climber still has.
 */
export function useActivePlanView(): ActivePlanView {
  const query = useActivePlan();
  // `useMutationState` (react-query `useMutationState.js`) runs `mutationCache.findAll` on every
  // cache notification and passes the result through `replaceEqualDeep`, so this array is
  // referentially stable while nothing relevant changes.
  const abandoning = useMutationState({
    filters: { mutationKey: PLAN_ABANDON_KEY, status: 'pending' },
    // The mutation cache is untyped by design; the `mutationKey` filter is what makes this cast
    // safe — every match was built by `useAbandonPlan`, whose variables are a plan id.
    select: (mutation) => mutation.state.variables as number | undefined,
  });

  const server = query.data;
  return {
    plan:
      server === undefined || server === null
        ? server
        : abandoning.some((planId) => planId === server.id)
          ? null
          : server,
    isLoadingError: query.isLoadingError,
    retry: () => {
      void query.refetch();
    },
  };
}

/**
 * `POST /api/plans` — generate this climber's plan, persist it activated, and return it. **201.**
 *
 * The variable is a `start_date`, and callers pass the **`start_date` of the plan on screen**
 * rather than re-deriving today's Monday. The server normalises whatever it is given the same
 * way on both routes, so echoing the preview's own value is what guarantees the plan that gets
 * saved starts on the day the preview showed — a mount that crossed midnight, or a tab left open
 * over a weekend, would otherwise persist a plan a week away from the one the climber read.
 *
 * ## ⚠️ A 409 IS NOT A FAILURE, and the recovery lives inside `mutationFn`
 *
 * The partial unique index `uq_plan_one_active_per_user` answers a second active plan with a
 * 409, and the climber who produced it **does have a plan** — so the honest response is to go
 * and read it, not to show an error. It is handled here rather than in `onError` for the reason
 * at the top of the file: an `invalidateQueries` fired from an error handler is the PR #9 bug
 * (measured: a refetch issued before the next write committed resolved second and overwrote a
 * newer `onSuccess`). Inside `mutationFn` the recovery read is part of the mutation, so it stays
 * under `PLAN_WRITE_SCOPE`'s serialisation, it resolves before `onSuccess` runs, and there is
 * exactly one writer for the cache entry either way.
 *
 * `null` is a legitimate result: a 409 followed by a read that finds nothing means another
 * session abandoned the plan in between, and `{plan: null}` is then the truth. The screen
 * renders its empty state and offers Start again.
 *
 * Only `ApiError`s with status 409 are caught. Anything else — including a `NotJsonError`, which
 * means a rewrite ate the request — rethrows and reads as the fault it is.
 *
 * ## `handlers.onSuccess` is attached HERE and not to `mutate(vars, { … })`
 *
 * Per-call options live on the observer, and `mutationObserver.js` reassigns `#mutateOptions` and
 * drops the observer from the in-flight mutation when a newer `mutate()` arrives — so a
 * superseded mutation's callback would report to nobody. `mutation.js` calls
 * `this.options.onSuccess`, which fires with no observer involved. Same reasoning, and the same
 * shape, as `profile/api.ts::ProfilePatchHandlers`.
 */
export interface CreatePlanHandlers {
  /** The plan the server committed, or `null` if the 409 recovery read found none. */
  onSuccess?: (plan: PlanTree | null) => void;
}

export function useCreatePlan(handlers: CreatePlanHandlers = {}) {
  const { request } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: PLAN_CREATE_KEY,
    scope: PLAN_WRITE_SCOPE,
    mutationFn: async (startDate: string): Promise<PlanTree | null> => {
      try {
        return await request<PlanTree>('/api/plans', {
          method: 'POST',
          json: { start_date: startDate },
        });
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        const active = await request<ActivePlanResponse>('/api/plans/active');
        return active.plan ?? null;
      }
    },
    // The server's own answer to the write that just committed — the 201 body, or the plan the
    // 409 recovery read returned. Never a guess, and the only cache write on this path. The
    // route's docstring is explicit that returning the whole tree is what makes a follow-up
    // fetch unnecessary, so this is that saving being taken.
    onSuccess: async (plan) => {
      await cancelStaleRead(queryClient);
      queryClient.setQueryData<ActivePlanResponse>(ACTIVE_PLAN_KEY, { plan });
      handlers.onSuccess?.(plan);
    },
  });
}

/**
 * `POST /api/plans/{plan_id}/abandon` — stand a plan down. Marks, never deletes.
 *
 * Idempotent server-side (an already-abandoned plan keeps its original timestamp), 404 for
 * anyone else's plan, and it shares `PLAN_WRITE_SCOPE` with `useCreatePlan` so an abandon and a
 * create cannot be on the wire together.
 *
 * ## What goes in the cache, and why it is not a guess
 *
 * The response is `{id, abandoned_at}` — not a plan — so there is no server-shaped envelope to
 * install. What the server *did* say is that plan `id` is abandoned, and an abandoned plan is by
 * definition not the active one, so `{plan: null}` is entailed rather than assumed. It is
 * written **only when the cached plan is that plan**: an abandon naming some other plan (a
 * second tab, a stale screen) must not clear an entry that was never about it.
 *
 * Returning `current` unchanged is how "leave the cache alone" is spelled — including when
 * `current` is `undefined`, which `queryClient.js:99` turns into no write at all rather than
 * into an entry holding `undefined`.
 */
export function useAbandonPlan() {
  const { request } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: PLAN_ABANDON_KEY,
    scope: PLAN_WRITE_SCOPE,
    mutationFn: (planId: number) =>
      request<PlanAbandoned>(`/api/plans/${String(planId)}/abandon`, { method: 'POST' }),
    onSuccess: async (abandoned) => {
      // Same race, same fix: a read in flight would otherwise reinstate the plan just stood
      // down. See `cancelStaleRead`.
      await cancelStaleRead(queryClient);
      queryClient.setQueryData<ActivePlanResponse>(ACTIVE_PLAN_KEY, (current) =>
        current?.plan?.id === abandoned.id ? { ...current, plan: null } : current,
      );
    },
  });
}
