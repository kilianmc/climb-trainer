import type {
  LibraryExercise,
  Phase,
  PlanBlock,
  PlanSession,
  Prescription,
  Profile,
} from '../api/types';
import { humanise, prescriptionLine } from '../library/browse';

/**
 * The pure half of the `/plan` screen: what may be asked for, what identifies the answer, and
 * the joins and one-line summaries the markup needs. No React, no fetch, no rendering — so the
 * decisions below are testable without mounting anything.
 *
 * ## Why the client decides whether to ask at all
 *
 * `POST /api/plans/preview` answers an unplannable profile with a 422 carrying one fixed
 * sentence, and that stays as defence in depth. But the client already holds the profile, so it
 * can see the refusal coming and show the sentence — plus a way to fix it — without spending a
 * request, a Neon wake and a 422 on a question it could already answer. That is what
 * `previewBlocker` is for, and it is why `usePlanPreview` is `enabled` on it.
 *
 * ⚠️ **The five sentences below are copied VERBATIM from
 * `server/domain/planner/contract.py::REFUSAL_MESSAGES`**, reworked on Kilian's dev-server
 * sign-off (2026-08-24) and frozen. Do not reword, retitle or repunctuate one. They are
 * duplicated rather than fetched because the whole point is to have them before the request —
 * and the duplication is self-checking: `tests/test_planner_refusal_copy.py` parses this
 * declaration and fails until both copies say the same thing.
 *
 * The sixth refusal, `cross_discipline_grades`, is deliberately **not** here: spotting it needs
 * the grade ladder from `GET /api/vocabulary`, both pickers are locked to one scale so it should
 * be unreachable, and if it does happen the server's own 422 says so. Splitting it that way
 * keeps this module free of the vocabulary.
 */

/** Which answer is missing. Mirrors `RefusalReason`'s values for the five cases visible here. */
export type PreviewBlockerReason =
  | 'no_target_grade'
  | 'no_current_grade'
  | 'sessions_per_week_unanswered'
  | 'available_weekdays_unanswered'
  | 'no_available_days';

export interface PreviewBlocker {
  reason: PreviewBlockerReason;
  message: string;
  /**
   * Where the answer is given. `/onboarding` resumes at the first unanswered step — but it
   * redirects a COMPLETE profile to `/profile`, and `available_weekdays === 0` is a complete
   * answer (`profile/completion.ts` counts the step done), so that one case has to go straight
   * to the editor or the link bounces.
   */
  fix: '/onboarding' | '/profile';
}

const BLOCKER_MESSAGES: Record<PreviewBlockerReason, string> = {
  no_target_grade:
    "Your plan is built around a target grade. Finish setting up your profile and we'll build it.",
  no_current_grade:
    "Your plan needs to know what you climb now as well as what you're aiming at. Finish " +
    "setting up your profile and we'll build it.",
  sessions_per_week_unanswered:
    "Your plan needs to know how often you can train. Finish setting up your profile and we'll " +
    'build it.',
  available_weekdays_unanswered:
    "Your plan needs to know which days you can train. Finish setting up your profile and we'll " +
    'build it.',
  no_available_days:
    "You haven't marked any day as available, so there's nowhere to put a session. Tick at " +
    "least one day in your profile and we'll build it.",
};

/**
 * The first answer the generator would refuse over, or `null` when it would build a plan.
 *
 * The order matches `server/plans/routes.py::_planner_input` exactly, so a profile missing two
 * answers names the same one on both sides of the wire. ⚠️ `available_weekdays` is tested
 * `=== null` before `=== 0`: zero is a legal *answer* ("answered, no days") with its own
 * sentence, and a truthiness check there would send the user to the wrong step.
 */
export function previewBlocker(profile: Profile): PreviewBlocker | null {
  const blocker = (reason: PreviewBlockerReason, fix: PreviewBlocker['fix']): PreviewBlocker => ({
    reason,
    message: BLOCKER_MESSAGES[reason],
    fix,
  });

  if (unanswered(profile.target_grade_id) || unanswered(profile.primary_discipline)) {
    return blocker('no_target_grade', '/onboarding');
  }
  if (unanswered(profile.current_grade_id)) return blocker('no_current_grade', '/onboarding');
  if (unanswered(profile.sessions_per_week)) {
    return blocker('sessions_per_week_unanswered', '/onboarding');
  }
  if (unanswered(profile.available_weekdays)) {
    return blocker('available_weekdays_unanswered', '/onboarding');
  }
  if (profile.available_weekdays === 0) return blocker('no_available_days', '/profile');
  return null;
}

/**
 * `null`, or absent altogether.
 *
 * Every field of `ProfileResponse` is required on the wire, so `undefined` should be
 * unreachable — but the two readings of an absent field are "unanswered" and "answered", and
 * only the first is safe: the second sends a profile the generator cannot use to the endpoint
 * and, downstream of that, reads `injuries` off a body that has none. Erring towards a notice
 * costs one sentence; erring the other way replaced the whole route with an error boundary in
 * `routeGuard.test.tsx`, whose fetch mock answers every request with a token payload.
 */
function unanswered(value: number | string | null | undefined): boolean {
  return value === null || value === undefined;
}

export function canPreview(profile: Profile | undefined): boolean {
  return profile !== undefined && previewBlocker(profile) === null;
}

/**
 * Everything the answer depends on, and nothing else — the query key.
 *
 * A profile change therefore yields a NEW key and a new fetch with no invalidation wiring, going
 * back to the screen is a cache hit, and `staleTime: Infinity` is correct rather than a
 * staleness bet: the same inputs against the same deploy cannot produce a different plan
 * (`server/models.py::Plan` promises exactly that, and the deploy pins the library).
 *
 * ⚠️ An injury's `note` and `started_on` are deliberately OUT. The planner reads open injury
 * *keys* and nothing else, so editing a note must not throw away a 32-week plan and pay for
 * another one. Ids, sorted, so the order the endpoint happened to return them in cannot fork the
 * key.
 */
export interface PreviewKeyParts {
  start_date: string;
  discipline: string | null;
  target_grade_id: number | null;
  current_grade_id: number | null;
  sessions_per_week: number | null;
  available_weekdays: number | null;
  strength_aspect_id: number | null;
  weakness_aspect_id: number | null;
  open_injuries: string;
}

export function previewKeyParts(profile: Profile, startDate: string): PreviewKeyParts {
  return {
    start_date: startDate,
    discipline: profile.primary_discipline,
    target_grade_id: profile.target_grade_id,
    current_grade_id: profile.current_grade_id,
    sessions_per_week: profile.sessions_per_week,
    available_weekdays: profile.available_weekdays,
    strength_aspect_id: profile.strength_aspect_id,
    weakness_aspect_id: profile.weakness_aspect_id,
    open_injuries: profile.injuries
      .map((injury) => injury.injury_area_id)
      .sort((a, b) => a - b)
      .join(','),
  };
}

/**
 * The Monday on or after `now`, as `YYYY-MM-DD` in the browser's own timezone.
 *
 * The client owns this because the domain has no clock and the server has no timezone: whatever
 * is sent is normalised to the Monday on or after it, so a local Monday round-trips unchanged.
 * Built from local date parts rather than `toISOString()`, which would shift the day by the
 * UTC offset and hand a Sunday to a planner that refuses anything but a Monday.
 */
export function nextMonday(now: Date): string {
  const shift = (8 - now.getDay()) % 7;
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + shift);
  const month = String(monday.getMonth() + 1).padStart(2, '0');
  const day = String(monday.getDate()).padStart(2, '0');
  return `${String(monday.getFullYear())}-${month}-${day}`;
}

/**
 * `exercise_key -> exercise`, built ONCE for the screen.
 *
 * A block names a key, not an id (the domain is DB-free and speaks keys), so the join happens
 * here against the library the app has already fetched. **Built once and passed down**: the
 * worst-case plan is 224 sessions and 672 blocks, and rebuilding an 85-entry index per row is
 * the one thing on this screen that would be quadratic.
 *
 * An unknown key is simply absent — `namesOf`'s rule, and for the same reason: the only way to
 * reach one is a plan generated against a library newer than the client's. What `exerciseLabel`
 * does with that absence is a separate decision; see it.
 */
export function exercisesByKey(
  exercises: readonly LibraryExercise[],
): ReadonlyMap<string, LibraryExercise> {
  return new Map(exercises.map((exercise) => [exercise.key, exercise]));
}

/**
 * What to call a block's exercise.
 *
 * ⚠️ **Deliberately NOT `namesOf`'s drop.** An equipment id with no vocabulary row renders as a
 * bare integer, which tells the reader nothing, so dropping it is right. A key does not: it is
 * authored English, and `weighted_max_hangs` humanises to something a climber can act on. So a
 * block whose exercise this client has never heard of is still shown, with its prescribed sets,
 * under a slightly plainer name — hiding prescribed work would be the worse failure.
 */
export function exerciseLabel(key: string, index: ReadonlyMap<string, LibraryExercise>): string {
  return index.get(key)?.name ?? humanise(key);
}

/** Monday first, matching `available_weekdays` bit 0 and `planned_session.weekday`. */
const WEEKDAY_NAMES = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
] as const;

export function weekdayName(weekday: number): string {
  return WEEKDAY_NAMES[weekday] ?? 'Unscheduled';
}

export const MONTH_NAMES = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const;

/**
 * `2026-08-31` -> `31 Aug 2026`, from the string's own parts.
 *
 * ⚠️ Not `new Date(iso).toLocaleDateString()`: a date-only string parses as UTC midnight, which
 * renders as the PREVIOUS day everywhere west of Greenwich. A plan whose first week starts on
 * Sunday is not a rendering nit — every session on the screen is then a day out.
 */
export function formatDay(iso: string): string {
  const [year, month, day] = iso.split('-');
  const name = month === undefined ? undefined : MONTH_NAMES[Number(month) - 1];
  if (year === undefined || day === undefined || name === undefined) return iso;
  return `${String(Number(day))} ${name} ${year}`;
}

/** A session's shape at a glance, for the disclosure summary. */
export function sessionSummary(session: PlanSession): string {
  const terms: string[] = [];
  const blocks = session.blocks.length;

  if (blocks === 0) {
    // The Recovery slot: zero blocks, and it carries a shortfall saying why. "0 blocks" would
    // read as a data fault; the invariant is that no empty session is UNEXPLAINED, not that
    // none exists.
    terms.push('nothing prescribed');
  } else {
    const sets = session.blocks.reduce((total, block) => total + block.sets.length, 0);
    terms.push(`${String(blocks)} ${blocks === 1 ? 'block' : 'blocks'}`);
    terms.push(`${String(sets)} ${sets === 1 ? 'set' : 'sets'}`);
  }
  // `null` for a session that prescribes nothing — no estimate, rather than an estimate of the
  // warm-up alone.
  if (session.estimated_minutes !== null) terms.push(`~${String(session.estimated_minutes)} min`);

  return terms.join(' · ');
}

/**
 * One block's prescription as a line, reusing `prescriptionLine`'s null-omission rule.
 *
 * ⚠️ **One line per BLOCK, not a row per set, and that is a measured decision.** In v1.0.0 every
 * set in a block is the same row of `prescription_template` with a different `set_index`, so a
 * row each would repeat itself — and the worst-case plan holds **2,421** of them. Reading the
 * first set and the count says exactly as much for a fraction of the DOM. The day sets stop
 * being identical (a per-set progression), this is the function that has to change.
 *
 * `phase` is the microcycle's, and it is here only because `Prescription` carries one;
 * `prescriptionLine` never reads it.
 */
export function setsLine(block: PlanBlock, phase: Phase): string {
  const first = block.sets[0];
  if (first === undefined) return '';

  const prescription: Prescription = {
    phase,
    sets: block.sets.length,
    reps: first.target_reps,
    work_seconds: first.target_work_seconds,
    rest_seconds: first.target_rest_seconds,
    rest_between_sets_seconds: block.rest_between_sets_seconds,
    intensity_pct: first.target_intensity_pct,
    target_rpe: first.target_rpe,
  };
  return prescriptionLine(prescription);
}
