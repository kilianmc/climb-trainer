import type { Grade, Vocabulary } from '../api/types';

/**
 * Which grades the pickers offer, and how a current grade compares with a goal.
 *
 * Nobody sets a training goal of Font 4, so the 3s and 4s are cut — as a **filter over
 * `GET /api/vocabulary`, never a seed change**. The rungs are shared (one ordinal, each
 * system's label hung off it), so "the base of 5" is a **rung**: found once per discipline from
 * the system that actually has a grade called `5` (French 5 = 2004, Font 5 = 1003) and then
 * applied to every system on that ladder **by ordinal**. Nothing is string-matched except the
 * single anchor. ⚠️ **V-scale has no grade labelled `5` and no mapping was invented**: V2 is
 * simply the label the seed hangs on ordinal 1003. **It fails open** — a discipline with no `5`
 * keeps every grade, because an empty picker is a dead end and a long one is not.
 *
 * ## ⚠️ Why the floor stays on the CLIENT, re-decided when the schema opened
 *
 * - **The ladder is domain truth and must stay complete.** `server/domain/grades.py::convert`
 *   maps between systems by ordinal, so a missing rung breaks a conversion, not just a picker.
 * - **`GET /api/vocabulary` is shared reference data behind a one-hour cache**, so a product
 *   rule baked into it is inherited by every future consumer — and the next one is an ascent
 *   log, where **Font 4 is a real thing to have climbed**. "We do not offer that as a GOAL" is
 *   not the claim "that grade does not exist".
 * - **A stored below-floor grade must still render.** Filtering the *options* while
 *   `grades.find(...)` still resolves the *value* is exactly what stops the select going blank.
 */
const FLOOR_LABEL = '5';

function floorOrdinalFor(vocabulary: Vocabulary, systemId: number): number | null {
  const system = vocabulary.grade_systems.find((entry) => entry.id === systemId);
  if (system === undefined) return null;

  const ladder = new Set(
    vocabulary.grade_systems
      .filter((entry) => entry.discipline === system.discipline)
      .map((entry) => entry.id),
  );
  const anchors = vocabulary.grades.filter(
    (grade) => ladder.has(grade.grade_system_id) && grade.label === FLOOR_LABEL,
  );
  if (anchors.length === 0) return null;
  return Math.min(...anchors.map((grade) => grade.ordinal));
}

/** One system's offered grades, floored and in ascending difficulty. */
export function gradesForSystem(vocabulary: Vocabulary, systemId: number | null): Grade[] {
  if (systemId === null) return [];
  const floor = floorOrdinalFor(vocabulary, systemId);
  return (
    vocabulary.grades
      .filter(
        (grade) => grade.grade_system_id === systemId && (floor === null || grade.ordinal >= floor),
      )
      // Explicit, rather than trusting the endpoint's `sort_order`: the ordinal IS the ladder,
      // and it is the same number the comparison below reads.
      .sort((a, b) => a.ordinal - b.ordinal)
  );
}

/**
 * Where a current grade sits relative to the goal, or `null` when the question cannot be
 * asked.
 *
 * ⚠️ **Comparable ordinals are not a given, and this checks rather than assumes.** The bands
 * are 1000 apart per discipline precisely so that a cross-discipline subtraction produces an
 * absurd number instead of a plausible one, and `convert()` raises `CrossDisciplineError`
 * rather than answer. Both pickers are locked to one scale by the UI, so a mismatch should be
 * unreachable — which is exactly why it is worth returning `null` for instead of trusting.
 */
export type GoalComparison = 'below' | 'equal' | 'above';

export function compareToGoal(
  vocabulary: Vocabulary,
  currentGradeId: number | null,
  targetGradeId: number | null,
): GoalComparison | null {
  if (currentGradeId === null || targetGradeId === null) return null;

  const current = vocabulary.grades.find((grade) => grade.id === currentGradeId);
  const target = vocabulary.grades.find((grade) => grade.id === targetGradeId);
  if (current === undefined || target === undefined) return null;

  const disciplineOf = (systemId: number) =>
    vocabulary.grade_systems.find((entry) => entry.id === systemId)?.discipline;
  const currentDiscipline = disciplineOf(current.grade_system_id);
  if (currentDiscipline === undefined || currentDiscipline !== disciplineOf(target.grade_system_id))
    return null;

  if (current.ordinal > target.ordinal) return 'above';
  return current.ordinal === target.ordinal ? 'equal' : 'below';
}
