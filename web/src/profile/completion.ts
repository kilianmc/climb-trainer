import type { Profile } from '../api/types';

/**
 * How complete a profile is, and which of the four steps are still open.
 *
 * ## The bar opens at 20%, and the number is not decoration
 *
 * **Endowed progress** (Nunes & Drèze 2006): a 10-stamp card with 2 pre-filled is
 * completed at roughly twice the rate of an 8-stamp card, for identical real work.
 * Starting from zero is the hardest step there is.
 *
 * The floor was 29% and is now **20%** (Kilian, issue #54): the same mechanic, read as
 * less manipulative. The formula is `20 + 80 × steps_done / total_steps`, which with four
 * steps is 20/40/60/80/100 — no rounding, and each step is worth the same.
 *
 * **The credit has to be TRUE, which is the rule that governs the whole mechanic.** The
 * floor stands for facts we actually know by the time this screen renders — the account
 * exists, and the email that identifies it is on file — and nothing else is ever
 * pre-credited.
 *
 * ## Why each step's "done" test is the one it is
 *
 * All of them read server state, and all of them are unambiguous — which is only true
 * since revision `0005` made the profile able to say "not answered":
 *
 * - **availability needs BOTH `sessions_per_week` and `available_weekdays`.** They are one
 *   step and are written together, and either alone is a half-answered question.
 * - **aspects = the current grade AND both aspect picks.** `0006` gave all three real
 *   columns, so this is server truth like the rest. It is deliberately NOT "at least one
 *   rating": since #54 the eight sliders are optional detail behind a disclosure, and a row
 *   written from an untouched default would credit a step nobody answered.
 * - **injuries = its `injuries_reviewed_at` timestamp is set**, never a row count.
 *   "Nothing is hurting" is an honest answer that writes ZERO rows, so a row count cannot
 *   tell "answered, nothing" from "never asked". ⚠️ A step needs a `*_reviewed_at` column
 *   exactly when zero rows is a legitimate answer, and this is now the only such step.
 * - **⚠️ There is no equipment step.** Issue #54 inverted the model: the user is assumed
 *   to have access to everything, and what they LACK is flagged on the exercise that needs
 *   it. `equipment_reviewed_at` is left on the server and read by nobody here.
 *
 * ## The bar reports PERSISTED state, and nothing else
 *
 * Every input comes from `GET`/`PATCH /api/profile`. The query cache holds **server
 * responses only**; an in-flight write shows up as a render-time overlay derived from the
 * pending mutation's own variables, so the bar moves on the click (CLAUDE.md's Tier-1 rule)
 * and a failure needs no rollback — the overlay simply stops applying. See `api.ts` for the
 * three bugs that got us here, and for why the final step is the one that waits.
 *
 */

/**
 * The four steps, in the order onboarding asks them.
 *
 * **The order is deliberate and is the plan's goal-gradient point**: the highest-friction
 * step sits in the MIDDLE and the last step is trivial. Never let the final step be the one
 * that stalls people. Step 1 is the target grade because it is the user's own freely-chosen
 * goal, which every later screen refers back to — including the current grade, which is
 * asked on the same scale.
 */
export const ONBOARDING_STEPS = ['targetGrade', 'availability', 'aspects', 'injuries'] as const;

export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];

/**
 * Card headings, the rail's accessible names, and the live-region announcement.
 *
 * ⚠️ `STEP_BAR_LABELS` lived beside this and is gone with the step LIST it was written for
 * (round 10). The rail draws digits, so it has no label width to save — and a screen reader is
 * better served by "Step 3: Where you are now" than by "Step 3: Current".
 */
export const STEP_TITLES: Record<OnboardingStep, string> = {
  targetGrade: 'Your goal',
  availability: 'Availability',
  aspects: 'Where you are now',
  injuries: 'Injuries',
};

/** The endowed floor, in percent. Credited for the account and the email on file. */
export const ENDOWED_FLOOR_PERCENT = 20;

export type StepCompletion = Record<OnboardingStep, boolean>;

export function stepCompletion(profile: Profile): StepCompletion {
  return {
    targetGrade: profile.target_grade_id !== null,
    availability: profile.sessions_per_week !== null && profile.available_weekdays !== null,
    // All three, because all three are the step's question — a current grade, a strength and
    // a weakness. The eight `aspect_ratings` ride along with them but are no longer the test:
    // they are optional detail now (see `UserAspectRating`'s docstring), and an untouched
    // slider left at the default would credit a step nobody answered.
    aspects:
      profile.current_grade_id !== null &&
      profile.strength_aspect_id !== null &&
      profile.weakness_aspect_id !== null,
    injuries: profile.injuries_reviewed_at !== null,
  };
}

export function remainingSteps(completion: StepCompletion): OnboardingStep[] {
  return ONBOARDING_STEPS.filter((step) => !completion[step]);
}

export function completedStepCount(completion: StepCompletion): number {
  return ONBOARDING_STEPS.length - remainingSteps(completion).length;
}

/** 0-100: the endowed floor, plus the rest shared equally between the steps. */
export function completionPercent(completion: StepCompletion): number {
  const done = completedStepCount(completion);
  const earned = (100 - ENDOWED_FLOOR_PERCENT) * (done / ONBOARDING_STEPS.length);
  return Math.round(ENDOWED_FLOOR_PERCENT + earned);
}
