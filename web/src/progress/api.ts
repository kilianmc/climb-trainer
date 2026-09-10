import { useQuery } from '@tanstack/react-query';

import type { AspectVolumeResponse } from '../api/types';
import { useAuth } from '../auth/AuthProvider';

export const ASPECT_VOLUME_KEY = ['sessions', 'volume'] as const;

/** Ten minutes, matching the plan, profile and journal reads: Neon bills awake time, not rows. */
const VOLUME_STALE_TIME_MS = 10 * 60_000;

/** `enabled` for the measured reason on `profile/api.ts::useVocabulary`: a logged-out observer
 *  refetches, that is a 401, and the refresh path answers a 401 with a Postgres write. */
export function useAspectVolume() {
  const { request, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ASPECT_VOLUME_KEY,
    queryFn: () => request<AspectVolumeResponse>('/api/sessions/volume'),
    staleTime: VOLUME_STALE_TIME_MS,
    enabled: isAuthenticated,
  });
}
