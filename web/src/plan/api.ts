import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import type { PlanPreview, Profile } from '../api/types';
import { useAuth } from '../auth/AuthProvider';

import { canPreview, nextMonday, previewKeyParts } from './blueprint';

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
 * ⚠️ **Never persisted.** The whole app persists no query cache
 * (`CLAUDE.md`, the federated-`localStorage` rule), and this is the one endpoint where doing it
 * would be an actual data leak rather than a policy breach: the body names the user's open
 * injuries.
 *
 * ## `enabled`, both halves
 *
 * - **`isAuthenticated`** for the measured reason in `profile/api.ts:88-100`: logging out clears
 *   the cache, a still-mounted observer refetches, that is a 401, and the refresh path answers a
 *   401 with a **Postgres write**.
 * - **`canPreview(profile)`** because the client holds the profile and can see a refusal before
 *   asking for one — see `blueprint.ts`. The 422 stays as defence in depth; it is just not the
 *   normal way this screen learns that a step is unanswered.
 */
export const PLAN_PREVIEW_KEY = ['plan', 'preview'] as const;

export function usePlanPreview(profile: Profile | undefined) {
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
      request<PlanPreview>('/api/plans/preview', {
        method: 'POST',
        json: { start_date: startDate },
      }),
    staleTime: Infinity,
    enabled: isAuthenticated && parts !== null,
  });
}
