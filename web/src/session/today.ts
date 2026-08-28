import type { PlanSession, PlanTree } from '../api/types';

/** Which session is on today. Pure — the date is passed in, so "22:00 in UTC+2 is still
 * today" is a unit test rather than a timezone the CI machine happens to run in. */

/**
 * Today, in the browser's own timezone, as `YYYY-MM-DD`.
 *
 * ⚠️ **`toISOString().slice(0, 10)` is WRONG here and the bug is silent.** It formats UTC, so
 * east of Greenwich every evening after `24:00 - offset` reports tomorrow and west of it every
 * morning reports yesterday — the session the climber is standing in front of disappears, and
 * `occurred_on` lands on the wrong day in the diary. Built from local parts instead, the same
 * way `plan/blueprint.ts::nextMonday` is and for the same reason.
 */
export function localIsoDate(now: Date): string {
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${String(now.getFullYear())}-${month}-${day}`;
}

/** Why the screen is showing what it is showing. */
export type SelectionReason = 'today' | 'rest_day' | 'plan_over' | 'no_plan';

export interface SessionChoice {
  /** The session to offer, or `null` when there is nothing left to offer at all. */
  readonly session: PlanSession | null;
  /** The plan calls for recovery today and `session` is the NEXT one, not today's. The
   * screen puts it behind a notice rather than pretending it is due. */
  readonly restDay: boolean;
  readonly reason: SelectionReason;
  /** `scheduled_on` of `session`, so the notice can name the day without re-searching. */
  readonly scheduledOn: string | null;
}

/** Every session in the tree, in schedule order. The tree is already sorted; this flattens it. */
export function planSessions(plan: PlanTree | null | undefined): PlanSession[] {
  if (plan == null) return [];
  return plan.mesocycles.flatMap((mesocycle) =>
    mesocycle.microcycles.flatMap((microcycle) => microcycle.sessions),
  );
}

/** Today's session, or the next one behind a rest-day notice. A `completed` one is still
 * returned: re-entering the player must find the run it just logged, not skip to Thursday. */
export function selectSession(plan: PlanTree | null | undefined, todayIso: string): SessionChoice {
  const sessions = planSessions(plan);
  if (sessions.length === 0)
    return { session: null, restDay: false, reason: 'no_plan', scheduledOn: null };

  const today = sessions.find((session) => session.scheduled_on === todayIso);
  if (today !== undefined) {
    return { session: today, restDay: false, reason: 'today', scheduledOn: today.scheduled_on };
  }

  const upcoming = sessions.find((session) => session.scheduled_on > todayIso);
  if (upcoming === undefined) {
    return { session: null, restDay: false, reason: 'plan_over', scheduledOn: null };
  }
  return {
    session: upcoming,
    restDay: true,
    reason: 'rest_day',
    scheduledOn: upcoming.scheduled_on,
  };
}

/** How many prescribed sets can actually be written. `LoggedSetIn.exercise_id` is required
 * and a PREVIEWED plan has none, so such a run is playable and unloggable — say so up front. */
export function loggableSets(session: PlanSession): number {
  return session.blocks.reduce(
    (total, block) => total + (block.exercise_id == null ? 0 : block.sets.length),
    0,
  );
}

/** Every prescribed set in the session, loggable or not. */
export function totalSets(session: PlanSession): number {
  return session.blocks.reduce((total, block) => total + block.sets.length, 0);
}
