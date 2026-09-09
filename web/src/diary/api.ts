import { keepPreviousData, useQuery } from '@tanstack/react-query';

import type { Journal } from '../api/types';
import { useAuth } from '../auth/AuthProvider';

/** `GET /api/journal`, in two flavours under two keys: scoped to one plan, and unscoped. Both
 *  stay cached, so opening the full history and going back costs no second request. */

export const JOURNAL_READ_KEY = ['journal', 'read'] as const;

/** Ten minutes, matching the plan and profile reads: Neon bills awake time, not rows. */
const JOURNAL_STALE_TIME_MS = 10 * 60_000;

/** `null` is the UNSCOPED read — every plan's entries — and is a distinct cache entry from any
 *  plan's own. A `plan_id` for a plan that is not this climber's is a 200 with no entries. */
export function journalReadKey(planId: number | null) {
  return [...JOURNAL_READ_KEY, planId] as const;
}

/** `enabled` for the measured reason on `profile/api.ts::useVocabulary`: a logged-out observer
 *  refetches, that is a 401, and the refresh path answers a 401 with a Postgres write. */
export function useJournal(planId: number | null, wanted: boolean) {
  const { request, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: journalReadKey(planId),
    queryFn: () =>
      request<Journal>(
        planId === null ? '/api/journal' : `/api/journal?plan_id=${encodeURIComponent(planId)}`,
      ),
    staleTime: JOURNAL_STALE_TIME_MS,
    // ⚠️ SCROLL, not speed: the scope switch changes the KEY, so without this the gate meets the
    // empty key with its loading page, the page collapses, and the browser clamps to the top.
    placeholderData: keepPreviousData,
    enabled: wanted && isAuthenticated,
  });
}
