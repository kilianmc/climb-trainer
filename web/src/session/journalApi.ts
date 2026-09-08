import { useMutation } from '@tanstack/react-query';

import type { JournalEntryRequest, JournalEntryResponse } from '../api/types';
import { useAuth } from '../auth/AuthProvider';

import { writesEnabled } from './api';

/** The one call site for `PUT /api/journal/{client_uuid}`. **No cache write at all**: nothing
 *  reads entries back yet (PR C), so `onSuccess` would have nothing true to install. */

export const JOURNAL_PUT_MUTATION_KEY = ['journal', 'put'] as const;

/** ONE scope, so a double-tap on Save serialises instead of racing — `api.ts`'s reasoning. */
const JOURNAL_WRITE_SCOPE = { id: 'journal-write' } as const;

export interface JournalPutVariables {
  readonly clientUuid: string;
  readonly body: JournalEntryRequest;
}

/** `null` resolves for a demo run: a real outcome rather than a failure, as on the session PUT.
 *  No `retry` — query-core defaults mutations to `0`, so a 4xx is classified once. */
export function useJournalPut() {
  const { request, scope } = useAuth();
  const enabled = writesEnabled(scope);

  return useMutation({
    mutationKey: JOURNAL_PUT_MUTATION_KEY,
    scope: JOURNAL_WRITE_SCOPE,
    mutationFn: async (variables: JournalPutVariables): Promise<JournalEntryResponse | null> => {
      if (!enabled) return null;
      return await request<JournalEntryResponse>(
        `/api/journal/${encodeURIComponent(variables.clientUuid)}`,
        { method: 'PUT', json: variables.body },
      );
    },
  });
}
