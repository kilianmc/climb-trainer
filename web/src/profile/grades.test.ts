import { describe, expect, it } from 'vitest';

import type { Grade, Vocabulary } from '../api/types';
import { compareToGoal, gradesForSystem } from './grades';

/**
 * The grade picker's floor rule and the goal comparison — the two pieces of #54 that are
 * domain maths rather than markup, which is why they are tested and the pickers themselves
 * are not.
 *
 * ## The fixture is the REAL ladder, rebuilt the way the seed builds it
 *
 * A toy three-grade vocabulary would let every assertion below pass while the rule was
 * wrong for the data it actually runs on: the whole point of the filter is that "the base of
 * 5" is a **rung** found once per discipline and then applied by ordinal to a system that has
 * no grade called `5` at all. That behaviour only exists in the presence of four real scales
 * with real coverage holes, so the two rung tables from
 * `server/domain/grades.py` (`_BOULDER_RUNGS`, `_SPORT_RUNGS`) are mirrored here and the 102
 * grades are derived from them exactly as `_build_grades` does — `base + step`, `None` where
 * a system has no label on a rung.
 *
 * ⚠️ **Mirrored, so it can drift**, and the guard against that is on the server side where
 * the ladder lives (`tests/test_grades.py`, `tests/test_seed.py`, `tests/test_vocabulary_api.py`).
 * The counts asserted below are the ones the docstring in `grades.ts` states, so a real seed
 * change shows up as a disagreement between three files rather than a silent pass.
 */

const BAND_BASE = { boulder: 1000, sport: 2000 } as const;

/** `(font, v_scale)`, ascending. `null` = that system has no label on this rung. */
const BOULDER_RUNGS: readonly (readonly [string | null, string | null])[] = [
  ['3', 'VB'],
  ['4', 'V0'],
  ['4+', 'V1'],
  ['5', 'V2'],
  ['5+', null],
  ['6A', 'V3'],
  ['6A+', null],
  ['6B', 'V4'],
  ['6B+', null],
  ['6C', 'V5'],
  ['6C+', null],
  ['7A', 'V6'],
  ['7A+', 'V7'],
  ['7B', 'V8'],
  ['7B+', null],
  ['7C', 'V9'],
  ['7C+', 'V10'],
  ['8A', 'V11'],
  ['8A+', 'V12'],
  ['8B', 'V13'],
  ['8B+', 'V14'],
  ['8C', 'V15'],
  ['8C+', 'V16'],
  ['9A', 'V17'],
];

/** `(french, yds)`, ascending. */
const SPORT_RUNGS: readonly (readonly [string | null, string | null])[] = [
  ['3', '5.4'],
  ['3+', '5.5'],
  ['4', '5.6'],
  ['4+', '5.7'],
  ['5', '5.8'],
  ['5+', '5.9'],
  ['6a', '5.10a'],
  ['6a+', '5.10b'],
  ['6b', '5.10c'],
  ['6b+', '5.10d'],
  ['6c', '5.11a'],
  ['6c+', '5.11b'],
  [null, '5.11c'], // French does not split this rung.
  ['7a', '5.11d'],
  ['7a+', '5.12a'],
  ['7b', '5.12b'],
  ['7b+', '5.12c'],
  ['7c', '5.12d'],
  ['7c+', '5.13a'],
  ['8a', '5.13b'],
  ['8a+', '5.13c'],
  ['8b', '5.13d'],
  ['8b+', '5.14a'],
  ['8c', '5.14b'],
  ['8c+', '5.14c'],
  ['9a', '5.14d'],
  ['9a+', '5.15a'],
  ['9b', '5.15b'],
  ['9b+', '5.15c'],
  ['9c', '5.15d'],
];

const FONT = 1;
const V_SCALE = 2;
const FRENCH = 3;
const YDS = 4;

const GRADE_SYSTEMS: Vocabulary['grade_systems'] = [
  { id: FONT, key: 'font', name: 'Fontainebleau', discipline: 'boulder' },
  { id: V_SCALE, key: 'v_scale', name: 'V-scale', discipline: 'boulder' },
  { id: FRENCH, key: 'french', name: 'French', discipline: 'sport' },
  { id: YDS, key: 'yds', name: 'Yosemite Decimal System', discipline: 'sport' },
];

function buildGrades(): Grade[] {
  const ladders = [
    { base: BAND_BASE.boulder, systems: [FONT, V_SCALE], rungs: BOULDER_RUNGS },
    { base: BAND_BASE.sport, systems: [FRENCH, YDS], rungs: SPORT_RUNGS },
  ];
  const grades: Grade[] = [];
  let id = 1;
  for (const ladder of ladders) {
    ladder.rungs.forEach((rung, step) => {
      rung.forEach((label, index) => {
        const systemId = ladder.systems[index];
        if (label === null || systemId === undefined) return;
        grades.push({ id: id++, grade_system_id: systemId, label, ordinal: ladder.base + step });
      });
    });
  }
  return grades;
}

const VOCABULARY: Vocabulary = {
  grade_systems: GRADE_SYSTEMS,
  grades: buildGrades(),
  climbing_aspects: [],
  equipment: [],
  injury_areas: [],
  enums: {
    disciplines: ['boulder', 'sport'],
    activity_kinds: ['climbing'],
    ascent_styles: ['redpoint'],
    protocol_kinds: ['max_hang'],
    phases: ['base'],
    session_statuses: ['planned'],
  },
};

const labels = (systemId: number | null) =>
  gradesForSystem(VOCABULARY, systemId).map((grade) => grade.label);
const gradeId = (systemId: number, label: string) => {
  const grade = VOCABULARY.grades.find(
    (entry) => entry.grade_system_id === systemId && entry.label === label,
  );
  if (grade === undefined) throw new Error(`no ${label} in system ${String(systemId)}`);
  return grade.id;
};

describe('the fixture really is the seeded ladder', () => {
  it('is the 102 grades the seed produces, on two disjoint bands', () => {
    // If this number ever disagrees with `.venv/bin/python -c "from server.domain.grades
    // import GRADES; print(len(GRADES))"`, the rung tables above have drifted and every
    // count below is measuring the wrong thing.
    expect(VOCABULARY.grades).toHaveLength(102);
    const perSystem = GRADE_SYSTEMS.map(
      (system) => VOCABULARY.grades.filter((g) => g.grade_system_id === system.id).length,
    );
    expect(perSystem).toEqual([24, 19, 29, 30]);
    // Boulder in the 1000-band, rope in the 2000-band: 1000 apart so a cross-discipline
    // subtraction produces an obviously absurd number instead of a plausible one.
    expect(VOCABULARY.grades.every((g) => g.ordinal >= 1000 && g.ordinal < 3000)).toBe(true);
  });
});

describe('gradesForSystem floors each discipline at the base of 5', () => {
  it('drops the 3s and 4s from the two systems that HAVE a grade called 5', () => {
    // Kilian's call (round 3): nobody sets a training goal of Font 4, so the low rungs are
    // noise in a list of 24. A filter over `GET /api/vocabulary`, **not a seed change** — the
    // ladder itself has to keep every rung, because `convert` maps between systems by ordinal
    // and a missing rung would break a conversion, not just a picker.
    expect(labels(FONT)).toHaveLength(21);
    expect(labels(FONT)[0]).toBe('5');
    expect(labels(FONT)).not.toContain('4+');

    expect(labels(FRENCH)).toHaveLength(25);
    expect(labels(FRENCH)[0]).toBe('5');
    expect(labels(FRENCH).slice(0, 3)).toEqual(['5', '5+', '6a']);
  });

  it('floors the systems that have NO grade called 5, by ordinal and not by label', () => {
    // ⚠️ The part that would be wrong if the rule were per-system string matching. V-scale
    // has no `5` and YDS has no `5` — the anchor is found once per DISCIPLINE, from whichever
    // system on that ladder does have one, and then applied by ordinal.
    expect(labels(V_SCALE)).toHaveLength(16);
    expect(labels(V_SCALE)[0]).toBe('V2');
    expect(labels(V_SCALE).slice(0, 3)).toEqual(['V2', 'V3', 'V4']);

    expect(labels(YDS)).toHaveLength(26);
    expect(labels(YDS)[0]).toBe('5.8');
    expect(labels(YDS).slice(0, 3)).toEqual(['5.8', '5.9', '5.10a']);
  });

  it('opens each pair on the SAME rung, so no equivalence was invented here', () => {
    // ⚠️ V2 is not an equivalence anyone chose in this file: it is the label the seed already
    // hangs on the same ordinal as Font 5 (`_BOULDER_RUNGS`). Same for 5.8 and French 5. If
    // the seed ever disagrees, the filter follows it and no code in `grades.ts` needs editing
    // — which is only true while these ordinals are equal, so that is what is asserted.
    const firstOrdinal = (systemId: number) => gradesForSystem(VOCABULARY, systemId)[0]?.ordinal;
    expect(firstOrdinal(FONT)).toBe(firstOrdinal(V_SCALE));
    expect(firstOrdinal(FRENCH)).toBe(firstOrdinal(YDS));
    // And the two anchors are the rungs `grades.ts` names.
    expect(firstOrdinal(FONT)).toBe(1003);
    expect(firstOrdinal(FRENCH)).toBe(2004);
  });

  it('drops exactly the rungs below the anchor and keeps everything above it', () => {
    // The complement of the counts above, as a property: nothing in the middle of a ladder is
    // ever dropped, and the hardest grade is always offered.
    for (const system of GRADE_SYSTEMS) {
      const offered = gradesForSystem(VOCABULARY, system.id);
      const all = VOCABULARY.grades.filter((g) => g.grade_system_id === system.id);
      const floor = offered[0]?.ordinal ?? 0;
      expect(offered).toEqual(all.filter((g) => g.ordinal >= floor));
      expect(offered.at(-1)?.ordinal).toBe(Math.max(...all.map((g) => g.ordinal)));
    }
  });

  it('sorts by ORDINAL, which is the ladder, and not by the endpoint order', () => {
    // Explicit rather than trusting `sort_order`: the ordinal is the same number the
    // comparison below reads, so a picker sorted any other way would disagree with the
    // "above your goal" line under it.
    const shuffled: Vocabulary = { ...VOCABULARY, grades: [...VOCABULARY.grades].reverse() };
    const ordinals = gradesForSystem(shuffled, YDS).map((grade) => grade.ordinal);
    expect(ordinals).toEqual([...ordinals].sort((a, b) => a - b));
    expect(gradesForSystem(shuffled, YDS).map((g) => g.label)).toEqual(labels(YDS));
  });

  it('offers nothing when no scale has been chosen', () => {
    // The picker renders "Choose a grade" and no options — the draft opens with a system, so
    // this is the defensive branch, not a state the UI produces.
    expect(gradesForSystem(VOCABULARY, null)).toEqual([]);
    expect(gradesForSystem(VOCABULARY, 999)).toEqual([]);
  });
});

describe('the floor FAILS OPEN', () => {
  it('keeps every grade when no system on the ladder has a 5', () => {
    // ⚠️ The deliberate asymmetry: **an empty picker is a dead end and a slightly long picker
    // is not.** If a seed change ever renamed or removed the anchor label, the correct
    // behaviour is 24 grades in the list, not zero and a step nobody can complete — the same
    // lesson the equipment step taught the hard way.
    const noAnchor: Vocabulary = {
      ...VOCABULARY,
      grades: VOCABULARY.grades.map((grade) =>
        grade.label === '5' ? { ...grade, label: 'V-nonsense' } : grade,
      ),
    };
    expect(gradesForSystem(noAnchor, FONT)).toHaveLength(24);
    expect(gradesForSystem(noAnchor, V_SCALE)).toHaveLength(19);
    expect(gradesForSystem(noAnchor, FRENCH)).toHaveLength(29);
    expect(gradesForSystem(noAnchor, YDS)).toHaveLength(30);
  });

  it('fails open per DISCIPLINE, not globally', () => {
    // Losing the boulder anchor must not un-floor the rope ladder: the anchor is found from
    // the systems that share the discipline, so the two ladders are independent.
    const noBoulderAnchor: Vocabulary = {
      ...VOCABULARY,
      grades: VOCABULARY.grades.filter(
        (grade) => !(grade.grade_system_id === FONT && grade.label === '5'),
      ),
    };
    // Font itself loses one rung to the deletion, so 23 rather than 24 — the point is that
    // nothing below the old anchor is filtered any more.
    expect(
      gradesForSystem(noBoulderAnchor, FONT)
        .map((g) => g.label)
        .slice(0, 3),
    ).toEqual(['3', '4', '4+']);
    expect(gradesForSystem(noBoulderAnchor, V_SCALE)).toHaveLength(19);
    // The rope ladder is untouched and still floored.
    expect(gradesForSystem(noBoulderAnchor, FRENCH)).toHaveLength(25);
    expect(gradesForSystem(noBoulderAnchor, YDS)).toHaveLength(26);
  });
});

describe('compareToGoal', () => {
  it('reads below, equal and above off the shared ordinal', () => {
    // The line under the current-grade picker has four states and this decides three of
    // them. `equal` is the one that earns its own case: a goal you already climb leaves the
    // plan nothing to aim at, and the copy says so.
    const goal = gradeId(FONT, '7A');
    expect(compareToGoal(VOCABULARY, gradeId(FONT, '6B'), goal)).toBe('below');
    expect(compareToGoal(VOCABULARY, gradeId(FONT, '7A'), goal)).toBe('equal');
    expect(compareToGoal(VOCABULARY, gradeId(FONT, '8A'), goal)).toBe('above');
  });

  it('compares across systems on the same ladder, because the rung is shared', () => {
    // V6 and Font 7A are the same rung, which is the whole reason the ordinal exists. A user
    // whose current grade was stored in one scale and whose goal is shown in another must
    // still get a straight answer.
    expect(compareToGoal(VOCABULARY, gradeId(V_SCALE, 'V6'), gradeId(FONT, '7A'))).toBe('equal');
    expect(compareToGoal(VOCABULARY, gradeId(YDS, '5.12a'), gradeId(FRENCH, '7b'))).toBe('below');
  });

  it('refuses a cross-discipline comparison, and returns null rather than a number', () => {
    // ⚠️ The bands are 1000 apart precisely so that a cross-discipline subtraction produces
    // an absurd number instead of a plausible one, and `server/domain/grades.py::convert`
    // raises `CrossDisciplineError` rather than answer. Both pickers are locked to one scale
    // by the UI, so this should be unreachable — which is exactly why it is worth checking
    // for instead of trusting. A boulderer who set a French goal by mistake must be told
    // nothing, not told they are 1000 grades short.
    const answers = [
      compareToGoal(VOCABULARY, gradeId(FONT, '7A'), gradeId(FRENCH, '7a')),
      compareToGoal(VOCABULARY, gradeId(FRENCH, '7a'), gradeId(FONT, '7A')),
      compareToGoal(VOCABULARY, gradeId(V_SCALE, 'V6'), gradeId(YDS, '5.12a')),
    ];
    for (const answer of answers) {
      expect(answer).toBeNull();
      expect(typeof answer).not.toBe('number');
    }
  });

  it('cannot be asked before both grades are chosen', () => {
    const goal = gradeId(FONT, '7A');
    expect(compareToGoal(VOCABULARY, null, goal)).toBeNull();
    expect(compareToGoal(VOCABULARY, goal, null)).toBeNull();
    expect(compareToGoal(VOCABULARY, null, null)).toBeNull();
  });

  it('returns null for an id or a system the vocabulary does not know', () => {
    // A stale draft outliving a vocabulary change is the realistic route here. Silence is
    // the right answer; a thrown error would take the whole step down with it.
    const goal = gradeId(FONT, '7A');
    expect(compareToGoal(VOCABULARY, 9999, goal)).toBeNull();
    expect(compareToGoal(VOCABULARY, goal, 9999)).toBeNull();
    const orphan: Vocabulary = { ...VOCABULARY, grade_systems: [] };
    expect(compareToGoal(orphan, goal, goal)).toBeNull();
  });
});
