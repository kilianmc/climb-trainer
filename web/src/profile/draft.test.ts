import { describe, expect, it } from 'vitest';

import type { Profile, Vocabulary } from '../api/types';
import { ONBOARDING_STEPS } from './completion';
import { DEFAULT_ASPECT_SCORE, canSubmit, draftFrom, patchFor, stepOf } from './draft';

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
 */

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
  climbing_aspects: [
    { id: 1, key: 'finger_strength', name: 'Finger strength', description: 'Force.' },
    { id: 2, key: 'power', name: 'Power', description: 'Fast force.' },
  ],
  equipment: [
    { id: 5, key: 'hangboard', name: 'Hangboard', description: 'Edges.' },
    { id: 6, key: 'pull_up_bar', name: 'Pull-up bar', description: 'A bar.' },
  ],
  injury_areas: [{ id: 8, key: 'elbow', name: 'Elbow', description: 'Tendons.' }],
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
  target_grade_id: null,
  primary_discipline: null,
  sessions_per_week: null,
  available_weekdays: null,
  show_body_metrics: true,
  equipment_reviewed_at: null,
  injuries_reviewed_at: null,
  equipment_ids: [],
  aspect_ratings: [],
  injuries: [],
};

describe('draftFrom', () => {
  it('starts every aspect at the middle of the scale, so the step is always submittable', () => {
    const draft = draftFrom(EMPTY_PROFILE, VOCABULARY);
    expect(draft.aspectScores).toEqual({ 1: DEFAULT_ASPECT_SCORE, 2: DEFAULT_ASPECT_SCORE });
  });

  it('does not invent a session frequency — the placeholder 0005 removed stays removed', () => {
    // ⚠️ The regression this pins: a draft that opened on 3 put the placeholder back from
    // the CLIENT, and `patchFor` sent it the moment one weekday was ticked — into the column
    // whose docstring tells the plan generator it may trust the value. NULL survives into
    // the form, the select shows "Choose a number", and the step cannot be submitted until
    // the user answers.
    const draft = draftFrom(EMPTY_PROFILE, VOCABULARY);
    expect(draft.sessionsPerWeek).toBeNull();
    expect(canSubmit('availability', { ...draft, availableWeekdays: 0b0000001 })).toBe(false);
    expect(patchFor('availability', { ...draft, availableWeekdays: 0b0000001 })).toEqual({});
  });

  it('keeps existing answers and fills only the gaps', () => {
    const draft = draftFrom(
      {
        ...EMPTY_PROFILE,
        target_grade_id: 20,
        aspect_ratings: [{ climbing_aspect_id: 2, score: 5, rated_at: '2026-08-21T00:00:00Z' }],
        injuries: [{ injury_area_id: 8, note: 'left side', started_on: '2026-08-21' }],
      },
      VOCABULARY,
    );

    // The picker follows the saved grade's own scale rather than resetting to the first.
    expect(draft.gradeSystemId).toBe(3);
    expect(draft.aspectScores).toEqual({ 1: DEFAULT_ASPECT_SCORE, 2: 5 });
    expect(draft.injuries).toEqual({ 8: 'left side' });
  });
});

describe('patchFor sends exactly one step, and only that step', () => {
  const draft = {
    ...draftFrom(EMPTY_PROFILE, VOCABULARY),
    targetGradeId: 11,
    sessionsPerWeek: 4,
    availableWeekdays: 0b0010101,
    equipmentIds: [6, 5],
    injuries: { 8: '  sore  ' },
  };

  it.each([
    ['targetGrade' as const, ['target_grade_id']],
    ['availability' as const, ['sessions_per_week', 'available_weekdays']],
    ['equipment' as const, ['equipment_ids']],
    ['aspects' as const, ['aspect_ratings']],
    ['injuries' as const, ['injuries']],
  ])('%s sends %j and nothing else', (step, keys) => {
    expect(Object.keys(patchFor(step, draft)).sort()).toEqual([...keys].sort());
  });

  it('never sends the grade SCALE, which is a display preference and not a profile field', () => {
    // The server derives `primary_discipline` from the grade id. A scale on the wire would
    // be a second, contradictable source of truth for the same fact.
    expect(patchFor('targetGrade', draft)).toEqual({ target_grade_id: 11 });
  });

  it('sends equipment ids sorted, so an unchanged set is an unchanged body', () => {
    expect(patchFor('equipment', draft)).toEqual({ equipment_ids: [5, 6] });
  });

  it('sends one rating per aspect, as ids', () => {
    expect(patchFor('aspects', draft)).toEqual({
      aspect_ratings: [
        { climbing_aspect_id: 1, score: DEFAULT_ASPECT_SCORE },
        { climbing_aspect_id: 2, score: DEFAULT_ASPECT_SCORE },
      ],
    });
  });

  it('always STATES the note, because this screen owns the whole field', () => {
    // The server treats an omitted `note` as "keep what is stored" and an explicit `null`
    // as "clear it". The editor renders the note input as part of the step, so it must
    // always say which of the two it means — omitting the key here would make clearing a
    // note impossible from the UI.
    expect(patchFor('injuries', draft).injuries?.every((entry) => 'note' in entry)).toBe(true);
  });

  it('trims an injury note and sends null rather than an empty string', () => {
    expect(patchFor('injuries', draft)).toEqual({
      injuries: [{ injury_area_id: 8, note: 'sore' }],
    });
    expect(patchFor('injuries', { ...draft, injuries: { 8: '   ' } })).toEqual({
      injuries: [{ injury_area_id: 8, note: null }],
    });
  });

  it('sends an empty list when every flag is cleared, because the list IS the state', () => {
    expect(patchFor('injuries', { ...draft, injuries: {} })).toEqual({ injuries: [] });
  });
});

describe('canSubmit', () => {
  const draft = draftFrom(EMPTY_PROFILE, VOCABULARY);

  it('blocks only the two steps that have no answer until the user gives one', () => {
    // A target grade and a training frequency cannot be inferred, and the controls open
    // with nothing chosen. Everything else below is submittable as it stands.
    expect(canSubmit('targetGrade', draft)).toBe(false);
    expect(canSubmit('availability', draft)).toBe(false);
  });

  it('NEVER blocks a step whose honest answer can be nothing', () => {
    // "I own none of this" and "nothing is hurting" are real answers, and blocking them was
    // a hard dead-end for an outdoor-only climber: no checkbox they could honestly tick,
    // Continue permanently disabled, 100% unreachable. The server records the answer with a
    // `*_reviewed_at` timestamp instead.
    expect(canSubmit('equipment', draft)).toBe(true);
    expect(canSubmit('injuries', draft)).toBe(true);
    // …and the sliders start mid-scale, so that step always has a value too.
    expect(canSubmit('aspects', draft)).toBe(true);
  });

  it('unblocks each step as soon as it has one', () => {
    expect(canSubmit('targetGrade', { ...draft, targetGradeId: 10 })).toBe(true);
    expect(canSubmit('availability', { ...draft, sessionsPerWeek: 3, availableWeekdays: 1 })).toBe(
      true,
    );
  });
});

describe('stepOf, the inverse of patchFor', () => {
  const draft = {
    ...draftFrom(EMPTY_PROFILE, VOCABULARY),
    targetGradeId: 11,
    sessionsPerWeek: 4,
    availableWeekdays: 0b0010101,
    equipmentIds: [5],
    injuries: { 8: '' },
  };

  it.each(ONBOARDING_STEPS)('round-trips %s', (step) => {
    // This is what makes a failure message name the step that actually failed. A step whose
    // key set changed in `patchFor` and not in `stepOf` would misattribute every failure —
    // silently, since both sides would still be internally consistent.
    expect(stepOf(patchFor(step, draft))).toBe(step);
  });

  it('is null for a body that names no step', () => {
    // `{}` is what an unanswerable step produces, and it is never sent — but a null here has
    // to mean "cannot attribute this" rather than defaulting to the first step.
    expect(stepOf({})).toBeNull();
    expect(stepOf({ show_body_metrics: false })).toBeNull();
  });
});
