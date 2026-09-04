import { describe, expect, it } from 'vitest';

import type { Profile, ProfilePatch, Vocabulary } from '../api/types';
import { ONBOARDING_STEPS } from './completion';
import {
  DEFAULT_ASPECT_SCORE,
  accountPatch,
  canSubmit,
  draftFrom,
  patchFor,
  patchForAll,
  stepOf,
  type ProfileDraft,
} from './draft';

/**
 * `patchFor` decides the exact key set each step sends, and that is the part of this
 * feature that can be wrong invisibly.
 *
 * `ProfilePatchRequest` is `extra="forbid"`, so **one extra key is a 422 for the whole
 * step** — the same class of bug `/login` shipped once by forwarding a form object whole,
 * which TypeScript cannot catch because excess-property checking only applies to object
 * literals. And a MISSING key is worse than an error: the request succeeds, the field is
 * silently not written, and the step reads as saved.
 *
 * Testing it here rather than through the rendered wizard is deliberate: the mapping is
 * pure, so a DOM, a router and a fetch mock would add three moving parts to an assertion
 * about object keys. The fields themselves are presentational and are not tested, per the
 * testing policy.
 *
 * ⚠️ Since issue #54 two of the four steps are **default-plus-disclosure state machines**
 * — "any day" and "nothing is hurting" are ticked before the user arrives — so the thing
 * being tested is no longer only a key set. It is the three-way distinction between *the
 * default answer*, *a named answer* and **not answered at all**, where the third must send
 * `{}`: `injuries: []` from an untouched step would stamp `injuries_reviewed_at` and the bar
 * would credit a step nobody looked at.
 */

/** The seeded climbing aspects, so "sends the ratings" means all of them. Written out rather
    than imported, so the fixture mirrors the vocabulary instead of echoing it. */
const ASPECT_KEYS = [
  'finger_strength',
  'general_strength',
  'power',
  'anaerobic_capacity',
  'power_endurance',
  'endurance',
  'technique',
  'core_tension',
  'antagonist_prehab',
  'mobility',
] as const;

const VOCABULARY: Vocabulary = {
  grade_systems: [
    { id: 1, key: 'font', name: 'Fontainebleau', discipline: 'boulder' },
    { id: 3, key: 'french', name: 'French', discipline: 'sport' },
  ],
  grades: [
    { id: 10, grade_system_id: 1, label: '6A', ordinal: 1010 },
    { id: 11, grade_system_id: 1, label: '6B', ordinal: 1012 },
    { id: 20, grade_system_id: 3, label: '7a', ordinal: 2015 },
  ],
  climbing_aspects: ASPECT_KEYS.map((key, index) => ({
    id: index + 1,
    key,
    name: key,
    description: `${key}.`,
  })),
  equipment: [
    // Still in the vocabulary payload, and read by nobody in `profile/` since #54: the
    // equipment STEP is gone, not the reference table. PR #10's exercises need it.
    { id: 5, key: 'hangboard', name: 'Hangboard', description: 'Edges.' },
  ],
  injury_areas: [
    { id: 8, key: 'elbow', name: 'Elbow', description: 'Tendons.' },
    { id: 9, key: 'shoulder', name: 'Shoulder', description: 'Cuff.' },
  ],
  // Irrelevant to this fixture; the phase copy is covered by tests/test_phase_guide.py.
  plan_goal: '',
  phase_guide: [],
  enums: {
    disciplines: ['boulder', 'sport'],
    activity_kinds: ['climbing'],
    ascent_styles: ['redpoint'],
    protocol_kinds: ['max_hang'],
    phases: ['base'],
    session_statuses: ['planned'],
  },
};

const EMPTY_PROFILE: Profile = {
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

/** All seven bits — "any day" as the mask actually stores it. */
const ALL_WEEKDAYS = 0b111_1111;
/** Monday, Wednesday, Friday. */
const SOME_WEEKDAYS = 0b001_0101;

const DEFAULT_SCORES = Object.fromEntries(
  ASPECT_KEYS.map((_key, index) => [index + 1, DEFAULT_ASPECT_SCORE]),
);

/** A draft with every step answered, which is what the round-trips below need. */
const ANSWERED: ProfileDraft = {
  ...draftFrom(EMPTY_PROFILE, VOCABULARY),
  targetGradeId: 11,
  currentGradeId: 10,
  strengthAspectId: 6,
  weaknessAspectId: 1,
  sessionsPerWeek: 4,
  availableWeekdays: SOME_WEEKDAYS,
  allWeekdays: false,
  injuries: { 8: '  sore  ' },
  noInjuries: false,
};

describe('draftFrom', () => {
  it('starts every aspect at the middle of the scale', () => {
    // ⚠️ Not "so the step is always submittable" any more — since #54 the sliders are
    // optional detail behind a disclosure and the step's question is the three picks. The
    // defaults still exist because whatever the disclosure is left at IS what gets saved.
    expect(draftFrom(EMPTY_PROFILE, VOCABULARY).aspectScores).toEqual(DEFAULT_SCORES);
  });

  it('does not invent a session frequency — the placeholder 0005 removed stays removed', () => {
    // ⚠️ The regression this pins: a draft that opened on 3 put the placeholder back from
    // the CLIENT, and `patchFor` sent it the moment one weekday was ticked — into the column
    // whose docstring tells the plan generator it may trust the value. NULL survives into
    // the form, the select shows "Choose a number", and the step cannot be submitted until
    // the user answers.
    const draft = draftFrom(EMPTY_PROFILE, VOCABULARY);
    expect(draft.sessionsPerWeek).toBeNull();
    const dayTicked = { ...draft, availableWeekdays: 0b000_0001, allWeekdays: false };
    expect(canSubmit('availability', dayTicked)).toBe(false);
    expect(patchFor('availability', dayTicked)).toEqual({});
  });

  it('keeps existing answers and fills only the gaps', () => {
    const draft = draftFrom(
      {
        ...EMPTY_PROFILE,
        display_name: 'Kilian',
        target_grade_id: 20,
        current_grade_id: 10,
        strength_aspect_id: 5,
        weakness_aspect_id: 1,
        aspect_ratings: [{ climbing_aspect_id: 2, score: 5, rated_at: '2026-08-21T00:00:00Z' }],
        injuries: [{ injury_area_id: 8, note: 'left side', started_on: '2026-08-21' }],
      },
      VOCABULARY,
    );

    // The picker follows the saved grade's own scale rather than resetting to the first.
    expect(draft.gradeSystemId).toBe(3);
    expect(draft.aspectScores).toEqual({ ...DEFAULT_SCORES, 2: 5 });
    expect(draft.injuries).toEqual({ 8: 'left side' });
    expect(draft.currentGradeId).toBe(10);
    expect(draft.strengthAspectId).toBe(5);
    expect(draft.weaknessAspectId).toBe(1);
    expect(draft.displayName).toBe('Kilian');
  });

  it('reads the two default answers back the way the columns store them', () => {
    // Both are "no new column" decisions, so reading them back is inference from the column
    // that does exist — and getting the inference wrong is how a user's named days or typed
    // note silently becomes the default on the next visit.
    const unanswered = draftFrom(EMPTY_PROFILE, VOCABULARY);
    // Unanswered means the default is OFFERED: "any day" ticked, mask still empty.
    expect(unanswered.allWeekdays).toBe(true);
    expect(unanswered.availableWeekdays).toBe(0);
    // …and "nothing is hurting" ticked, because no rows is the tick. What separates
    // "answered" from "never asked" is `injuries_reviewed_at`, which only `completion.ts`
    // reads — this flag is the DEFAULT answer, not a readout of one.
    expect(unanswered.noInjuries).toBe(true);

    // A stored 127 is indistinguishable from the tick, and that is the point of using the
    // mask instead of a new column: "all of them" is expressible in it.
    expect(
      draftFrom({ ...EMPTY_PROFILE, available_weekdays: ALL_WEEKDAYS }, VOCABULARY).allWeekdays,
    ).toBe(true);

    // Anything else is a real list of days, and the disclosure opens on it.
    const named = draftFrom({ ...EMPTY_PROFILE, available_weekdays: SOME_WEEKDAYS }, VOCABULARY);
    expect(named.allWeekdays).toBe(false);
    expect(named.availableWeekdays).toBe(SOME_WEEKDAYS);

    // `0` is a legal mask meaning "answered, no days" — the API accepts and stores it — but
    // it is not "any day", so the tick must not come back on.
    expect(draftFrom({ ...EMPTY_PROFILE, available_weekdays: 0 }, VOCABULARY).allWeekdays).toBe(
      false,
    );

    const hurt = draftFrom(
      { ...EMPTY_PROFILE, injuries: [{ injury_area_id: 8, note: null, started_on: '2026-08-21' }] },
      VOCABULARY,
    );
    expect(hurt.noInjuries).toBe(false);
  });
});

describe('patchFor sends exactly one step, and only that step', () => {
  it.each([
    ['targetGrade' as const, ['target_grade_id']],
    ['availability' as const, ['sessions_per_week', 'available_weekdays']],
    [
      'aspects' as const,
      ['current_grade_id', 'strength_aspect_id', 'weakness_aspect_id', 'aspect_ratings'],
    ],
    ['injuries' as const, ['injuries']],
  ])('%s sends %j and nothing else', (step, keys) => {
    expect(Object.keys(patchFor(step, ANSWERED)).sort()).toEqual([...keys].sort());
  });

  it('never sends the grade SCALE, which is a display preference and not a profile field', () => {
    // The server derives `primary_discipline` from the grade id. A scale on the wire would
    // be a second, contradictable source of truth for the same fact.
    expect(patchFor('targetGrade', ANSWERED)).toEqual({ target_grade_id: 11 });
  });

  it('never sends display_name from ANY step', () => {
    // ⚠️ It belongs to no step, so no step may carry it: a display name is not an answer to
    // an onboarding question and must never move the completion bar. The editor composes it
    // separately with `accountPatch`.
    const named: ProfileDraft = { ...ANSWERED, displayName: 'Kilian' };
    for (const step of ONBOARDING_STEPS) {
      expect(Object.keys(patchFor(step, named))).not.toContain('display_name');
    }
  });
});

describe('the availability step, whose default answer is "any day"', () => {
  it('sends all seven bits when "any day" is ticked, and does not clear the mask', () => {
    // "Any day" wins over whatever is in the mask, but is not destructive: the mask is left
    // as it was and simply not sent, so un-ticking brings back exactly what was chosen.
    const anyDay: ProfileDraft = { ...ANSWERED, allWeekdays: true };
    expect(patchFor('availability', anyDay)).toEqual({
      sessions_per_week: 4,
      available_weekdays: ALL_WEEKDAYS,
    });
    expect(anyDay.availableWeekdays).toBe(SOME_WEEKDAYS);
    expect(patchFor('availability', { ...anyDay, allWeekdays: false })).toEqual({
      sessions_per_week: 4,
      available_weekdays: SOME_WEEKDAYS,
    });
  });

  it('sends both halves or neither, never a mask on its own', () => {
    // A weekday mask with no frequency would leave the step half-answered, which
    // `completion.ts` correctly refuses to credit — so the bar would sit still after a
    // successful write, which reads as a lost answer.
    expect(patchFor('availability', { ...ANSWERED, sessionsPerWeek: null })).toEqual({});
    expect(
      patchFor('availability', { ...ANSWERED, sessionsPerWeek: null, allWeekdays: true }),
    ).toEqual({});
  });

  it('is submittable from either half of the weekday question, and from neither', () => {
    const draft = draftFrom(EMPTY_PROFILE, VOCABULARY);
    // The default tick answers the weekday half on arrival, so only the frequency is owed.
    expect(canSubmit('availability', draft)).toBe(false);
    expect(canSubmit('availability', { ...draft, sessionsPerWeek: 3 })).toBe(true);
    // Naming days answers it too.
    expect(
      canSubmit('availability', {
        ...draft,
        sessionsPerWeek: 3,
        allWeekdays: false,
        availableWeekdays: SOME_WEEKDAYS,
      }),
    ).toBe(true);
    // The one state that is not an answer: "any day" un-ticked with nothing named.
    expect(
      canSubmit('availability', {
        ...draft,
        sessionsPerWeek: 3,
        allWeekdays: false,
        availableWeekdays: 0,
      }),
    ).toBe(false);
  });
});

describe('the aspects step, which is three picks and not a row of sliders', () => {
  it('sends all three answers plus every rating, in one body', () => {
    // The scores ride along because picking a strength or a weakness writes that aspect's
    // score too — the two picks have their own columns since `0006`, and the ratings are the
    // optional detail behind the disclosure.
    expect(patchFor('aspects', ANSWERED)).toEqual({
      current_grade_id: 10,
      strength_aspect_id: 6,
      weakness_aspect_id: 1,
      aspect_ratings: ASPECT_KEYS.map((_key, index) => ({
        climbing_aspect_id: index + 1,
        score: DEFAULT_ASPECT_SCORE,
      })),
    });
  });

  it('sends NOTHING while any one of the three is missing', () => {
    // ⚠️ Not a partial body. Sending the ratings alone would write a row per aspect for a step
    // that has no answer, which is exactly what `completion.ts` stopped crediting.
    expect(patchFor('aspects', { ...ANSWERED, currentGradeId: null })).toEqual({});
    expect(patchFor('aspects', { ...ANSWERED, strengthAspectId: null })).toEqual({});
    expect(patchFor('aspects', { ...ANSWERED, weaknessAspectId: null })).toEqual({});
  });

  it('is NOT submittable on untouched 3s', () => {
    // ⚠️ The behaviour change #54 made, and the one a refactor is most likely to undo: this
    // step used to be submittable the moment it rendered, because visible sliders plus
    // a deliberate Continue click were a real answer. They are behind a disclosure now, so
    // they are not.
    const untouched = draftFrom(EMPTY_PROFILE, VOCABULARY);
    expect(untouched.aspectScores).toEqual(DEFAULT_SCORES);
    expect(canSubmit('aspects', untouched)).toBe(false);
    expect(canSubmit('aspects', { ...untouched, currentGradeId: 10 })).toBe(false);
    expect(canSubmit('aspects', ANSWERED)).toBe(true);
  });
});

describe('the injuries step, whose default answer is "nothing is hurting"', () => {
  it('sends the empty list that stamps injuries_reviewed_at when "none" is ticked', () => {
    // The tick is not a new column and does not need one: `injuries_reviewed_at` exists
    // precisely because zero rows is a legitimate answer, and `injuries: []` is what stamps
    // it. It also wins over whatever is in the map, without clearing it.
    const none: ProfileDraft = { ...ANSWERED, noInjuries: true };
    expect(patchFor('injuries', none)).toEqual({ injuries: [] });
    expect(none.injuries).toEqual({ 8: '  sore  ' });
    expect(patchFor('injuries', { ...none, noInjuries: false })).toEqual({
      injuries: [{ injury_area_id: 8, note: 'sore' }],
    });
  });

  it('sends NOTHING when neither answer has been given', () => {
    // ⚠️ The honesty gate, and the reason this branch exists at all. `injuries: []` here
    // would stamp the step as reviewed for a user who never looked at it, and the bar would
    // credit it — a step credited without an answer is the one failure this feature must not
    // have. `{}` is a legal no-op body, not a special case the caller has to remember.
    const untouched: ProfileDraft = { ...ANSWERED, noInjuries: false, injuries: {} };
    expect(patchFor('injuries', untouched)).toEqual({});
    expect(canSubmit('injuries', untouched)).toBe(false);
  });

  it('is submittable on arrival, because the default IS an answer', () => {
    // One tick either way, and the tick is already there. "Nothing is hurting" is storable —
    // unlike the equipment step's empty answer, which was not, and which is why that step
    // could disable Continue forever for an outdoor-only climber. **"The answer cannot be
    // stored" is a schema problem and gets a schema fix; it is never a reason to disable a
    // control.**
    const draft = draftFrom(EMPTY_PROFILE, VOCABULARY);
    expect(draft.noInjuries).toBe(true);
    expect(canSubmit('injuries', draft)).toBe(true);
    // …and a listed injury is the other way to answer it.
    expect(canSubmit('injuries', { ...draft, noInjuries: false, injuries: { 8: '' } })).toBe(true);
  });

  it('always STATES the note, because this screen owns the whole field', () => {
    // The server treats an omitted `note` as "keep what is stored" and an explicit `null`
    // as "clear it". The editor renders the note input as part of the step, so it must
    // always say which of the two it means — omitting the key here would make clearing a
    // note impossible from the UI.
    expect(patchFor('injuries', ANSWERED).injuries?.every((entry) => 'note' in entry)).toBe(true);
  });

  it('trims a note and sends null rather than an empty string', () => {
    expect(patchFor('injuries', ANSWERED)).toEqual({
      injuries: [{ injury_area_id: 8, note: 'sore' }],
    });
    expect(patchFor('injuries', { ...ANSWERED, injuries: { 8: '   ' } })).toEqual({
      injuries: [{ injury_area_id: 8, note: null }],
    });
  });
});

describe('canSubmit', () => {
  const draft = draftFrom(EMPTY_PROFILE, VOCABULARY);

  it('blocks the two steps that cannot be inferred, and only those', () => {
    // A target grade, a training frequency and the two aspect picks cannot be inferred from
    // anything. The two steps that open on a default answer are submittable as they stand.
    expect(canSubmit('targetGrade', draft)).toBe(false);
    expect(canSubmit('availability', draft)).toBe(false);
    expect(canSubmit('aspects', draft)).toBe(false);
    expect(canSubmit('injuries', draft)).toBe(true);
  });

  it('unblocks each step as soon as it has an answer', () => {
    expect(canSubmit('targetGrade', { ...draft, targetGradeId: 10 })).toBe(true);
    expect(canSubmit('availability', { ...draft, sessionsPerWeek: 3 })).toBe(true);
    expect(
      canSubmit('aspects', {
        ...draft,
        currentGradeId: 10,
        strengthAspectId: 6,
        weaknessAspectId: 1,
      }),
    ).toBe(true);
  });

  it('agrees with patchFor: a blocked step has nothing to send', () => {
    // The two are one contract read from either end — a step that cannot be submitted must
    // produce `{}`, and a step that produces `{}` must not be submittable. A drift between
    // them is either a button that sends nothing or a body that stamps an unanswered step.
    for (const step of ONBOARDING_STEPS) {
      const body = patchFor(step, draft);
      expect(Object.keys(body).length > 0).toBe(canSubmit(step, draft));
    }
  });
});

describe('accountPatch, which belongs to no step', () => {
  it('sends the display name, trimmed, when there is one', () => {
    expect(accountPatch({ ...ANSWERED, displayName: '  Kilian  ' })).toEqual({
      display_name: 'Kilian',
    });
  });

  it('sends nothing at all when there is no name to send', () => {
    // ⚠️ `{}`, never `{display_name: null}`: `null` means "no change" on this endpoint and
    // `DisplayName` refuses `''`, so there is no spelling of "clear my display name" here.
    expect(accountPatch({ ...ANSWERED, displayName: null })).toEqual({});
    expect(accountPatch({ ...ANSWERED, displayName: '' })).toEqual({});
    expect(accountPatch({ ...ANSWERED, displayName: '   ' })).toEqual({});
  });

  it('names no step, so it can never move the completion bar', () => {
    // The Account section reports its own failure. A `display_name` that attributed itself
    // to a step would both misreport that failure and credit an onboarding answer nobody
    // gave, which is the rule the whole feature rests on.
    expect(stepOf(accountPatch({ ...ANSWERED, displayName: 'Kilian' }))).toBeNull();
  });
});

describe('patchForAll, the editor single Save', () => {
  it('sends NOTHING for no steps — the honesty gate', () => {
    // ⚠️ The assertion that stops the editor's Save from stamping a step the user never
    // touched. Folding in every step would write `injuries: []` and a default rating per aspect
    // for someone who opened the editor to change their target grade, and the bar would
    // credit two steps they never saw. **The bar may only report answers a user gave.**
    expect(patchForAll(ANSWERED, [])).toEqual({});
  });

  it('sends exactly the steps it is given, and nothing from the others', () => {
    expect(patchForAll(ANSWERED, ['targetGrade'])).toEqual({ target_grade_id: 11 });
    const two = patchForAll(ANSWERED, ['targetGrade', 'availability']);
    expect(Object.keys(two).sort()).toEqual(
      ['available_weekdays', 'sessions_per_week', 'target_grade_id'].sort(),
    );
    // The step whose empty body is a stamp is the one that must not leak in.
    expect(two).not.toHaveProperty('injuries');
  });

  it('is the union of the per-step bodies when every step is named', () => {
    const all = patchForAll(ANSWERED, ONBOARDING_STEPS);
    const union: ProfilePatch = ONBOARDING_STEPS.reduce<ProfilePatch>(
      (body, step) => ({ ...body, ...patchFor(step, ANSWERED) }),
      {},
    );
    expect(all).toEqual(union);
    expect(Object.keys(all)).toHaveLength(8);
  });

  it('drops a named step that has no answer, rather than sending a partial one', () => {
    // Naming a step is "the user saw this card", not "the user answered it". An untouched
    // card contributes `{}`, which is how a visited-but-unanswered step stays uncredited.
    const half: ProfileDraft = { ...ANSWERED, noInjuries: false, injuries: {} };
    expect(patchForAll(half, ['injuries'])).toEqual({});
    expect(patchForAll(half, ['targetGrade', 'injuries'])).toEqual({ target_grade_id: 11 });
  });
});

describe('stepOf, the inverse of patchFor', () => {
  it.each(ONBOARDING_STEPS)('round-trips %s', (step) => {
    // This is what makes a failure message name the step that actually failed. A step whose
    // key set changed in `patchFor` and not in `stepOf` would misattribute every failure —
    // silently, since both sides would still be internally consistent.
    expect(stepOf(patchFor(step, ANSWERED))).toBe(step);
  });

  it('attributes each of the aspects step keys on its own', () => {
    // `0006` gave that step three more keys, and any one of them can arrive alone from the
    // editor's combined body. A key `patchFor` sends but `stepOf` does not own would report
    // its failure against the wrong card, or none.
    expect(stepOf({ current_grade_id: 10 })).toBe('aspects');
    expect(stepOf({ strength_aspect_id: 6 })).toBe('aspects');
    expect(stepOf({ weakness_aspect_id: 1 })).toBe('aspects');
    expect(stepOf({ aspect_ratings: [] })).toBe('aspects');
  });

  it('is null for a body that names no step', () => {
    // `{}` is what an unanswerable step produces, and it is never sent — but a null here has
    // to mean "cannot attribute this" rather than defaulting to the first step.
    expect(stepOf({})).toBeNull();
    expect(stepOf({ show_body_metrics: false })).toBeNull();
    expect(stepOf({ display_name: 'Kilian' })).toBeNull();
  });

  it('reports the editor combined body as its FIRST step', () => {
    // Acceptable only because the editor saves once, at the end, and shows the failure on
    // the card the user is standing on. If that ever changes, this is the assumption to fix.
    expect(stepOf(patchForAll(ANSWERED, ONBOARDING_STEPS))).toBe(ONBOARDING_STEPS[0]);
  });
});
