import type { Profile, ProfilePatch, Vocabulary } from '../api/types';
import { ONBOARDING_STEPS, type OnboardingStep } from './completion';

/**
 * The editable copy of a profile, and the one place a step turns into a request body.
 *
 * Two reasons this is not just `Profile` with setters:
 *
 * 1. **The wire shape is not the editable shape.** `aspect_ratings` is a list of rows with
 *    a `rated_at` the client does not own; editing a row of sliders wants a map. Same for the
 *    injury notes.
 * 2. **`patchFor` is the whole persistence contract, and it is pure.** `ProfilePatchRequest`
 *    is `extra="forbid"`, so an extra key is a 422 rather than a field the server ignores —
 *    exactly the mistake `/login` made once by forwarding a form object whole. Keeping the
 *    mapping in a pure function means it is tested without a DOM, a router or a fetch mock.
 *
 * `gradeSystemId` is UI-only and is never sent: which scale the picker shows is a display
 * preference, and the profile's discipline is DERIVED server-side from the chosen grade.
 */
export interface ProfileDraft {
  /** Which grade scale both pickers show. Not part of the profile. */
  gradeSystemId: number | null;
  targetGradeId: number | null;
  /**
   * What they climb now. Locked to the same scale as the target by the UI, and to the same
   * DISCIPLINE by the API — `server/profile/routes.py::_decide_grades` refuses a mismatch,
   * and clears this column itself when a new target moves to the other ladder.
   */
  currentGradeId: number | null;
  /** One strength and one weakness, from the aspect vocabulary. Must differ (the API checks). */
  strengthAspectId: number | null;
  weaknessAspectId: number | null;
  /**
   * The account's display name. ⚠️ It belongs to NO step — `patchFor` never sends it, and
   * `accountPatch` is what the editor's Save uses. See `stepOf`.
   */
  displayName: string | null;
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
  /**
   * "Any day" — the DEFAULT answer to the weekday question (Kilian, round 5), and the exact
   * counterpart of `noInjuries`.
   *
   * ⚠️ **No new column.** `available_weekdays` is a mask, so "all of them" is expressible in it:
   * ticked, this sends `ALL_WEEKDAYS` (127). It is not a placeholder either — `0005` exists to
   * stop the server inventing a frequency, and this is the user's own answer, pre-selected and
   * visible, with the step's help text explaining what it means.
   *
   * Mutually exclusive with naming days but **not destructive**: the mask above is left as it is
   * and simply not sent, so un-ticking brings back exactly what was chosen.
   */
  allWeekdays: boolean;
  /** Climbing-aspect id -> 1-5. Every seeded aspect has an entry. */
  aspectScores: Record<number, number>;
  /** Injury-area id -> note. **Presence is the flag**; the note may be empty. */
  injuries: Record<number, string>;
  /**
   * "Nothing is hurting" — a tickable answer rather than an empty list, and **ticked by
   * default** (Kilian, rounds 2 and 3).
   *
   * ⚠️ **No new column, and none is needed**: `injuries_reviewed_at` is exactly the column
   * that exists because zero rows is a legitimate answer, so this ticked and submitted is a
   * `PATCH` of `injuries: []`, which is what stamps it. Reading it back is the same fact
   * inverted — reviewed, and no rows — which `draftFrom` does.
   *
   * ⚠️ **The default tick is not itself an answer, and nothing here makes it one.** It is a
   * pre-filled control, and the bar only ever credits what `patchFor` actually sent — which
   * happens for a step the user has been on and moved off. See `steps.tsx::InjuryFields`.
   *
   * It is mutually exclusive with a listed injury but **does not discard one**: the map above
   * is left exactly as it was and simply not sent, so un-ticking brings back what was typed.
   */
  noInjuries: boolean;
}

/**
 * Where the sliders sit until something says otherwise, and what the two picks write.
 *
 * ⚠️ Since issue #54 the sliders are behind a disclosure and are **no longer the step's
 * question** — one strength and one weakness are. Picking one writes that aspect's score
 * (`ClimbingNowFields`), so the picks reach the server as ratings even though their own
 * columns do not exist yet; the disclosure can then still move any slider, and whatever it
 * is left at is what is saved.
 */
export const DEFAULT_ASPECT_SCORE = 3;
export const STRENGTH_SCORE = 5;
export const WEAKNESS_SCORE = 1;

const NO_WEEKDAYS = 0;
/** All seven bits. "Any day" as the mask actually stores it. */
const ALL_WEEKDAYS = 0b111_1111;

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
    currentGradeId: profile.current_grade_id,
    strengthAspectId: profile.strength_aspect_id,
    weaknessAspectId: profile.weakness_aspect_id,
    displayName: profile.display_name,
    // Straight through, NULL included: "not answered" has to survive into the form.
    sessionsPerWeek: profile.sessions_per_week,
    availableWeekdays: profile.available_weekdays ?? NO_WEEKDAYS,
    // Unanswered means the default is offered; a stored 127 means it was chosen. Anything else
    // is a real list of days, and the disclosure opens on it.
    allWeekdays: profile.available_weekdays === null || profile.available_weekdays === ALL_WEEKDAYS,
    aspectScores,
    injuries,
    // No rows means the tick, whether or not the step has been reviewed: it is the DEFAULT
    // answer now, not a readout of one. What separates "answered" from "never asked" is still
    // `injuries_reviewed_at`, and `completion.ts` is the only thing that reads it.
    noInjuries: profile.injuries.length === 0,
  };
}

/**
 * Whether a step has an answer worth sending.
 *
 * **Every step can lack one**: a target grade, a training frequency, the pair of aspect
 * picks that replaced the self-rating (#54), and — since round 2 — an injuries step that has
 * neither an injury listed nor "none" ticked. All of them are answerable by anyone, which is
 * the test that matters.
 *
 * ⚠️ **"The answer cannot be stored" is never a reason to disable a control**, and the
 * injuries step is the case that proves the difference. The equipment step once required at
 * least one tick out of fifteen indoor rows, so an outdoor-only climber could never enable
 * Continue: 100% unreachable, dashboard nagging forever, for someone who had answered
 * correctly. That was a schema problem and it got a schema fix. "Nothing is hurting" is the
 * opposite case — it IS storable, via `injuries_reviewed_at` — so asking for it explicitly
 * costs one tick and buys a user who can tell an answered step from a skipped one.
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
      // pre-selected control would put that placeholder straight back, client-side. The weekday
      // half is answered by "any day" or by naming days — the one state that is not an answer is
      // "any day" un-ticked with nothing named.
      return (
        draft.sessionsPerWeek !== null &&
        (draft.allWeekdays || draft.availableWeekdays !== NO_WEEKDAYS)
      );
    case 'aspects':
      // Every climber has a relative strength and a relative weakness, and the sliders are
      // behind a disclosure now — so a row of untouched 3s is not an answer to this step.
      return (
        draft.currentGradeId !== null &&
        draft.strengthAspectId !== null &&
        draft.weaknessAspectId !== null
      );
    case 'injuries':
      // One tick either way. An empty form is now "not answered yet" rather than "nothing
      // is hurting", which is the ambiguity the None row exists to remove.
      return draft.noInjuries || Object.keys(draft.injuries).length > 0;
  }
}

/**
 * The request body for one step — and **only** the fields that step owns.
 *
 * ⚠️ **`display_name` is never here.** It belongs to no step, so the editor composes it
 * separately with `accountPatch` — a display name is not an answer to an onboarding question
 * and must never move the completion bar.
 *
 * An unanswerable step returns `{}`, which is a legal no-op body rather than a special case
 * the caller has to remember.
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
            // "Any day" wins over whatever is in the mask, and sends all seven bits. The mask is
            // not cleared — see `allWeekdays`.
            available_weekdays: draft.allWeekdays ? ALL_WEEKDAYS : draft.availableWeekdays,
          };
    case 'aspects':
      // Three answers and every score, in one body. The scores ride along because
      // picking a strength or a weakness writes that aspect's score too — see
      // `UserAspectRating`'s docstring for why both exist.
      return draft.currentGradeId === null ||
        draft.strengthAspectId === null ||
        draft.weaknessAspectId === null
        ? {}
        : {
            current_grade_id: draft.currentGradeId,
            strength_aspect_id: draft.strengthAspectId,
            weakness_aspect_id: draft.weaknessAspectId,
            aspect_ratings: Object.entries(draft.aspectScores).map(([aspectId, score]) => ({
              climbing_aspect_id: Number(aspectId),
              score,
            })),
          };
    case 'injuries':
      // "None" wins over whatever is in the map, and sends the empty list that stamps
      // `injuries_reviewed_at`. The map is not cleared — see `noInjuries`.
      if (draft.noInjuries) return { injuries: [] };
      // Neither answer given: send nothing at all. `injuries: []` here would stamp the step
      // as reviewed for a user who never looked at it, and the bar would credit it.
      if (Object.keys(draft.injuries).length === 0) return {};
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
 * The Account section's own field. It belongs to no step, so it is composed separately.
 *
 * ⚠️ Returns `{}` rather than `{display_name: null}` when there is nothing to say: `null`
 * means "no change" on this endpoint, and `DisplayName` refuses `''`, so there is no spelling
 * of "clear my display name" here. `POST /api/profile/reset` does not clear it either — it is
 * not one of the four steps. That is deliberate; see `server/fields.py::DisplayName`.
 */
export function accountPatch(draft: ProfileDraft): ProfilePatch {
  const name = draft.displayName?.trim() ?? '';
  return name === '' ? {} : { display_name: name };
}

/**
 * Several steps' fields in one body — the editor's single Save (issue #54).
 *
 * ⚠️ **Only the steps named**, and the editor names the ones it actually showed. Folding in
 * every step would stamp `injuries_reviewed_at` and write a default rating per aspect for someone
 * who opened the editor to change their target grade, and the bar would credit two steps
 * they never saw. The bar may only report answers a user gave.
 */
export function patchForAll(draft: ProfileDraft, steps: readonly OnboardingStep[]): ProfilePatch {
  return steps.reduce<ProfilePatch>((body, step) => ({ ...body, ...patchFor(step, draft) }), {});
}

/**
 * Which step a patch came from — the inverse of `patchFor`, and the reason it exists.
 *
 * A failure has to be reported against the step that produced it, and by the time it is
 * reported the user has usually moved on: naming the step from a captured closure pointed
 * at whatever was on screen when the message rendered, not at what failed. The mutation
 * hands its variables back (`ProfilePatchHandlers`), so the patch itself is the answer.
 *
 * ⚠️ Returns the FIRST step a patch touches, so the editor's combined body reports as step
 * one. That is acceptable only because the editor now saves once, at the end, and shows the
 * failure on the card the user is standing on.
 *
 * ⚠️ **`show_body_metrics` and `display_name` belong to no step**, so a patch carrying only
 * one of them returns `null` and a failure would be reported with no step named and
 * therefore no message. The editor's Account section sends `display_name` and reports its own
 * failure; whoever adds a `show_body_metrics` control has to decide where it belongs here.
 */
export function stepOf(patch: ProfilePatch): OnboardingStep | null {
  const owns: Record<OnboardingStep, boolean> = {
    targetGrade: patch.target_grade_id !== undefined,
    availability: patch.sessions_per_week !== undefined || patch.available_weekdays !== undefined,
    aspects:
      patch.aspect_ratings !== undefined ||
      patch.current_grade_id !== undefined ||
      patch.strength_aspect_id !== undefined ||
      patch.weakness_aspect_id !== undefined,
    injuries: patch.injuries !== undefined,
  };
  return ONBOARDING_STEPS.find((step) => owns[step]) ?? null;
}
