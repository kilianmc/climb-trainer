import { describe, expect, it } from 'vitest';

import type { Profile } from '../api/types';
import {
  ENDOWED_FLOOR_PERCENT,
  ONBOARDING_STEPS,
  completedStepCount,
  completionPercent,
  remainingSteps,
  stepCompletion,
} from './completion';

/**
 * The completion arithmetic, which is the one part of this feature that is a rule rather
 * than a render. Three properties are Kilian's explicit requirements and each of them is
 * the kind of thing that breaks silently in a refactor:
 *
 * - the bar **opens at the endowed floor and never at 0%** (endowed progress);
 * - it reaches **exactly 100%** when the four steps are done;
 * - it **never overstates** — no combination of answers may credit a step that has none.
 *
 * The last one is why the empty-profile case is asserted field by field rather than only
 * as a number: a placeholder read as an answer is the failure mode, and it would show up
 * as a number nobody earned on a profile nobody has touched.
 *
 * ⚠️ **The floor moved from 29% (2 of 7 units) to 20%, and the step count from five to
 * four** (issue #54). The three numbers that changed are the floor, the step list and the
 * ladder; the reasoning that produced them did not, so the shape of this file did not
 * change either.
 */

/**
 * A brand-new account: the row exists, the email is on file, and nothing has been asked.
 *
 * ⚠️ `sessions_per_week` is NULL, not a placeholder. Revision 0005 exists so this column
 * can say "not answered"; before it, a fresh row carried a plausible 3 and no reader could
 * tell the difference.
 *
 * ⚠️ **There are no `equipment_ids` and no `equipment_reviewed_at` here, and their absence
 * is checked by the compiler**: `0006` took both off `ProfileResponse`. Issue #54 inverted
 * the model — the user is assumed to have access to everything and flags what they LACK on
 * the exercise that needs it — so the step is gone rather than relaxed.
 */
const EMPTY: Profile = {
  email: 'climber@example.com',
  display_name: null,
  target_grade_id: null,
  current_grade_id: null,
  primary_discipline: null,
  strength_aspect_id: null,
  weakness_aspect_id: null,
  sessions_per_week: null,
  available_weekdays: null,
  show_body_metrics: true,
  injuries_reviewed_at: null,
  aspect_ratings: [],
  injuries: [],
};

type Step = (typeof ONBOARDING_STEPS)[number];

const ANSWERS: Record<Step, Partial<Profile>> = {
  targetGrade: { target_grade_id: 42 },
  // Monday, Wednesday, Friday.
  availability: { sessions_per_week: 3, available_weekdays: 0b0010101 },
  // All three columns `0006` added, because all three are the step's question. The eight
  // ratings ride along with them and are deliberately NOT part of the test — since #54 the
  // sliders are optional detail behind a disclosure, so a row written from an untouched
  // default would credit a step nobody answered.
  aspects: { current_grade_id: 41, strength_aspect_id: 5, weakness_aspect_id: 1 },
  // The step is answered by the TIMESTAMP, not by the rows: "nothing is hurting" is a real
  // answer that writes none. A flagged injury is included to show both travel together.
  injuries: {
    injuries_reviewed_at: '2026-08-21T10:00:00Z',
    injuries: [{ injury_area_id: 3, note: null, started_on: '2026-08-21' }],
  },
};

function profileWith(...steps: Step[]): Profile {
  return steps.reduce<Profile>((profile, step) => ({ ...profile, ...ANSWERS[step] }), EMPTY);
}

/**
 * Every subset of the step list, as a list of step arrays — a bitmask over the list rather
 * than a hand-written table, so adding a step widens the sweep instead of leaving a hole in
 * it. The overstatement properties below are only worth anything if they hold for all 16.
 */
function subsets(): Step[][] {
  return Array.from({ length: 1 << ONBOARDING_STEPS.length }, (_unused, mask) =>
    ONBOARDING_STEPS.filter((_step, index) => (mask & (1 << index)) !== 0),
  );
}

describe('an untouched profile', () => {
  it('credits only the one thing that is genuinely already true', () => {
    // The account exists and the email that identifies it is on file. That is the whole of
    // the endowment, and it is the rule that governs the mechanic: a mechanic is allowed
    // only if the progress it signals is TRUE.
    const completion = stepCompletion(EMPTY);
    expect(completedStepCount(completion)).toBe(0);
    expect(remainingSteps(completion)).toEqual(ONBOARDING_STEPS);
  });

  it('opens the bar at the 20% floor Kilian asked for, never at 0', () => {
    // Endowed progress (Nunes & Drèze 2006): a 10-stamp card with 2 pre-filled is completed
    // at roughly twice the rate of an 8-stamp card, for identical real work. The floor was
    // 29% and is 20% since #54 — the same mechanic, read as less manipulative.
    expect(ENDOWED_FLOOR_PERCENT).toBe(20);
    expect(completionPercent(stepCompletion(EMPTY))).toBe(20);
  });

  it('needs BOTH halves of the availability step, not either one', () => {
    // The two columns are one question and are written together. Half an answer is the
    // state a hand-written `PATCH` can produce, and it must not credit the step — the old
    // "weekday mask is not zero" test credited it while `sessions_per_week` was a
    // placeholder the user had never seen.
    expect(stepCompletion({ ...EMPTY, sessions_per_week: 5 }).availability).toBe(false);
    expect(stepCompletion({ ...EMPTY, available_weekdays: 127 }).availability).toBe(false);
    expect(
      stepCompletion({ ...EMPTY, sessions_per_week: 5, available_weekdays: 127 }).availability,
    ).toBe(true);
  });

  it('needs ALL THREE of the aspects step, and never credits it off ratings', () => {
    // ⚠️ The regression #54 could reintroduce most easily. Until `0006` this step was
    // "at least one `aspect_ratings` row", which was sound while eight visible sliders plus
    // a deliberate Continue click WERE the question. They are not any more: they sit behind
    // a disclosure, so eight rows written from untouched defaults would credit a step the
    // user never answered. The three columns are the question now.
    const ratingsOnly: Profile = {
      ...EMPTY,
      aspect_ratings: [{ climbing_aspect_id: 1, score: 3, rated_at: '2026-08-21T00:00:00Z' }],
    };
    expect(stepCompletion(ratingsOnly).aspects).toBe(false);

    expect(stepCompletion({ ...EMPTY, current_grade_id: 41 }).aspects).toBe(false);
    expect(stepCompletion({ ...EMPTY, current_grade_id: 41, strength_aspect_id: 5 }).aspects).toBe(
      false,
    );
    expect(stepCompletion(profileWith('aspects')).aspects).toBe(true);
  });
});

describe('the arithmetic', () => {
  it('is the floor plus an equal share per step, and lands on whole numbers', () => {
    // 20 + 80 × done/4 = 20/40/60/80/100. No rounding happens at any point, which is worth
    // pinning: a five-step list would make every intermediate number a rounded one, and the
    // "each step is worth the same" claim would stop being exactly true.
    const percents = ONBOARDING_STEPS.map((_step, index) =>
      completionPercent(stepCompletion(profileWith(...ONBOARDING_STEPS.slice(0, index + 1)))),
    );
    expect(percents).toEqual([40, 60, 80, 100]);
    for (const percent of percents) expect(Number.isInteger(percent)).toBe(true);
  });

  it('is IDENTICALLY "the account is step zero of five"', () => {
    // ⚠️ This equivalence is the whole justification for the floor, so it is asserted
    // directly rather than left as a remark. `20 + 80 × done/4` === `100 × (1 + done) / 5`:
    // the floor is not a bonus bolted onto a four-step bar, it is the credit for a fifth
    // step that is already done — the account exists. If someone "simplifies" the formula
    // to `100 × done / 4` the bar starts at 0 and this fails; if they keep a floor but
    // change its size, the framing stops being true and this fails too.
    for (const steps of subsets()) {
      const done = steps.length;
      expect(completionPercent(stepCompletion(profileWith(...steps)))).toBe(
        (100 * (1 + done)) / (ONBOARDING_STEPS.length + 1),
      );
    }
  });

  it('rises with every step and never falls', () => {
    const percents = [0, 1, 2, 3, 4].map((count) =>
      completionPercent(stepCompletion(profileWith(...ONBOARDING_STEPS.slice(0, count)))),
    );
    expect(percents).toEqual([20, 40, 60, 80, 100]);
    expect([...percents].sort((a, b) => a - b)).toEqual(percents);
  });

  it('never reports below the endowed floor or above 100, for ANY combination', () => {
    for (const steps of subsets()) {
      const percent = completionPercent(stepCompletion(profileWith(...steps)));
      expect(percent).toBeGreaterThanOrEqual(ENDOWED_FLOOR_PERCENT);
      expect(percent).toBeLessThanOrEqual(100);
    }
  });

  it('counts exactly the steps that were answered, and no others', () => {
    for (const steps of subsets()) {
      const completion = stepCompletion(profileWith(...steps));
      expect(completedStepCount(completion)).toBe(steps.length);
      expect(remainingSteps(completion)).toEqual(
        ONBOARDING_STEPS.filter((step) => !steps.includes(step)),
      );
    }
  });
});

describe('100% is unreachable with a real step unanswered', () => {
  it('holds for every one of the 16 subsets, not just the happy path', () => {
    // The property Kilian actually cares about, stated as a property. A bar that reads 100%
    // over a NULL column is the failure that matters: the next reader of this profile is the
    // plan generator, and the dashboard stops nagging for the thing it needs.
    for (const steps of subsets()) {
      const complete = steps.length === ONBOARDING_STEPS.length;
      const percent = completionPercent(stepCompletion(profileWith(...steps)));
      expect(percent === 100).toBe(complete);
      // …and the two readouts can never disagree: nothing outstanding iff 100%.
      expect(remainingSteps(stepCompletion(profileWith(...steps))).length === 0).toBe(complete);
    }
  });

  it('reaches exactly 100% when all four are answered', () => {
    expect(completionPercent(stepCompletion(profileWith(...ONBOARDING_STEPS)))).toBe(100);
  });
});

describe('the injuries step, whose honest answer writes no rows', () => {
  const three = profileWith('targetGrade', 'availability', 'aspects');

  it('is complete for a healthy user: the TIMESTAMP is the answer, not the rows', () => {
    // The whole reason `injuries_reviewed_at` exists — and since #54 it is the ONLY step
    // that needs such a column, because it is the only remaining step whose honest answer
    // can be zero rows. Before it, this state was indistinguishable from "never asked" and
    // the bar could not reach 100% honestly.
    expect(
      completionPercent(stepCompletion({ ...three, injuries_reviewed_at: '2026-08-21T10:00:00Z' })),
    ).toBe(100);
  });

  it('is NOT complete while the step has never been submitted', () => {
    expect(stepCompletion(three).injuries).toBe(false);
    expect(completionPercent(stepCompletion(three))).toBe(80);
  });

  it('does not credit itself off an injury row alone', () => {
    // Belt and braces: the API always stamps the timestamp when it writes an injury, so
    // this state should not occur — and if a future write path forgets to, the bar must
    // under-report rather than assume.
    const rowsOnly = {
      ...three,
      injuries: [{ injury_area_id: 3, note: null, started_on: '2026-08-21' }],
    };
    expect(stepCompletion(rowsOnly).injuries).toBe(false);
  });

  it('is the step that inherited the outdoor-only lesson, and is not gated like it', () => {
    // ⚠️ The history worth keeping now that the equipment step is gone. That step required
    // one tick out of fifteen indoor rows, so an outdoor-only climber had nothing they could
    // honestly select: Continue never enabled, 100% unreachable, and the dashboard nagging
    // forever about a step they had answered correctly. **"The answer cannot be stored" is a
    // schema problem and gets a schema fix; it is never a reason to disable a control.**
    // "Nothing is hurting" is the storable case, and it reaches 100% with zero rows.
    const healthy = { ...three, injuries: [], injuries_reviewed_at: '2026-08-21T10:00:00Z' };
    expect(completionPercent(stepCompletion(healthy))).toBe(100);
  });
});

describe('the step list', () => {
  it('has four steps and no equipment step', () => {
    // ⚠️ Issue #54 removed it rather than relaxing it: the user is assumed to have access to
    // everything, and what they LACK is flagged on the exercise that needs it.
    // `equipment_reviewed_at` is still on the server and is read by nobody here.
    expect(ONBOARDING_STEPS).toEqual(['targetGrade', 'availability', 'aspects', 'injuries']);
    expect(ONBOARDING_STEPS).not.toContain('equipment');
  });

  it('puts the highest-friction step in the middle and a trivial one last', () => {
    // The plan's goal-gradient point, and the reason the order is a constant rather than
    // whatever the UI happens to render: motivation rises as the end approaches, so the
    // hardest question must not be the last thing between a user and a plan. Step 1 is the
    // target grade because it is the user's own freely-chosen goal, which every later screen
    // refers back to — including the current grade, asked on the same scale.
    const friction = ONBOARDING_STEPS.indexOf('aspects');
    expect(friction).toBeGreaterThan(0);
    expect(friction).toBeLessThan(ONBOARDING_STEPS.length - 1);
  });
});
