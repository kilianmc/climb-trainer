import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ApiError, NotJsonError } from '../api/client';
import type { SessionLogRequest, SessionLogResponse } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import type { Scope } from '../auth/session';

/**
 * The one call site for `PUT /api/sessions/{client_uuid}` — start, recovery flush, Finish and
 * the RPE follow-up are the same request with a different body (`outbox.ts::buildPut`).
 *
 * ## The rule this file is built on: the query cache holds SERVER RESPONSES ONLY
 *
 * `plan/api.ts` carries the measurements. So: **no `onMutate`, no snapshot, no rollback, no
 * `invalidateQueries`.** `onSuccess` writes the server's own answer and is the only cache write
 * here. The optimistic view is the persisted run itself (`runStore.ts`), which is authoritative
 * until the server acknowledges — a failed write therefore needs no rollback and issues no
 * request.
 *
 * ## ⚠️ NO debounce and NO item-count flush trigger
 *
 * The triggers are Finish, `visibilitychange`→hidden and `online`, and nothing else. Any
 * periodic flush would hold Neon awake for the whole 45–90 minute session for zero user
 * benefit, because the persisted store is already authoritative and a run has exactly one
 * writer. "Add a debounce so we don't lose data" is the well-meaning change that undoes it.
 */

/** Per-uuid: the last `SessionLogResponse` the server sent for that session, and nothing else. */
export const SESSION_LOG_KEY = ['session', 'log'] as const;
export const SESSION_LOG_MUTATION_KEY = ['session', 'log', 'put'] as const;

/** ONE scope, so two triggers firing together serialise instead of racing: `mutationCache.js`
 * runs only a scope's first pending mutation and continues the next when it settles. */
const SESSION_WRITE_SCOPE = { id: 'session-log' } as const;

/** Where one session's server answer lives. */
export function sessionLogKey(clientUuid: string) {
  return [...SESSION_LOG_KEY, clientUuid] as const;
}

/** What to do with a failed flush. There is no third answer and no timer behind either one. */
export type FlushDisposition = 'requeue' | 'quarantine';

/**
 * 4xx is PERMANENT, 5xx is retryable.
 *
 * A 422 rejects the whole flush by design and every detail string on the route is fixed, so a
 * retry can never succeed — quarantine it. A 5xx, a network failure and a `NotJsonError` (a
 * rewrite served the SPA shell) all mean the request never reached the handler, so the sets
 * are requeued and go out on the **next trigger**, never on a timer.
 *
 * ⚠️ **401 requeues.** It belongs to the refresh layer, which has already retried once; one
 * that survives means the session expired, and destroying a climber's sets because they need
 * to log in again would be the worst possible reading of "4xx is permanent".
 */
export function classifyFailure(error: unknown): FlushDisposition {
  if (error instanceof NotJsonError) return 'requeue';
  if (!(error instanceof ApiError)) return 'requeue';
  if (error.status === 401) return 'requeue';
  return error.status >= 400 && error.status < 500 ? 'quarantine' : 'requeue';
}

/** Demo scope issues ZERO writes — #65 satisfied by absence, not by a greyed-out control.
 * The player runs in full and the brief says the run is not saved. */
export function writesEnabled(scope: Scope | null): boolean {
  return scope === 'user';
}

export interface SessionPutVariables {
  readonly clientUuid: string;
  readonly body: SessionLogRequest;
}

/** The mutation; `null` resolves for a demo run, a real outcome rather than a failure. No
 * `retry`: query-core defaults mutations to `0`, so a 4xx reaches `classifyFailure` once. */
export function useSessionLogPut() {
  const { request, scope } = useAuth();
  const queryClient = useQueryClient();
  const enabled = writesEnabled(scope);

  return useMutation({
    mutationKey: SESSION_LOG_MUTATION_KEY,
    scope: SESSION_WRITE_SCOPE,
    mutationFn: async (variables: SessionPutVariables): Promise<SessionLogResponse | null> => {
      if (!enabled) return null;
      return await request<SessionLogResponse>(
        `/api/sessions/${encodeURIComponent(variables.clientUuid)}`,
        { method: 'PUT', json: variables.body },
      );
    },
    // The server's own answer to the write that just committed. The only cache write here, and
    // there is nothing to invalidate: no other observer reads this key.
    onSuccess: (response) => {
      if (response === null) return;
      queryClient.setQueryData(sessionLogKey(response.client_uuid), response);
    },
  });
}
