import type { Grade, Vocabulary } from '../api/types';

/**
 * Which grades the pickers offer, and how a current grade compares with a goal.
 *
 * ## The low end is cut, and it is cut CLIENT-SIDE
 *
 * Kilian's call (round 3): nobody sets a training goal of Font 4, so the 3s and 4s are noise
 * in a list of 24. This is a **filter over `GET /api/vocabulary`, not a seed change** — the
 * ladder itself has to keep every rung, because `server/domain/grades.py::convert` maps
 * between systems by ordinal and a missing rung would break a conversion, not just a picker.
 *
 * ## The rule, and why it is one rule rather than four
 *
 * The rungs are shared: one ordinal per rung, with each system's label hung off it. So "the
 * base of 5" is a **rung**, not a label, and it is found once per discipline — from the
 * system that actually has a grade called `5` — and then applied to every system on that
 * ladder by ordinal. Nothing is string-matched except the single anchor.
 *
 * - **Sport** anchors on French `5` (ordinal 2004). French loses `3, 3+, 4, 4+` (4 of 29);
 *   YDS loses `5.4, 5.5, 5.6, 5.7` (4 of 30) and now opens at **5.8**, which is the same rung
 *   as French 5, not a guess.
 * - **Boulder** anchors on Fontainebleau `5` (ordinal 1003). Font loses `3, 4, 4+` (3 of 24).
 *   V-scale loses `VB, V0, V1` (3 of 19) and opens at **V2**.
 *
 * ⚠️ **V-scale has no grade labelled `5` and no mapping was invented for it.** V2 is not an
 * equivalence anyone chose here: it is the label the seed already hangs on ordinal 1003,
 * the same rung as Font 5 (`_BOULDER_RUNGS`). If that seed ever disagrees, this filter
 * changes with it and no code here needs editing.
 *
 * **It fails open.** A discipline with no `5` anywhere keeps every grade, because an empty
 * picker is a dead end and a slightly long picker is not.
 *
 * ## ⚠️ Why this stays on the CLIENT now that the schema is open
 *
 * This PR touches the database, so "should the floor move server-side?" was a real question.
 * It stays here, and the reasoning is worth keeping because the answer is not obvious:
 *
 * - **The ladder is domain truth and has to stay complete.** `server/domain/grades.py::convert`
 *   maps between systems by ordinal; a rung missing from the reference data breaks a
 *   conversion, not just a picker. So the floor could only ever be a filter on the way out,
 *   never a deletion.
 * - **`GET /api/vocabulary` is shared reference data with a one-hour cache** (`private,
 *   max-age=3600`, plus `staleTime: Infinity` on the client). A product rule baked into that
 *   payload would be inherited by every future consumer of it — and the next consumer is an
 *   ascent log, where **Font 4 is a perfectly real thing to have climbed**. "We do not offer
 *   that as a training GOAL" is not the same claim as "that grade does not exist".
 * - **A stored below-floor grade must still render.** If the endpoint filtered, a profile
 *   holding one (dev data, an import, a goal set before the floor existed) would look up
 *   against a vocabulary that no longer contains it and the select would go blank. Filtering
 *   the *options* while `grades.find(...)` still resolves the *value* is exactly the split
 *   that avoids that.
 *
 * So: a presentation rule, in the presentation layer, next to the two pickers it governs. If a
 * second surface ever needs the same floor, this module is what it imports — not a new column.
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
