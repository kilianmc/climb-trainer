import { describe, expect, it } from 'vitest';

import type { LibraryExercise, PlanSession, Profile } from '../api/types';

import {
  canPreview,
  exerciseLabel,
  exercisesByKey,
  nextMonday,
  previewBlocker,
  previewKeyParts,
  sessionSummary,
} from './blueprint';

/**
 * Four behaviours, each a decision rather than a restatement of a render. Per the testing policy
 * in `CLAUDE.md`:
 *
 * - **`canPreview` / `previewBlocker`** — "critical business logic and domain rules". It decides
 *   whether a request is made at all, and *which* of five fixed sentences the user reads. Its
 *   order is the server's order, so getting it wrong points somebody at the wrong step.
 * - **`previewKeyParts`** — "complex transforms". It IS the cache identity: too narrow and a
 *   profile change serves a stale plan with no invalidation to save it; too wide and every
 *   unrelated edit re-generates a 32-week plan. Both directions are asserted.
 * - **`nextMonday`** — "date and timezone maths", named explicitly in the policy. The planner
 *   refuses a start date that is not a Monday, and the off-by-one shifts every session in the
 *   plan.
 * - **`exercisesByKey` / `exerciseLabel`** — "complex transforms": the join that turns a
 *   DB-free domain's key into something a climber can read, and what it does with a key it has
 *   never heard of.
 *
 * `sessionSummary` gets the one arm that is a decision — a session with no blocks must not read
 * as a data fault — and nothing more; the rest is string assembly.
 *
 * **No render test for `plan.lazy.tsx`.** Presentational UI is on the policy's SKIP list, and
 * the approved plan says so for this screen by name.
 */

/** A profile the generator would accept. Each test spoils exactly one field. */
function plannable(overrides: Partial<Profile> = {}): Profile {
  return {
    email: 'climber@example.com',
    display_name: 'Climber',
    show_body_metrics: true,
    primary_discipline: 'sport',
    target_grade_id: 208,
    current_grade_id: 206,
    sessions_per_week: 3,
    available_weekdays: 0b010_0101,
    strength_aspect_id: 1,
    weakness_aspect_id: 4,
    injuries_reviewed_at: '2026-08-24T00:00:00Z',
    aspect_ratings: [],
    injuries: [],
    ...overrides,
  };
}

describe('canPreview', () => {
  it.each([
    ['a complete profile', {}, null],
    ['no target grade', { target_grade_id: null }, 'no_target_grade'],
    // The discipline is derived from the target grade, so a NULL one is the same refusal.
    ['no discipline', { primary_discipline: null }, 'no_target_grade'],
    ['no current grade', { current_grade_id: null }, 'no_current_grade'],
    ['unanswered frequency', { sessions_per_week: null }, 'sessions_per_week_unanswered'],
    ['unanswered weekdays', { available_weekdays: null }, 'available_weekdays_unanswered'],
    // ⚠️ 0 is an ANSWER ("no days"), not an absence, and gets its own sentence.
    ['no day available', { available_weekdays: 0 }, 'no_available_days'],
    // Neither headline aspect is a refusal: an unanswered one costs the weakness bias, not
    // the plan (`PlannerInput` takes `str | None` for both).
    ['no strength or weakness', { strength_aspect_id: null, weakness_aspect_id: null }, null],
  ])('%s', (_label, overrides, reason) => {
    const profile = plannable(overrides);
    expect(previewBlocker(profile)?.reason ?? null).toBe(reason);
    expect(canPreview(profile)).toBe(reason === null);
  });

  it('cannot preview before the profile has loaded', () => {
    expect(canPreview(undefined)).toBe(false);
  });

  it('reports the FIRST missing answer, in the server handler order', () => {
    // Two answers missing. Naming the later one would send the user to a step that is not the
    // one the endpoint would complain about.
    const profile = plannable({ current_grade_id: null, sessions_per_week: null });
    expect(previewBlocker(profile)?.reason).toBe('no_current_grade');
  });

  it('sends an answered-but-empty weekday mask to the editor, not to onboarding', () => {
    // `/onboarding` redirects a complete profile to `/profile`, and this profile IS complete —
    // `available_weekdays: 0` counts as answered. A link there would bounce.
    expect(previewBlocker(plannable({ available_weekdays: 0 }))?.fix).toBe('/profile');
    expect(previewBlocker(plannable({ target_grade_id: null }))?.fix).toBe('/onboarding');
  });
});

describe('previewKeyParts', () => {
  const START = '2026-08-31';

  it('is identical for two equal profiles', () => {
    expect(previewKeyParts(plannable(), START)).toEqual(previewKeyParts(plannable(), START));
  });

  it.each([
    ['the start date', {}, '2026-09-07'],
    ['the target grade', { target_grade_id: 210 }, START],
    ['the current grade', { current_grade_id: 207 }, START],
    ['the discipline', { primary_discipline: 'boulder' as const }, START],
    ['the frequency', { sessions_per_week: 4 }, START],
    ['the weekdays', { available_weekdays: 0b000_0111 }, START],
    ['the declared strength', { strength_aspect_id: 2 }, START],
    ['the declared weakness', { weakness_aspect_id: 5 }, START],
    [
      'an open injury',
      { injuries: [{ injury_area_id: 3, note: null, started_on: '2026-08-01' }] },
      START,
    ],
  ])('changes when %s changes', (_label, overrides, start) => {
    expect(previewKeyParts(plannable(overrides), start)).not.toEqual(
      previewKeyParts(plannable(), START),
    );
  });

  it('ignores the order the endpoint returned the injuries in', () => {
    const injury = (id: number) => ({ injury_area_id: id, note: null, started_on: '2026-08-01' });
    expect(previewKeyParts(plannable({ injuries: [injury(3), injury(1)] }), START)).toEqual(
      previewKeyParts(plannable({ injuries: [injury(1), injury(3)] }), START),
    );
  });

  it('ignores an injury NOTE and start date, which the planner never reads', () => {
    // Otherwise editing a note throws away a 32-week plan and pays to generate another.
    expect(
      previewKeyParts(
        plannable({
          injuries: [{ injury_area_id: 3, note: 'left elbow', started_on: '2026-01-01' }],
        }),
        START,
      ),
    ).toEqual(
      previewKeyParts(
        plannable({ injuries: [{ injury_area_id: 3, note: null, started_on: '2026-08-01' }] }),
        START,
      ),
    );
  });

  it('ignores fields the planner does not read', () => {
    expect(
      previewKeyParts(
        plannable({ display_name: 'Somebody else', show_body_metrics: false }),
        START,
      ),
    ).toEqual(previewKeyParts(plannable(), START));
  });
});

describe('nextMonday', () => {
  it.each([
    // 2026-08-24 is a Monday.
    ['a Monday returns itself', 2026, 7, 24, '2026-08-24'],
    ['a Tuesday waits six days', 2026, 7, 25, '2026-08-31'],
    ['a Saturday waits two', 2026, 7, 29, '2026-08-31'],
    ['a Sunday waits one', 2026, 7, 30, '2026-08-31'],
    ['it crosses a month boundary', 2026, 7, 27, '2026-08-31'],
    ['it crosses a year boundary', 2026, 11, 30, '2027-01-04'],
  ])('%s', (_label, year, month, day, expected) => {
    // Local-time constructor on purpose: the whole point is that the answer is the browser's
    // Monday, and a UTC round trip is what would shift it.
    expect(nextMonday(new Date(year, month, day, 23, 30))).toBe(expected);
  });

  it('pads a single-digit month and day', () => {
    expect(nextMonday(new Date(2027, 0, 3))).toBe('2027-01-04');
  });
});

describe('exercisesByKey', () => {
  function exercise(key: string, name: string): LibraryExercise {
    return {
      id: 1,
      key,
      name,
      climbing_aspect_id: 1,
      protocol_kind: 'straight_sets',
      discipline: null,
      instructions: 'Do the thing.',
      equipment_ids: [],
      contraindicated_injury_area_ids: [],
      media_url: null,
      progression_of_id: null,
      regression_of_id: null,
      substitution_hint: null,
      prescriptions: [],
    };
  }

  const index = exercisesByKey([
    exercise('weighted_max_hangs', 'Weighted max hangs'),
    exercise('four_by_four', '4x4s'),
  ]);

  it('indexes what the library sent', () => {
    expect(index.get('four_by_four')?.name).toBe('4x4s');
    expect(index.size).toBe(2);
  });

  it('drops a key the library has no row for', () => {
    expect(index.get('no_such_exercise')).toBeUndefined();
  });

  it('names an unknown key rather than hiding the block that prescribed it', () => {
    // Deliberately unlike `namesOf`, which drops an unresolvable id: an id is an integer and
    // says nothing, a key is authored English. Dropping the block would hide prescribed work.
    expect(exerciseLabel('weighted_max_hangs', index)).toBe('Weighted max hangs');
    expect(exerciseLabel('front_lever_raises', index)).toBe('Front lever raises');
  });
});

describe('sessionSummary', () => {
  function session(overrides: Partial<PlanSession> = {}): PlanSession {
    return {
      weekday: 0,
      scheduled_on: '2026-08-31',
      activity_kind: 'climbing',
      title: 'Endurance, technique, mobility',
      estimated_minutes: 55,
      blocks: [],
      shortfalls: [],
      ...overrides,
    };
  }

  it('says a session prescribes nothing, rather than printing a zero', () => {
    // The Recovery slot is a real, explained outcome — "0 blocks" reads as a data fault.
    expect(sessionSummary(session({ estimated_minutes: null }))).toBe('nothing prescribed');
  });

  it('counts blocks and sets and omits an absent estimate', () => {
    const block = {
      order_index: 1,
      exercise_key: 'four_by_four',
      aspect_key: 'power_endurance',
      protocol_kind: 'circuit' as const,
      rest_after_seconds: null,
      rest_between_sets_seconds: 180,
      shortfall: null,
      sets: [1, 2, 3].map((set_index) => ({
        set_index,
        target_reps: 4,
        target_work_seconds: null,
        target_rest_seconds: 60,
        target_intensity_pct: null,
        target_rpe: 8,
        target_load_kg: null,
        target_grade_id: null,
      })),
    };
    expect(sessionSummary(session({ blocks: [block] }))).toBe('1 block · 3 sets · ~55 min');
    expect(sessionSummary(session({ blocks: [block], estimated_minutes: null }))).toBe(
      '1 block · 3 sets',
    );
  });
});
