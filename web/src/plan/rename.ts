import type { ActivePlanResponse, Journal, PlanNameResponse } from '../api/types';
import { ApiError } from '../api/client';

/** Renaming a plan, pure half: the name bound mirrored at the edge, and what a rename does to
 *  the two caches carrying a plan's name. Nothing here renders — `diaryScreen.test.tsx`. */

/** `server/models.py::PLAN_NAME_MAX`, mirrored so the control can stop before the server does. */
export const PLAN_NAME_MAX = 80;

/** The typed name as it would be STORED, or `null` when the server would refuse it. Stripped
 *  first and then measured, which is the order `server/fields.py::PlanName` applies. */
export function parsedPlanName(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === '' || trimmed.length > PLAN_NAME_MAX) return null;
  return trimmed;
}

/** What to say under the field, or `null` when there is nothing to say. Off `parsedPlanName`, so
 *  the hint and the refusal can never disagree about a value — `journal.ts::bodyWeightHint`. */
export function planNameHint(raw: string): string | null {
  if (parsedPlanName(raw) !== null) return null;
  const trimmed = raw.trim();
  if (trimmed === '') return 'A plan needs a name. Type one, or cancel and keep the old one.';
  return `That is ${String(trimmed.length)} characters. Keep a plan name to ${String(PLAN_NAME_MAX)} or fewer.`;
}

/** What went wrong, in the climber's words. A 404 is a plan that is gone or was never theirs, so
 *  retrying cannot help and re-reading can; anything else leaves the typed name on screen. */
export function renameFailure(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return 'That plan is not there any more, so nothing was renamed. Open your diary again.';
  }
  return 'That name did not save. Nothing changed — try again, or cancel and keep the old one.';
}

/** ⚠️ `renamed.name` is the STORED value, never what the field held: the server strips. */
export function journalWithRenamedPlan(journal: Journal, renamed: PlanNameResponse): Journal {
  if (!journal.plans.some((plan) => plan.plan_id === renamed.id)) return journal;
  return {
    ...journal,
    plans: journal.plans.map((plan) =>
      plan.plan_id === renamed.id ? { ...plan, name: renamed.name } : plan,
    ),
  };
}

/** The same install on the OTHER cache holding a name. Untouched when the renamed plan is not
 *  the active one, which is the ordinary case: a finished plan is renameable too. */
export function activeWithRenamedPlan(
  envelope: ActivePlanResponse,
  renamed: PlanNameResponse,
): ActivePlanResponse {
  const plan = envelope.plan ?? null;
  if (plan === null || plan.id !== renamed.id) return envelope;
  return { ...envelope, plan: { ...plan, name: renamed.name } };
}
