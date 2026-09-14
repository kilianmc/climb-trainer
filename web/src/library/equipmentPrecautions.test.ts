import { describe, expect, it } from 'vitest';

import { EQUIPMENT_PRECAUTIONS, precautionsFor } from './equipmentPrecautions';

// `equipment.id` is assigned by the seed, so the map from id to key is the payload's, never
// a constant: these ids are this test's own vocabulary.
const KEYS = new Map([
  [1, 'hangboard'],
  [2, 'bouldering_wall'],
  [3, 'campus_board'],
]);

describe('precautionsFor', () => {
  it('returns the gear precaution for an exercise that loads the fingers', () => {
    expect(precautionsFor([1], KEYS)).toEqual([EQUIPMENT_PRECAUTIONS.hangboard]);
  });

  it('is SILENT for gear with no precaution, so the panel renders no block at all', () => {
    expect(precautionsFor([2], KEYS)).toEqual([]);
  });

  it('drops an id the vocabulary does not have rather than rendering a gap', () => {
    expect(precautionsFor([99], KEYS)).toEqual([]);
  });

  it('keeps the payload order and carries one string per piece of gear', () => {
    expect(precautionsFor([3, 2, 1], KEYS)).toEqual([
      EQUIPMENT_PRECAUTIONS.campus_board,
      EQUIPMENT_PRECAUTIONS.hangboard,
    ]);
  });
});
