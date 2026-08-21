import type { Profile, ProfilePatch, Vocabulary } from '../api/types';
import { ONBOARDING_STEPS, type OnboardingStep } from './completion';

/**
 * The editable copy of a profile, and the one place a step turns into a request body.
 *
 * Two reasons this is not just `Profile` with setters:
 *
 * 1. **The wire shape is not the editable shape.** `aspect_ratings` is a list of rows with
 *    a `rated_at` the client does not own; editing eight sliders wants a map. Same for the
 *    injury notes.
 * 2. **`patchFor` is the whole persistence contract, and it is pure.** Onboarding sends
 *    ONE step per request and `ProfilePatchRequest` is `extra="forbid"`, so an extra key is
 *    a 422 rather than a field the server ignores — exactly the mistake `/login` made once
 *    by forwarding a form object whole. Keeping the mapping in a pure function means it is
 *    tested without a DOM, a router or a fetch mock (`draft.test.ts`).
 *
 * `gradeSystemId` is UI-only and is never sent: which scale the picker shows is a display
 * preference, and the profile's discipline is DERIVED server-side from the chosen grade.
 */
export interface ProfileDraft {
  /** Which grade scale the picker is showing. Not part of the profile. */
  gradeSystemId: number | null;
  targetGradeId: number | null;
  /**
   * ⚠️ **Nullable, and it must stay nullable.** `0005` exists to stop the SERVER inventing
   * `sessions_per_week = 3`; a draft that opened on 3 put the same placeholder back from the
   * client, and `patchFor` would have sent it the moment the user ticked one weekday — into
   * the column whose docstring tells PR #11's generator it may trust the value. The select
   * opens on "Choose", exactly as the grade picker does.
   */
  sessionsPerWeek: number | null;
  /** 7-bit mask, Monday = bit 0. `0` means nothing picked yet in this draft. */
  availableWeekdays: number;
  equipmentIds: number[];
  /** Climbing-aspect id -> 1-5. Every seeded aspect has an entry. */
  aspectScores: Record<number, number>;
  /** Injury-area id -> note. **Presence is the flag**; the note may be empty. */
  injuries: Record<number, string>;
}

/**
 * Where the self-rating sliders start.
 *
 * ⚠️ **An accepted default IS a recorded answer.** Submitting this step writes all eight
 * scores, so a user who reads the sliders and clicks Continue persists eight 3s — that is
 * the intended behaviour (eight visible controls plus a deliberate click is a real answer,
 * and requiring interaction would be a strange gate for a genuinely middling climber), but
 * it is not "no answer", and the UI says so on the step rather than letting the number look
 * like a placeholder. `user_aspect_rating.rated_at` timestamps it either way.
 */
export const DEFAULT_ASPECT_SCORE = 3;

const NO_WEEKDAYS = 0;

export function draftFrom(profile: Profile, vocabulary: Vocabulary): ProfileDraft {
  const targetGrade = vocabulary.grades.find((grade) => grade.id === profile.target_grade_id);

  const aspectScores: Record<number, number> = {};
  for (const aspect of vocabulary.climbing_aspects) aspectScores[aspect.id] = DEFAULT_ASPECT_SCORE;
  for (const rating of profile.aspect_ratings)
    aspectScores[rating.climbing_aspect_id] = rating.score;

  const injuries: Record<number, string> = {};
  for (const injury of profile.injuries) injuries[injury.injury_area_id] = injury.note ?? '';

  return {
    gradeSystemId: targetGrade?.grade_system_id ?? vocabulary.grade_systems[0]?.id ?? null,
    targetGradeId: profile.target_grade_id,
    // Straight through, NULL included: "not answered" has to survive into the form.
    sessionsPerWeek: profile.sessions_per_week,
    availableWeekdays: profile.available_weekdays ?? NO_WEEKDAYS,
    equipmentIds: [...profile.equipment_ids],
    aspectScores,
    injuries,
  };
}

/**
 * Whether a step has an answer worth sending.
 *
 * **Only two steps can lack one**, and both are scalars that cannot be inferred: a target
 * grade, and a training frequency. Their controls open with nothing chosen, so the button
 * waits for the user.
 *
 * ⚠️ **The other three are NEVER blocked, and blocking equipment was a hard dead-end.** An
 * outdoor-only climber owned none of the fifteen items seeded at the time, so there was
 * nothing they could honestly tick and Continue never enabled — 100% unreachable, dashboard
 * nagging forever, for someone who had answered correctly. (The list has since grown two
 * outdoor rows as well; both halves were needed.) An empty answer is recordable now: the
 * server stamps `equipment_reviewed_at` / `injuries_reviewed_at` when the step is
 * submitted, with or without rows. "The answer cannot be stored" is a schema problem and
 * gets a schema fix; it is never a reason to disable a button.
 *
 * This is a **guard on the button**, not validation — the server accepts every one of
 * these bodies.
 */
export function canSubmit(step: OnboardingStep, draft: ProfileDraft): boolean {
  switch (step) {
    case 'targetGrade':
      return draft.targetGradeId !== null;
    case 'availability':
      // BOTH halves. The frequency select opens on nothing chosen for the same reason the
      // grade picker does: 0005 stopped the server inventing `sessions_per_week = 3`, and a
      // pre-selected control would put that placeholder straight back, client-side.
      return draft.sessionsPerWeek !== null && draft.availableWeekdays !== NO_WEEKDAYS;
    case 'equipment':
    case 'aspects':
    case 'injuries':
      return true;
  }
}

/**
 * The request body for one step — and **only** the fields that step owns.
 *
 * An unanswerable step returns `{}`, which is a legal no-op body rather than a special
 * case the caller has to remember: the only way to reach it is a target-grade step
 * submitted with no grade, which the form does not allow.
 */
export function patchFor(step: OnboardingStep, draft: ProfileDraft): ProfilePatch {
  switch (step) {
    case 'targetGrade':
      return draft.targetGradeId === null ? {} : { target_grade_id: draft.targetGradeId };
    case 'availability':
      // Both halves or neither. Sending a weekday mask with no frequency would leave the
      // step half-answered, which `completion.ts` correctly refuses to credit.
      return draft.sessionsPerWeek === null
        ? {}
        : {
            sessions_per_week: draft.sessionsPerWeek,
            available_weekdays: draft.availableWeekdays,
          };
    case 'equipment':
      return { equipment_ids: [...draft.equipmentIds].sort((a, b) => a - b) };
    case 'aspects':
      return {
        aspect_ratings: Object.entries(draft.aspectScores).map(([aspectId, score]) => ({
          climbing_aspect_id: Number(aspectId),
          score,
        })),
      };
    case 'injuries':
      return {
        injuries: Object.entries(draft.injuries).map(([areaId, note]) => ({
          injury_area_id: Number(areaId),
          // ALWAYS sent, and `null` when empty. The server treats an omitted `note` as
          // "leave what is stored" and an explicit `null` as "clear it" — this screen owns
          // the whole field, so it always states the value rather than omitting it.
          note: note.trim() === '' ? null : note.trim(),
        })),
      };
  }
}

/**
 * Which step a patch came from — the inverse of `patchFor`, and the reason it exists.
 *
 * A failure has to be reported against the step that produced it, and by the time it is
 * reported the user has usually moved on: naming the step from a captured closure pointed
 * at whatever was on screen when the message rendered, not at what failed. The mutation
 * hands its variables back (`ProfilePatchHandlers`), so the patch itself is the answer.
 *
 * Keyed on the fields each step owns, which `draft.test.ts` pins in both directions — a
 * step whose key set changed in `patchFor` and not here would misattribute every failure.
 *
 * ⚠️ **`show_body_metrics` belongs to no step**, so a patch carrying only that field returns
 * `null` and a failure would be reported with no step named and therefore no message. No
 * screen sends one today (it is deliberately absent from both entry points — see
 * `routes/_authed/profile.lazy.tsx`). Whoever adds that control has to decide where it
 * belongs here first.
 */
export function stepOf(patch: ProfilePatch): OnboardingStep | null {
  const owns: Record<OnboardingStep, boolean> = {
    targetGrade: patch.target_grade_id !== undefined,
    availability: patch.sessions_per_week !== undefined || patch.available_weekdays !== undefined,
    equipment: patch.equipment_ids !== undefined,
    aspects: patch.aspect_ratings !== undefined,
    injuries: patch.injuries !== undefined,
  };
  return ONBOARDING_STEPS.find((step) => owns[step]) ?? null;
}
