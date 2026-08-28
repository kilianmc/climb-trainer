/**
 * The two joins and one walk the library browse screen needs, kept out of the component so
 * they can be tested without rendering anything.
 *
 * ## The payload carries ids, not names — deliberately
 *
 * `GET /api/library` sends `climbing_aspect_id`, `equipment_ids` and
 * `contraindicated_injury_area_ids` and no display text for any of them. Duplicating the names
 * into that payload was rejected on purpose: `GET /api/vocabulary` already ships them for every
 * picker in the app, and two copies of a name is one copy that goes stale. So the screen joins
 * here, against the vocabulary the app has already fetched.
 *
 * ## Grouping is a WALK, not a sort
 *
 * The server returns the rows ordered by `climbing_aspect.sort_order`, then name. That order is
 * the content decision and the screen must not second-guess it, so `groupByAspect` walks the
 * array once and starts a new group whenever `climbing_aspect_id` changes. Two consequences,
 * both wanted: nothing is re-sorted client-side (a sort by the serial id would put the aspects
 * in insertion order, which is not `sort_order`), and if the payload ever came back interleaved
 * the screen would *show* that rather than quietly tidying it away.
 */
import type { LibraryExercise, Prescription, ReferenceRow } from '../api/types';

/** One aspect's run of exercises, in payload order. */
export interface AspectGroup {
  aspectId: number;
  title: string;
  exercises: LibraryExercise[];
}

/** `id -> name` for one of the vocabulary's reference lists. */
export function nameIndex(rows: readonly ReferenceRow[]): ReadonlyMap<number, string> {
  return new Map(rows.map((row) => [row.id, row.name]));
}

/**
 * The ids that have a name, in the order the payload listed them.
 *
 * An id with no vocabulary row is **dropped**, not rendered as a number: the only way to reach
 * that state is a library seeded ahead of the vocabulary a client holds, and a bare integer on
 * screen tells the reader nothing they can act on.
 */
export function namesOf(
  ids: readonly number[],
  index: ReadonlyMap<number, string>,
): readonly string[] {
  return ids.map((id) => index.get(id)).filter((name): name is string => name !== undefined);
}

export function groupByAspect(
  exercises: readonly LibraryExercise[],
  aspectNames: ReadonlyMap<number, string>,
): readonly AspectGroup[] {
  const groups: AspectGroup[] = [];
  let current: AspectGroup | undefined;

  for (const exercise of exercises) {
    if (current === undefined || current.aspectId !== exercise.climbing_aspect_id) {
      current = {
        aspectId: exercise.climbing_aspect_id,
        // A named aspect with no vocabulary row is not a state the seeds can produce; the
        // heading still has to say something rather than render empty.
        title: aspectNames.get(exercise.climbing_aspect_id) ?? 'Unlisted aspect',
        exercises: [],
      };
      groups.push(current);
    }
    current.exercises.push(exercise);
  }

  return groups;
}

/** `power_endurance` -> `Power endurance`. Enough for a sanity-check screen; no label table. */
export function humanise(value: string): string {
  const spaced = value.split('_').join(' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * One phase's prescription as a readable run of terms.
 *
 * Every field except `sets` is nullable and the nulls are meaningful, not missing: a repeater
 * has `work_seconds` and no `reps`, a pull-up set the reverse, a circuit neither. So a null term
 * is **omitted**, never printed — "reps: null" reads as a data fault when it is the shape of the
 * protocol.
 */
export function prescriptionLine(prescription: Prescription): string {
  const terms: string[] = [
    `${String(prescription.sets)} ${prescription.sets === 1 ? 'set' : 'sets'}`,
  ];
  const { reps, work_seconds, rest_seconds, rest_between_sets_seconds } = prescription;
  const { intensity_pct, target_rpe } = prescription;

  if (reps !== null) terms.push(`${String(reps)} reps`);
  if (work_seconds !== null) terms.push(`${String(work_seconds)}s work`);
  if (rest_seconds !== null) terms.push(`${String(rest_seconds)}s rest`);
  if (rest_between_sets_seconds !== null) {
    terms.push(`${String(rest_between_sets_seconds)}s between sets`);
  }
  if (intensity_pct !== null) terms.push(`${String(intensity_pct)}% intensity`);
  if (target_rpe !== null) terms.push(`RPE ${String(target_rpe)}`);

  return terms.join(' · ');
}
