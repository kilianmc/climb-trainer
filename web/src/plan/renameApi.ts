import { useMutation, useQueryClient } from '@tanstack/react-query';

import type { ActivePlanResponse, Journal, PlanNameResponse } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { JOURNAL_READ_KEY } from '../diary/api';
import { writesEnabled } from '../session/api';

import { ACTIVE_PLAN_KEY } from './api';
import { activeWithRenamedPlan, journalWithRenamedPlan } from './rename';

/** The one call site for `PUT /api/plans/{plan_id}/name`. The ack carries the STORED name, so
 *  there is something to install and no read to issue — `api.ts`'s one-writer rule holds. */

export const PLAN_RENAME_MUTATION_KEY = ['plan', 'rename'] as const;

/** ONE scope, so a double-tapped Save serialises instead of racing — `api.ts`'s reasoning. */
const PLAN_RENAME_SCOPE = { id: 'plan-rename' } as const;

export interface RenamePlanVariables {
  readonly planId: number;
  /** What the field HOLDS. The server strips it, so `PlanNameResponse.name` is the only place
   *  the stored value exists and this is not it. */
  readonly name: string;
}

/** `null` resolves for a demo run: a real outcome rather than a failure, as on the journal PUT.
 *  The affordance is ABSENT for that principal (#65) — this is defence in depth behind it. */
export function useRenamePlan() {
  const { request, scope } = useAuth();
  const queryClient = useQueryClient();
  const enabled = writesEnabled(scope);

  return useMutation({
    mutationKey: PLAN_RENAME_MUTATION_KEY,
    scope: PLAN_RENAME_SCOPE,
    mutationFn: async (variables: RenamePlanVariables): Promise<PlanNameResponse | null> => {
      if (!enabled) return null;
      return await request<PlanNameResponse>(
        `/api/plans/${encodeURIComponent(variables.planId)}/name`,
        { method: 'PUT', json: { name: variables.name } },
      );
    },
    // ⚠️ TWO caches carry a plan's name and a stale one makes the screen contradict itself: the
    // journal read's `plans` lookup — under every key it has — and the active plan's envelope.
    onSuccess: async (renamed) => {
      if (renamed === null) return;
      // A read already on the wire would resolve after this and write the OLD name back.
      // Cancelling REMOVES a writer rather than adding one — `api.ts::cancelStaleRead`.
      await queryClient.cancelQueries({ queryKey: ACTIVE_PLAN_KEY });
      await queryClient.cancelQueries({ queryKey: JOURNAL_READ_KEY });
      // A PREFIX, deliberately: the scoped read and the whole history are two entries and both
      // hold the name. `journalReadKey`'s two flavours are exactly why this is not `setQueryData`.
      queryClient.setQueriesData<Journal>({ queryKey: JOURNAL_READ_KEY }, (current) =>
        current === undefined ? current : journalWithRenamedPlan(current, renamed),
      );
      queryClient.setQueryData<ActivePlanResponse>(ACTIVE_PLAN_KEY, (current) =>
        current === undefined ? current : activeWithRenamedPlan(current, renamed),
      );
    },
  });
}
