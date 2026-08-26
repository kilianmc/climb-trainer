import { useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import type { ActivePlanResponse, PlanAbandoned, PlanTree, Profile } from '../api/types';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthProvider';

import { canPreview, nextMonday, previewKeyParts } from './blueprint';

/**
 * The one read that costs a generation, the one read that says what the climber HAS, and the
 * two writes between them.
 *
 * ## ⚠️ THE RULE THIS FILE IS BUILT ON: the query cache holds SERVER RESPONSES ONLY
 *
 * `web/src/profile/api.ts` carries the measurements — three review rounds, three bugs, every one
 * of them from two writers for one cache entry. So: **no `onMutate`, no snapshot, nothing at all
 * on the error path.** `onSuccess` writes the server's own answer and is the only cache write
 * here; the optimistic view is DERIVED at render time from the pending mutation's variables
 * (`useActivePlanView`), so a failed write needs no rollback and issues no request. Hence no
 * `invalidateQueries` anywhere — the 409 recovery is a read *inside* `mutationFn`, under the same
 * `scope` serialisation, rather than a write racing out of an `onError`.
 *
 * ## Verified against `web/node_modules/@tanstack/query-core@5.101.4`, `build/modern/`
 *
 * Per CLAUDE.md's standing rule, every claim below was read there:
 *
 * - `mutation.js:82` — `retry: this.options.retry ?? 0`: a mutation does not retry, so the 409
 *   reaches `mutationFn`'s `catch` once.
 * - `mutation.js:94` — `execute()` dispatches `{ type: 'pending', variables }` **synchronously**,
 *   before the retryer and `onMutate`, so the derived overlay lands on the click.
 * - `mutation.js:135-144` — `retryer.start()` -> `onSuccess` -> `onSettled` ->
 *   `dispatch('success')`: the cache is written before the mutation leaves `pending`.
 * - `mutationCache.js:60-67`/`75` + `mutation.js:194` — `canRun` is true only for the *first
 *   pending* mutation in a scope, and `runNext` continues the next. So `scope: { id: 'plan' }`
 *   serialises the REQUESTS: a create and an abandon are never on the wire at once.
 * - `queryClient.js:92-103` — `setQueryData` writes nothing when the updater yields `undefined`,
 *   which is how `useAbandonPlan` says "leave the cache alone".
 * - `queryObserver.js:331` — `isLoadingError: isError && !hasData`, the "nothing to show"
 *   question every screen here gates on instead of `isError`.
 * - `queryClient.js:141-147` + `query.js:268-270` — `cancelQueries` defaults to
 *   `{ revert: true }` and a reverted `CancelledError` restores `#revertState`, so cancelling an
 *   in-flight read **removes** a writer rather than adding one. See `cancelStaleRead`.
 */

/** `POST /api/plans/preview`. The parts are appended per call — see `usePlanPreview`. */
export const PLAN_PREVIEW_KEY = ['plan', 'preview'] as const;
/** `GET /api/plans/active`. Holds the whole `{plan}` envelope, exactly as the server sent it. */
export const ACTIVE_PLAN_KEY = ['plan', 'active'] as const;

/**
 * Declared so `useActivePlanView` can find *our* pending abandon and nobody else's:
 * `matchMutation` (query-core `utils.js`) returns false for any mutation with no `mutationKey`.
 */
export const PLAN_CREATE_KEY = ['plan', 'create'] as const;
export const PLAN_ABANDON_KEY = ['plan', 'abandon'] as const;

/**
 * ONE scope for both writes: creating a plan stands the previous one down in the same server
 * transaction, so a create and an abandon must never overlap. A double-tap sends its second
 * `POST` only after the first returned, which the server answers with a legitimate 201. The 409
 * comes from a *second tab or device*, where nothing on this client can serialise anything.
 */
const PLAN_WRITE_SCOPE = { id: 'plan' } as const;

/**
 * Ten minutes, matching the profile's: every `POST` replaces the entry outright. ⚠️ A second TAB
 * stays stale that long and focusing it will not refresh it (`refetchOnWindowFocus: false`, set
 * in `router.tsx` because a gym phone flaps between focused and blurred). Benign — the worst
 * case is a Start that comes back 409 and installs the truth.
 */
const ACTIVE_PLAN_STALE_TIME_MS = 10 * 60_000;

/**
 * Drop any `GET /api/plans/active` still on the wire, before a mutation installs its answer. A
 * read issued *before* a Start and resolving *after* it would write the OLD plan over the new
 * one, and the screen would hold it for `staleTime`. **Plausible rather than reproduced** (0.050 s
 * read against a 0.243 s write), but a cold Neon wake lands on the read as easily as the write.
 *
 * ⚠️ **It adds no writer, so one-writer-per-cache-entry still holds**: the cancelled read writes
 * nothing at all (`queryClient.js:142`, `query.js:268-270`), leaving the mutation's
 * `setQueryData` the only writer. It is the opposite of the PR #9 bug — an extra READ fired from
 * an error handler. `await`ed because `mutation.js:135-144` awaits `onSuccess` before dispatching
 * `success`, so the button stays busy until the cache is true.
 */
async function cancelStaleRead(queryClient: ReturnType<typeof useQueryClient>): Promise<void> {
  await queryClient.cancelQueries({ queryKey: ACTIVE_PLAN_KEY });
}

/**
 * `POST /api/plans/preview` — the plan the generator would build, never written.
 *
 * **`useQuery`, not `useMutation`**, because the hooks differ on cache semantics rather than HTTP
 * verbs: the response is a pure function of the inputs and must not be re-sent on remount. The
 * verb is `POST` only because a per-user body on a cacheable verb is the `/api/library` CDN trap
 * (`server/plans/routes.py` carries that reasoning). A mutation would re-generate a 32-week plan
 * on every visit.
 *
 * **The key IS the inputs** — `start_date` plus every profile field the planner reads plus an
 * injury fingerprint — so a profile change is a new key and a new fetch with nothing to
 * invalidate, and `staleTime: Infinity` is simply true rather than a bet.
 *
 * ⚠️ **The hook keeps the name `usePlanPreview`.** The plan the climber *has* versus the plan we
 * would *offer* is the only thing separating these two hooks — their response type is identical
 * (`PlanTree`) — so the names have to keep carrying it.
 *
 * ⚠️ **Never persisted.** The app persists no query cache (`CLAUDE.md`, the
 * federated-`localStorage` rule), and this is the one endpoint where doing it would be an actual
 * data leak rather than a policy breach: the body names the user's open injuries.
 *
 * `enabled`, all three parts:
 *
 * - **`isAuthenticated`** for the measured reason in `profile/api.ts:88-100`: logging out clears
 *   the cache, a still-mounted observer refetches, that is a 401, and the refresh path answers a
 *   401 with a **Postgres write**.
 * - **`canPreview(profile)`** — the client holds the profile and can see a refusal before asking
 *   for one (`blueprint.ts`). The 422 stays as defence in depth.
 * - **`wanted`**, a compute decision: this is the most expensive read in the app, and a climber
 *   who already has a plan did not ask for another by arriving here. The two reads are therefore
 *   **sequential** on the empty-state path — one extra round trip for a new account, against a
 *   wasted generation on every visit for every account in the steady state.
 */
export function usePlanPreview(profile: Profile | undefined, wanted = true) {
  const { request, isAuthenticated } = useAuth();

  // Fixed for the life of the mount. It is a query-key input, so re-deriving it every render
  // would be a new key — and a new 32-week generation — the moment the clock crosses midnight.
  const startDate = useMemo(() => nextMonday(new Date()), []);

  // A key is required even while the query is disabled, so the unplannable case gets `null`,
  // which cannot collide with a real key.
  const parts =
    profile !== undefined && canPreview(profile) ? previewKeyParts(profile, startDate) : null;

  return useQuery({
    queryKey: [...PLAN_PREVIEW_KEY, parts],
    // A body is mandatory — a bodyless POST is a 422 — and `json` sets the content-type
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
 * ⚠️ **`{"plan": null}` is the empty state and arrives as a 200**, not a 404; every new account
 * is in it. `server/plans/routes.py::ActivePlanResponse` carries why.
 *
 * `select` keeps that legible: the **cache holds the envelope the server sent** (so
 * `setQueryData` in both mutations writes a server-shaped value) while observers see
 * `PlanTree | null`, with `undefined` meaning only "the first read has not landed".
 *
 * ⚠️ `?? null` rather than bare `response.plan`: the field is required on the wire, but the two
 * readings of absent are "no plan" and "still loading", and only the first is safe — the second
 * parks the screen on a spinner forever. Same argument as `blueprint.ts::unanswered`.
 *
 * Enabled on `isAuthenticated` for the measured reason in `profile/api.ts`. **Not** gated on the
 * profile being plannable: a plan does not stop existing because the answers behind it moved.
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
   * `undefined` — the first read has not landed. `null` — there is no plan, a normal screen.
   * A `PlanTree` — the plan the climber is on, with every `id` filled.
   */
  plan: PlanTree | null | undefined;
  /**
   * There is **nothing to show** and the read failed — the only condition under which a screen
   * may replace itself with an error.
   *
   * ⚠️ Not `isError`: `query.js`'s error reducer sets `status: "error"` even when data is
   * present, so a failing background refetch would otherwise blow away a plan the climber is
   * reading. `queryObserver.js:331` derives `isLoadingError` as `isError && !hasData`.
   */
  isLoadingError: boolean;
  /** Nothing else will retry: `refetchOnWindowFocus` is off app-wide. */
  retry: () => void;
}

/**
 * Server truth, plus the one optimistic thing this screen can honestly guess.
 *
 * **An abandon in flight renders as "no plan", derived from the pending mutation's own variables
 * and written nowhere.** The click is a Tier-1 write, so the UI must not wait on Postgres, and
 * `mutation.js:94` dispatches `pending` synchronously. A failure just drops the overlay — no
 * rollback, no request.
 *
 * ⚠️ **A pending CREATE gets no overlay, deliberately.** The optimistic value would be a whole
 * plan tree the server has not generated yet, and inventing one is exactly what "the cache holds
 * server responses only" forbids.
 *
 * The id is compared rather than assumed, because an abandon can name a plan that is not the
 * active one (a second tab stood a different plan down).
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
 * Callers pass the **`start_date` of the plan on screen**, not today's Monday recomputed. Both
 * routes normalise identically, so echoing the preview's own value is what guarantees the saved
 * plan starts on the day the preview showed; a mount that crossed midnight would otherwise
 * persist a plan a week away from the one the climber read.
 *
 * ⚠️ **A 409 is not a failure, and the recovery lives inside `mutationFn`.**
 * `uq_plan_one_active_per_user` answers a second active plan with a 409, and that climber **does
 * have a plan** — so the honest response is to read it. Not in `onError`, for the reason at the
 * top of the file: an `invalidateQueries` from an error handler is the PR #9 bug (measured — a
 * refetch issued before the next write committed resolved second and overwrote a newer
 * `onSuccess`). Inside `mutationFn` it stays under `PLAN_WRITE_SCOPE`, resolves before
 * `onSuccess`, and leaves exactly one writer either way. `null` is legitimate: another session
 * abandoned the plan in between, so the screen offers Start again. Only a 409 `ApiError` is
 * caught; anything else — a `NotJsonError` means a rewrite ate the request — rethrows.
 *
 * **`handlers.onSuccess` is attached HERE, not to `mutate(vars, { … })`.** Per-call options live
 * on the observer, and `mutationObserver.js` drops the observer from the in-flight mutation when
 * a newer `mutate()` arrives, so a superseded mutation's callback would report to nobody.
 * `mutation.js` calls `this.options.onSuccess` with no observer involved. Same shape as
 * `profile/api.ts::ProfilePatchHandlers`.
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
    // 409 recovery read returned. Never a guess, and the only cache write on this path.
    onSuccess: async (plan) => {
      await cancelStaleRead(queryClient);
      queryClient.setQueryData<ActivePlanResponse>(ACTIVE_PLAN_KEY, { plan });
      handlers.onSuccess?.(plan);
    },
  });
}

/**
 * `POST /api/plans/{plan_id}/abandon` — stand a plan down. Marks, never deletes. Idempotent
 * server-side, 404 for anyone else's plan, and it shares `PLAN_WRITE_SCOPE` with `useCreatePlan`.
 *
 * The response is `{id, abandoned_at}` — not a plan — so there is no server-shaped envelope to
 * install, but "plan `id` is abandoned" entails `{plan: null}` rather than guessing it. Written
 * **only when the cached plan is that plan**: an abandon naming some other plan (a second tab, a
 * stale screen) must not clear an entry that was never about it. Returning `current` unchanged is
 * how "leave the cache alone" is spelled, including when it is `undefined`, which
 * `queryClient.js:99` turns into no write at all.
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
