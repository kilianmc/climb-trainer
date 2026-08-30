import { useQuery } from '@tanstack/react-query';

import type {
  PlanMesocycle,
  PlanSession,
  PlanTree,
  SessionCompletion,
  SessionCompletionResponse,
} from '../api/types';
import { useAuth } from '../auth/AuthProvider';

/* `GET /api/sessions/completion` — the derived figure the plan screen colours past sessions
   with. Its own endpoint because `/api/plans/active` is already the heaviest payload here. */

export const SESSION_COMPLETION_KEY = ['sessions', 'completion'] as const;

/* Ten minutes, matching `ACTIVE_PLAN_STALE_TIME_MS`: the compute rule is that this must not
   wake Neon more often than the plan load it sits beside. */
const COMPLETION_STALE_TIME_MS = 10 * 60_000;

export interface CompletionWindow {
  from: string;
  to: string;
}

/** The plan's own span, which is what the screen renders. `null` when it has no sessions. */
export function planWindow(plan: PlanTree): CompletionWindow | null {
  let last: string | null = null;
  for (const mesocycle of plan.mesocycles) {
    for (const microcycle of mesocycle.microcycles) {
      for (const session of microcycle.sessions) {
        if (last === null || session.scheduled_on > last) last = session.scheduled_on;
      }
    }
  }
  return last === null ? null : { from: plan.start_date, to: last };
}

/** Keyed by `planned_session_id`, which is the only id the plan tree can look one up by. */
export function completionBySession(
  response: SessionCompletionResponse | undefined,
): ReadonlyMap<number, SessionCompletion> {
  return new Map((response?.sessions ?? []).map((row) => [row.planned_session_id, row] as const));
}

/** The ONE boundary in the colour rule: `50` and up is amber, below it red. Kilian's "yellow if
 *  its more than 50%" / "below 50% red" leaves 50 unclaimed, so it is decided here, once. */
export const AMBER_FLOOR_PERCENT = 50;

export type CompletionBand = 'full' | 'partial' | 'low';

/** The band is the PERCENTAGE's, never the session's: `100` green, `50`–`99` amber, under `50` red. */
export function completionBand(percent: number): CompletionBand {
  if (percent >= 100) return 'full';
  return percent >= AMBER_FLOOR_PERCENT ? 'partial' : 'low';
}

/** The word and the tint from ONE decision, so colour is never the only channel. */
export interface CompletionBadge {
  readonly label: string;
  readonly band: CompletionBand;
}

/** ⚠️ `status` is NOT consulted — "unfinished and skipped is the same result in real life"
 *  (Kilian) — so a past session is only its percentage. `null` when it has no percentage. */
export function completionBadge(row: SessionCompletion | undefined): CompletionBadge | null {
  if (row === undefined || row.state === 'pending' || row.percent === null) return null;
  const percent = row.percent;
  const band = completionBand(percent);
  if (percent === 0) return { label: 'Skipped', band };
  return { label: band === 'full' ? 'Completed' : `${String(percent)}% done`, band };
}

/** One block row's mark on a past session's card. */
export type BlockOutcome = 'done' | 'missed';

/** The WORD beside the tint, from the same decision — colour is never the only channel. */
export const BLOCK_MARK_LABEL: Record<BlockOutcome, string> = { done: 'Done', missed: 'Missed' };

/** The blocks a session got done — `null` while its rows must stay unmarked: only a PAST session
 *  is marked, on the server's own `pending`, since an unreached block is not a missed one. */
export function doneBlocks(row: SessionCompletion | undefined): ReadonlySet<number> | null {
  if (row === undefined || row.state === 'pending') return null;
  return new Set(row.done_block_ids);
}

/** ONE block's mark. Keyed on `session_block.id`, which is what `done_block_ids` names and what
 *  a PERSISTED block carries; `null` for a preview block, whose id does not exist yet. */
export function blockOutcome(
  done: ReadonlySet<number> | null,
  blockId: number | null | undefined,
): BlockOutcome | null {
  if (done === null || blockId == null) return null;
  return done.has(blockId) ? 'done' : 'missed';
}

/** A PHASE's aggregate, for the badge a COLLAPSED phase carries: the same three bands, over the
 *  mean of its sessions rather than over one session's blocks. */
export interface PhaseCompletion {
  readonly label: string;
  readonly percent: number;
  readonly band: CompletionBand;
}

/** Whole percent, half-up in integer arithmetic — the same shape as the server's `_percent`, so
 *  the two can never disagree by a rounding step. */
function meanPercent(percents: readonly number[]): number {
  const total = percents.reduce((sum, percent) => sum + percent, 0);
  return Math.floor((total * 2 + percents.length) / (percents.length * 2));
}

/** Every planned session in one phase, in schedule order. */
function phaseSessions(mesocycle: PlanMesocycle): readonly PlanSession[] {
  return mesocycle.microcycles.flatMap((microcycle) => microcycle.sessions);
}

/** ⚠️ EQUAL WEIGHT PER SESSION (Kilian, 2026-08-30): twelve sessions in a phase are twelve
 *  twelfths, so this is the MEAN of their percentages, NOT blocks done over blocks planned. */
export function phaseCompletionBadge(
  mesocycle: PlanMesocycle,
  completion: ReadonlyMap<number, SessionCompletion>,
  todayIso: string,
): PhaseCompletion | null {
  const sessions = phaseSessions(mesocycle);
  // Only a phase ENTIRELY in the past is scored: a future phase reading 0% red would be alarming
  // and wrong, and the one being trained is deliberately left unbadged while it can still move.
  const allPast = sessions.every((session) => session.scheduled_on < todayIso);
  if (sessions.length === 0 || !allPast) return null;

  const rows = sessions.map((session) =>
    session.id == null ? undefined : completion.get(session.id),
  );
  // A skipped or never-started session is a real 0. No row (a preview, or a read still in flight)
  // and `percent === null` (no blocks, unreachable today) have no result to average, so they go.
  const scored = rows
    .map((row) => row?.percent ?? null)
    .filter((percent): percent is number => percent !== null);
  if (scored.length === 0) return null;

  const percent = meanPercent(scored);
  // ⚠️ The bands and the 50 boundary come from the ONE session decision point, never a copy.
  const band = completionBand(percent);
  return { label: band === 'full' ? 'Completed' : `${String(percent)}% done`, band, percent };
}

/** One PERSISTED plan's figures. Disabled for a preview (no rows, so no id to ask about) and
 *  on `isAuthenticated`, for the measured reason in `profile/api.ts`: a 401 costs a PG write. */
export function useSessionCompletion(plan: PlanTree | null) {
  const { request, isAuthenticated } = useAuth();
  const window = plan === null || plan.id == null ? null : planWindow(plan);

  return useQuery({
    queryKey: [...SESSION_COMPLETION_KEY, window],
    queryFn: () =>
      request<SessionCompletionResponse>(
        `/api/sessions/completion?from=${encodeURIComponent(window?.from ?? '')}&to=${encodeURIComponent(window?.to ?? '')}`,
      ),
    staleTime: COMPLETION_STALE_TIME_MS,
    enabled: isAuthenticated && window !== null,
  });
}
