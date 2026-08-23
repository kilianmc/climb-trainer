/**
 * `GET /api/library` — the exercise library, fetched once per deploy and never refetched.
 *
 * Two settings, and both are compute decisions rather than UX ones:
 *
 * 1. **`?v=${BUILD_ID}`.** The server answers `public, s-maxage=31536000, immutable`, so
 *    the CDN holds this body for a year and the URL is the only thing that can invalidate
 *    it. The build id is the deploy commit SHA (`src/buildId.ts`).
 * 2. **`staleTime: Infinity`.** The content changes only when `server/contentseed.py` runs,
 *    which is an out-of-band dispatch that ships with a deploy — so a refetch inside one
 *    session can only ever return the same bytes. Neon Free gives ~400 awake hours a month
 *    and every origin read costs a five-minute window, so a refetch that finds nothing new
 *    is not free; it is the most expensive kind of no-op this app can make.
 *
 * ⚠️ **The build id is in the QUERY KEY too**, not only in the URL. TanStack Query keys the
 * cache itself, and a key of just `['library']` would let a stale entry rehydrate across a
 * deploy in any persisted-cache future while the URL said otherwise.
 *
 * `enabled: isAuthenticated`, exactly as `useVocabulary` is and for the same measured
 * reason: logging out clears the cache, and a mounted observer whose query was just removed
 * refetches — a 401, which the refresh path answers with a Postgres write. See
 * `profile/api.ts` for the full note.
 */
import { useQuery } from '@tanstack/react-query';

import type { ExerciseLibrary } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { BUILD_ID } from '../buildId';

export const LIBRARY_KEY = ['library', BUILD_ID] as const;

export function useLibrary() {
  const { request, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: LIBRARY_KEY,
    queryFn: () => request<ExerciseLibrary>(`/api/library?v=${encodeURIComponent(BUILD_ID)}`),
    staleTime: Infinity,
    enabled: isAuthenticated,
  });
}
