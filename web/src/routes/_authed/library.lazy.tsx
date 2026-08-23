import { createLazyFileRoute } from '@tanstack/react-router';

import type { LibraryExercise, Prescription } from '../../api/types';
import { useLibrary } from '../../library/api';
import {
  groupByAspect,
  humanise,
  nameIndex,
  namesOf,
  prescriptionLine,
} from '../../library/browse';
import { useVocabulary } from '../../profile/api';

/**
 * The exercise library, browsed. Deliberately minimal (Kilian's brief): a plain list grouped by
 * aspect, no detail route, no search, no filtering, no animation — enough to read the seeded
 * content and sanity-check it, styled but not designed.
 *
 * **Two reads, and neither is a new fetch.** `useLibrary` is the hook PR #10 added and this
 * screen is its first consumer — until now it was tree-shaken dead code. `useVocabulary` is
 * `profile/api.ts`'s, reused rather than reimplemented: the library payload sends only ids for
 * equipment, injury areas and aspects, and the vocabulary is where their names live. Both are
 * `staleTime: Infinity` and `enabled: isAuthenticated`, so arriving here costs at most one
 * request each per session and nothing on a revisit.
 *
 * **Not in the nav, and that is deliberate.** `_chrome.scss` carries a nav threshold table
 * measured term by term whose tightest regime is budgeted at 311px of content and clears a
 * 365px phone by ~6px; a sixth destination invalidates that arithmetic, and issue #60 is
 * already open about the nav on mobile. The only way in is the dashboard link.
 */
function Library() {
  const library = useLibrary();
  const vocabulary = useVocabulary();

  const exercises = library.data?.exercises;
  const vocab = vocabulary.data;

  function retry() {
    if (library.isLoadingError) void library.refetch();
    if (vocabulary.isLoadingError) void vocabulary.refetch();
  }

  // ⚠️ Gated on "there is nothing to show", NEVER on `isError`: query-core's error reducer sets
  // `status: "error"` even with data present, so a failed background refetch must not replace a
  // rendered list. `isLoadingError` is `isError && !hasData`, which is exactly this condition.
  // `refetchOnWindowFocus` is off app-wide, so the retry button is not decoration — without it a
  // failed first load is terminal until a manual reload.
  if (exercises === undefined || vocab === undefined) {
    const failed = library.isLoadingError || vocabulary.isLoadingError;
    return (
      <>
        <h1>Exercise library</h1>
        {failed ? (
          <>
            <p className="ct-app__status ct-app__status--error" role="alert">
              {/* Two reads, two failures, two sentences: naming the wrong one sends the reader
                  looking in the wrong place. */}
              {library.isLoadingError
                ? 'The exercise library could not be loaded.'
                : 'The equipment and injury lists could not be loaded.'}
            </p>
            <div className="ct-app__actions">
              <button
                type="button"
                className="ct-app__button ct-app__button--primary"
                onClick={retry}
              >
                Try again
              </button>
            </div>
          </>
        ) : (
          <p className="ct-app__status">Loading the exercise library…</p>
        )}
      </>
    );
  }

  const equipmentNames = nameIndex(vocab.equipment);
  const injuryNames = nameIndex(vocab.injury_areas);
  const groups = groupByAspect(exercises, nameIndex(vocab.climbing_aspects));

  return (
    <>
      <h1>Exercise library</h1>
      <p className="ct-app__lede">
        Everything the plan generator can draw on, in the order it sees it, grouped by the aspect of
        climbing each exercise trains.
      </p>
      {groups.map((group) => (
        <section key={group.aspectId}>
          <h2>
            {group.title} <span className="ct-app__badge">{String(group.exercises.length)}</span>
          </h2>
          <ul className="ct-app__stack">
            {group.exercises.map((exercise) => (
              <ExerciseCard
                key={exercise.id}
                exercise={exercise}
                equipmentNames={equipmentNames}
                injuryNames={injuryNames}
              />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

interface ExerciseCardProps {
  exercise: LibraryExercise;
  equipmentNames: ReadonlyMap<number, string>;
  injuryNames: ReadonlyMap<number, string>;
}

/**
 * One exercise, flat. `instructions` and `substitution_hint` are plain text rendered as React
 * children, which React escapes — no `dangerouslySetInnerHTML` and no markdown pass. `media_url`
 * is read by nothing here: it is NULL across the whole library today, and an unvalidated string
 * interpolated into `src`/`href` is the stored-XSS shape CLAUDE.md rules out.
 */
function ExerciseCard({ exercise, equipmentNames, injuryNames }: ExerciseCardProps) {
  const equipment = namesOf(exercise.equipment_ids, equipmentNames);
  const contraindicated = namesOf(exercise.contraindicated_injury_area_ids, injuryNames);

  return (
    <li className="ct-app__card">
      <h3>{exercise.name}</h3>
      <p className="ct-app__tags">
        <span className="ct-app__badge">{humanise(exercise.protocol_kind)}</span>
        {exercise.discipline !== null && (
          <span className="ct-app__badge">{humanise(exercise.discipline)}</span>
        )}
      </p>
      <p>{exercise.instructions}</p>
      <dl className="ct-app__facts">
        <dt>Equipment</dt>
        {/* `equipment_ids` is an AND set, so an empty list means "requires nothing and is always
            prescribable" — which is what replaces the `bodyweight` row that deliberately does not
            exist. It is an answer, not a gap, and must not read as one. */}
        <dd>{equipment.length === 0 ? 'None needed' : equipment.join(', ')}</dd>
        {contraindicated.length > 0 && (
          <>
            <dt>Avoid with</dt>
            <dd>{contraindicated.join(', ')}</dd>
          </>
        )}
        {/* ⚠️ A NULL `substitution_hint` is a SAFETY boundary, not missing content: every finger
            loading protocol has one, on purpose (`server/domain/exercises.py`). Absent means
            silent — never a placeholder that invites the reader to invent an alternative. */}
        {exercise.substitution_hint !== null && (
          <>
            <dt>Substitution</dt>
            <dd>{exercise.substitution_hint}</dd>
          </>
        )}
      </dl>
      {exercise.prescriptions.length > 0 && (
        <ul className="ct-app__terms">
          {exercise.prescriptions.map((prescription: Prescription) => (
            <li key={prescription.phase}>
              <strong>{humanise(prescription.phase)}</strong> {prescriptionLine(prescription)}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export const Route = createLazyFileRoute('/_authed/library')({ component: Library });
