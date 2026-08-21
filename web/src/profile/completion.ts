import type { Profile } from '../api/types';

/**
 * How complete a profile is, and which of the five steps are still open.
 *
 * ## The bar opens at ~29%, and the number is not decoration
 *
 * **Endowed progress** (Nunes & Drèze 2006): a 10-stamp card with 2 pre-filled is
 * completed at roughly twice the rate of an 8-stamp card, for identical real work.
 * Starting from zero is the hardest step there is. Kilian's call for this app: open at
 * **~25-30%**, never 0%, and reach **100%** when the five steps are done.
 *
 * **The credit has to be TRUE, which is the rule that governs the whole mechanic.** So
 * the two pre-filled units are two facts we actually know by the time this screen renders
 * — the account exists, and the email that identifies it is on file. Seven units, two
 * credited, five steps: `round(100 * 2/7)` = **29%**, and each step is worth ~14 points.
 *
 * (The plan words the second fact as "the display name is known". There is no
 * `display_name` column and this PR does not add one — see the report on PR #9 — so the
 * registered email address stands in for it. Same class of fact: something the user
 * already told us.)
 *
 * ## Why each step's "done" test is the one it is
 *
 * **All five read server state, and all five are unambiguous** — which is only true since
 * revision `0005` made the profile able to say "not answered":
 *
 * - **availability needs BOTH `sessions_per_week` and `available_weekdays`.** They are one
 *   step and are written together, and either alone is a half-answered question. Before
 *   `0005` these columns were `NOT NULL`, so the row carried a placeholder `3` that was
 *   indistinguishable from a real answer and the test had to be "the weekday mask is not
 *   zero" — which credited the step while the database still asserted three sessions a week
 *   nobody had asked for.
 * - **aspects = at least one rating**, not all eight. The step submits all eight together,
 *   so in practice they are the same test — and if a ninth aspect is ever seeded, an
 *   "all rated" test would silently un-complete every existing profile.
 * - **equipment and injuries = their `*_reviewed_at` timestamp is set**, never a row count.
 *   Both have an honest answer that writes ZERO rows — "I own none of this" and "nothing is
 *   hurting" — so a row count cannot tell "answered, nothing" from "never asked". Counting
 *   rows made the equipment step a **hard dead-end for an outdoor-only climber**: every one
 *   of the fifteen rows seeded at the time was a wall or a piece of kit, so there was nothing
 *   they could honestly tick, the Continue button stayed disabled and 100% was unreachable.
 *   `0005` added both columns and the vocabulary gained `outdoor_boulders` /
 *   `outdoor_routes`; the server stamps them whenever the step is submitted, with or without
 *   rows. (PR #9 first shipped a device-local `localStorage` flag for the injuries
 *   half, which could only ever understate; the column replaced it and the file is gone.)
 *
 * ## The bar reports PERSISTED state, and nothing else
 *
 * Every input comes from `GET`/`PATCH /api/profile`. The query cache holds **server
 * responses only**; an in-flight write shows up as a render-time overlay derived from the
 * pending mutation's own variables, so the bar moves on the click (CLAUDE.md's Tier-1 rule)
 * and a failure needs no rollback — the overlay simply stops applying. Nothing local is ever
 * written into the cache, which is what makes "the bar reports persisted state" true rather
 * than nearly true. See `api.ts` for the three bugs that got us here, and for why the final
 * step is the one that waits: a failed final write that still moved the bar to 100% is not a
 * cosmetic bug, it is the plan generator prescribing crimp work on an injured elbow the
 * server never heard about.
 */

/**
 * The five steps, in the order onboarding asks them.
 *
 * **The order is deliberate and is the plan's goal-gradient point**: the
 * highest-friction step (the eight self-ratings) sits in the MIDDLE, and the last step is
 * trivial. Never let the final step be the one that stalls people. Step 1 is the target
 * grade because it is the user's own freely-chosen goal, which every later screen refers
 * back to.
 */
export const ONBOARDING_STEPS = [
  'targetGrade',
  'availability',
  'equipment',
  'aspects',
  'injuries',
] as const;

export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];

/** Short titles, for the stepper and for the live-region announcement. */
export const STEP_TITLES: Record<OnboardingStep, string> = {
  targetGrade: 'Target grade',
  availability: 'Availability',
  equipment: 'What you train on',
  aspects: 'Self-rating',
  injuries: 'Injuries',
};

/** Credited before the user answers anything: the account, and the email on file. */
export const CREDITED_ON_SIGN_UP = 2;

export const TOTAL_UNITS = CREDITED_ON_SIGN_UP + ONBOARDING_STEPS.length;

export type StepCompletion = Record<OnboardingStep, boolean>;

export function stepCompletion(profile: Profile): StepCompletion {
  return {
    targetGrade: profile.target_grade_id !== null,
    availability: profile.sessions_per_week !== null && profile.available_weekdays !== null,
    equipment: profile.equipment_reviewed_at !== null,
    aspects: profile.aspect_ratings.length > 0,
    injuries: profile.injuries_reviewed_at !== null,
  };
}

export function remainingSteps(completion: StepCompletion): OnboardingStep[] {
  return ONBOARDING_STEPS.filter((step) => !completion[step]);
}

export function completedStepCount(completion: StepCompletion): number {
  return ONBOARDING_STEPS.length - remainingSteps(completion).length;
}

/** 0-100, rounded, floored at the endowed credit and reaching exactly 100 when done. */
export function completionPercent(completion: StepCompletion): number {
  const credited = CREDITED_ON_SIGN_UP + completedStepCount(completion);
  return Math.round((100 * credited) / TOTAL_UNITS);
}
