import { describe, expect, it } from 'vitest';

import type { LibraryExercise, Prescription, ReferenceRow } from '../api/types';

import { groupByAspect, nameIndex, namesOf, prescriptionLine } from './browse';

/**
 * The grouping walk and the id -> name joins, and nothing else.
 *
 * Per the testing policy this file exists for the two behaviours that are decisions rather than
 * restatements of a render: **the payload's order is authoritative** (the screen groups by
 * walking and breaking, so it can never re-sort the content the server ordered by
 * `sort_order`), and **a null prescription term is omitted, not printed**. The browse component
 * itself is presentational markup and is deliberately untested.
 */
function exercise(id: number, aspectId: number): LibraryExercise {
  return {
    id,
    key: `ex-${String(id)}`,
    name: `Exercise ${String(id)}`,
    climbing_aspect_id: aspectId,
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

function row(id: number, name: string): ReferenceRow {
  return { id, key: name.toLowerCase(), name, description: '' };
}

const EMPTY_PRESCRIPTION: Prescription = {
  phase: 'base',
  sets: 3,
  reps: null,
  work_seconds: null,
  rest_seconds: null,
  rest_between_sets_seconds: null,
  intensity_pct: null,
  target_rpe: null,
};

describe('groupByAspect', () => {
  it('breaks a group only where the aspect id changes, keeping payload order', () => {
    const aspects = nameIndex([row(7, 'Finger strength'), row(2, 'Power')]);

    const groups = groupByAspect([exercise(1, 7), exercise(2, 7), exercise(3, 2)], aspects).map(
      (group) => [group.title, group.exercises.map((ex) => ex.id)],
    );

    // Aspect 7 comes first because the payload put it first — NOT because 2 < 7. A client-side
    // sort by the serial id would reverse these two and lose `climbing_aspect.sort_order`.
    expect(groups).toEqual([
      ['Finger strength', [1, 2]],
      ['Power', [3]],
    ]);
  });

  it('shows an interleaved payload as interleaved rather than tidying it away', () => {
    const groups = groupByAspect(
      [exercise(1, 7), exercise(2, 2), exercise(3, 7)],
      nameIndex([row(7, 'Finger strength'), row(2, 'Power')]),
    );

    expect(groups.map((group) => group.aspectId)).toEqual([7, 2, 7]);
  });

  it('still gives a heading a name when the vocabulary has no row for the aspect', () => {
    const [group] = groupByAspect([exercise(1, 99)], nameIndex([]));

    expect(group?.title).toBe('Unlisted aspect');
  });
});

describe('namesOf', () => {
  it('joins in payload order and drops an id the vocabulary does not know', () => {
    const index = nameIndex([row(1, 'Hangboard'), row(4, 'Rings')]);

    expect(namesOf([4, 1, 9], index)).toEqual(['Rings', 'Hangboard']);
  });

  it('answers empty for an empty AND set, which is "requires nothing"', () => {
    expect(namesOf([], nameIndex([row(1, 'Hangboard')]))).toEqual([]);
  });
});

describe('prescriptionLine', () => {
  it('omits every null term rather than printing it', () => {
    expect(prescriptionLine(EMPTY_PRESCRIPTION)).toBe('3 sets');
  });

  it('renders the terms it has, in a fixed order', () => {
    const line = prescriptionLine({
      ...EMPTY_PRESCRIPTION,
      sets: 1,
      work_seconds: 7,
      rest_seconds: 3,
      rest_between_sets_seconds: 180,
      intensity_pct: 85,
      target_rpe: 8,
    });

    expect(line).toBe('1 set · 7s work · 3s rest · 180s between sets · 85% intensity · RPE 8');
  });
});
