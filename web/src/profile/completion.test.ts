import { describe, expect, it } from 'vitest';

import type { Profile } from '../api/types';
import {
  CREDITED_ON_SIGN_UP,
  ONBOARDING_STEPS,
  TOTAL_UNITS,
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
 * - the bar **opens at 25-30% and never at 0%** (endowed progress);
 * - it reaches **exactly 100%** when the five steps are done;
 * - it **never overstates** — no combination of answers may credit a step that has none.
 *
 * The last one is why the empty-profile case is asserted field by field rather than only
 * as a number: a placeholder read as an answer is the failure mode, and it would show up
 * as 43% on a profile nobody has touched.
 */

const EMPTY: Profile = {
  target_grade_id: null,
  primary_discipline: null,
  // NULL, not a placeholder. Revision 0005 exists so this column can say "not answered";
  // before it, a fresh row carried a plausible 3 and no reader could tell the difference.
  sessions_per_week: null,
  available_weekdays: null,
  show_body_metrics: true,
  equipment_reviewed_at: null,
  injuries_reviewed_at: null,
  equipment_ids: [],
  aspect_ratings: [],
  injuries: [],
};

const ANSWERS: Record<(typeof ONBOARDING_STEPS)[number], Partial<Profile>> = {
  targetGrade: { target_grade_id: 42 },
  // Monday, Wednesday, Friday.
  availability: { sessions_per_week: 3, available_weekdays: 0b0010101 },
  // Both halves: the ids AND the timestamp. The timestamp is the answer — see the
  // outdoor-only case below, where there are no ids to give.
  equipment: { equipment_reviewed_at: '2026-08-21T10:00:00Z', equipment_ids: [1, 2] },
  aspects: {
    aspect_ratings: [{ climbing_aspect_id: 1, score: 3, rated_at: '2026-08-21T00:00:00Z' }],
  },
  // The step is answered by the TIMESTAMP, not by the rows: "no current injuries" is a
  // real answer that writes none. A flagged injury is included to show both travel together.
  injuries: {
    injuries_reviewed_at: '2026-08-21T10:00:00Z',
    injuries: [{ injury_area_id: 3, note: null, started_on: '2026-08-21' }],
  },
};

function profileWith(...steps: (typeof ONBOARDING_STEPS)[number][]): Profile {
  return steps.reduce<Profile>((profile, step) => ({ ...profile, ...ANSWERS[step] }), EMPTY);
}

/** Every subset of the five steps, as a list of step arrays. */
function subsets(): (typeof ONBOARDING_STEPS)[number][][] {
  return Array.from({ length: 1 << ONBOARDING_STEPS.length }, (_unused, mask) =>
    ONBOARDING_STEPS.filter((_step, index) => (mask & (1 << index)) !== 0),
  );
}

describe('an untouched profile', () => {
  it('credits only the two things that are genuinely already true', () => {
    const completion = stepCompletion(EMPTY);
    expect(completedStepCount(completion)).toBe(0);
    expect(CREDITED_ON_SIGN_UP).toBe(2);
    expect(TOTAL_UNITS).toBe(7);
  });

  it('opens the bar inside the 25-30% window Kilian asked for, never at 0', () => {
    const percent = completionPercent(stepCompletion(EMPTY));
    expect(percent).toBe(29);
    expect(percent).toBeGreaterThanOrEqual(25);
    expect(percent).toBeLessThanOrEqual(30);
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
});

describe('finishing the steps', () => {
  it('reaches exactly 100% when all five are answered', () => {
    expect(completionPercent(stepCompletion(profileWith(...ONBOARDING_STEPS)))).toBe(100);
  });

  it('rises with every step and never falls', () => {
    const percents = ONBOARDING_STEPS.map((_step, index) =>
      completionPercent(stepCompletion(profileWith(...ONBOARDING_STEPS.slice(0, index + 1)))),
    );
    expect(percents).toEqual([43, 57, 71, 86, 100]);
  });

  it('never reports below the endowed floor or above 100, for ANY combination', () => {
    for (const steps of subsets()) {
      const percent = completionPercent(stepCompletion(profileWith(...steps)));
      expect(percent).toBeGreaterThanOrEqual(29);
      expect(percent).toBeLessThanOrEqual(100);
    }
  });

  it('counts exactly the steps that were answered, and no others', () => {
    for (const steps of subsets()) {
      const completion = stepCompletion(profileWith(...steps));
      expect(remainingSteps(completion)).toEqual(
        ONBOARDING_STEPS.filter((step) => !steps.includes(step)),
      );
    }
  });
});

describe('the two steps whose honest answer can be NOTHING', () => {
  const answered = (steps: (typeof ONBOARDING_STEPS)[number][]) => profileWith(...steps);

  it('an outdoor-only climber who ticks ONLY outdoor rock reaches 100%', () => {
    // The other half of the fix, and it is seed data rather than code: until `EQUIPMENT`
    // grew `outdoor_boulders` / `outdoor_routes` there was no row a rock climber could
    // honestly tick: all fifteen options then were walls or kit they did not have. `tests/test_equipment_vocabulary.py` guards the vocabulary itself;
    // this pins that one such tick is a complete answer.
    const onRock: Profile = {
      ...answered(['targetGrade', 'availability', 'aspects', 'injuries']),
      equipment_ids: [99],
      equipment_reviewed_at: '2026-08-21T10:00:00Z',
    };
    expect(completionPercent(stepCompletion(onRock))).toBe(100);
  });

  it('an outdoor-only climber with no equipment at all still reaches 100%', () => {
    // The real user this exists for: no gym membership, no hangboard, no home gear. Every
    // one of the fifteen seeded rows is a wall or a piece of kit they do not have, so there
    // is nothing they can honestly tick — and gating the step on `length > 0` made 100%
    // unreachable for them and left the dashboard nagging forever. `equipment_reviewed_at`
    // is what makes "none of these" a recordable answer, exactly as for injuries.
    const outdoorOnly: Profile = {
      ...answered(['targetGrade', 'availability', 'aspects', 'injuries']),
      equipment_ids: [],
      equipment_reviewed_at: '2026-08-21T10:00:00Z',
    };
    expect(stepCompletion(outdoorOnly).equipment).toBe(true);
    expect(completionPercent(stepCompletion(outdoorOnly))).toBe(100);
  });

  it('does not credit the equipment step off rows alone', () => {
    const rowsOnly = { ...EMPTY, equipment_ids: [1, 2] };
    expect(stepCompletion(rowsOnly).equipment).toBe(false);
  });
});

describe('the injuries step, whose honest answer writes no rows', () => {
  const four = profileWith('targetGrade', 'availability', 'equipment', 'aspects');

  it('is complete for a healthy user: the TIMESTAMP is the answer, not the rows', () => {
    // The whole reason `injuries_reviewed_at` exists. Before it, this state was
    // indistinguishable from "never asked" and the bar could not reach 100% honestly.
    expect(
      completionPercent(stepCompletion({ ...four, injuries_reviewed_at: '2026-08-21T10:00:00Z' })),
    ).toBe(100);
  });

  it('is NOT complete while the step has never been submitted', () => {
    expect(completionPercent(stepCompletion(four))).toBe(86);
  });

  it('does not credit itself off an injury row alone', () => {
    // Belt and braces: the API always stamps the timestamp when it writes an injury, so
    // this state should not occur — and if a future write path forgets to, the bar must
    // under-report rather than assume.
    const rowsOnly = {
      ...four,
      injuries: [{ injury_area_id: 3, note: null, started_on: '2026-08-21' }],
    };
    expect(stepCompletion(rowsOnly).injuries).toBe(false);
  });
});

describe('the step order', () => {
  it('puts the highest-friction step in the middle and a trivial one last', () => {
    // The plan's goal-gradient point, and the reason the order is a constant rather than
    // whatever the UI happens to render: motivation rises as the end approaches, so the
    // eight self-ratings must not be the last thing standing between a user and a plan.
    expect(ONBOARDING_STEPS).toEqual([
      'targetGrade',
      'availability',
      'equipment',
      'aspects',
      'injuries',
    ]);
    // The property that matters: the friction is neither the first screen a new account
    // ever sees nor the last thing between the user and a finished profile.
    const friction = ONBOARDING_STEPS.indexOf('aspects');
    expect(friction).toBeGreaterThan(0);
    expect(friction).toBeLessThan(ONBOARDING_STEPS.length - 1);
  });
});
