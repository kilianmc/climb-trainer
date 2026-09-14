/* One exercise in full, as the PANEL of a `<details>` the host owns. Inline, not an overlay:
   an expanding row leaves the plan's and the session player's own state alone. */
import type { LibraryExercise, ReferenceRow, Vocabulary } from '../api/types';
import { publicUrl } from '../publicUrl';
import { IconArtPending } from '../ui/icons';

import { humanise, nameIndex, namesOf, prescriptionTerms, protocolBadge } from './browse';
import { precautionsFor } from './equipmentPrecautions';
import { ICON_SIDE, iconFor, iconPath } from './exerciseIcons';
import { intensityAnchor } from './intensity';

/** What a detail reads that is not on the exercise row itself. */
export interface ExerciseVocabulary {
  /** The whole row, not just the name: the aspect supplies its own "why" and the icon's key. */
  readonly aspects: ReadonlyMap<number, ReferenceRow>;
  readonly equipmentNames: ReadonlyMap<number, string>;
  /** `id -> equipment.key`, which is what `equipmentPrecautions.ts` is authored against. */
  readonly equipmentKeys: ReadonlyMap<number, string>;
  readonly injuryNames: ReadonlyMap<number, string>;
  /** `id -> name` over the whole library, so a progression link resolves to a name. */
  readonly exerciseNames: ReadonlyMap<number, string>;
}

/** Built ONCE per screen and passed down, for `blueprint.ts::exercisesByKey`'s reason: the plan
 *  renders up to 672 rows and a per-row index over 106 exercises is the quadratic one. */
export function exerciseVocabulary(
  vocabulary: Vocabulary,
  exercises: readonly LibraryExercise[],
): ExerciseVocabulary {
  return {
    aspects: new Map(vocabulary.climbing_aspects.map((row) => [row.id, row])),
    equipmentNames: nameIndex(vocabulary.equipment),
    equipmentKeys: new Map(vocabulary.equipment.map((row) => [row.id, row.key])),
    injuryNames: nameIndex(vocabulary.injury_areas),
    exerciseNames: nameIndex(exercises),
  };
}

export interface ExerciseDetailProps {
  exercise: LibraryExercise;
  vocabulary: ExerciseVocabulary;
  compactShot?: boolean;
}

/** ⚠️ A FRAGMENT of `<details>`' own children: `ct-app__disclosure` spaces it, the element
 *  carries keyboard and expanded state, and the name is the summary's, not a second copy. */
export function ExerciseDetail({ exercise, vocabulary, compactShot = false }: ExerciseDetailProps) {
  const aspect = vocabulary.aspects.get(exercise.climbing_aspect_id) ?? null;
  const equipment = namesOf(exercise.equipment_ids, vocabulary.equipmentNames);
  const contraindicated = namesOf(exercise.contraindicated_injury_area_ids, vocabulary.injuryNames);
  const badge = protocolBadge(exercise.protocol_kind);
  const anchor = intensityAnchor(exercise.protocol_kind);
  const icon = iconFor(exercise.key, aspect?.key ?? null);
  // ⚠️ Derived HERE, not passed in: a precaution a host can forget to pass is a precaution
  // that renders on three screens out of four; `equipmentPrecautions.ts` is the one authority.
  const precautions = precautionsFor(exercise.equipment_ids, vocabulary.equipmentKeys);

  // ⚠️ The DIRECTION. "X is a progression of Y" means Y is the easier one, so
  // `progression_of_id` is the EASIER version and `regression_of_id` is the harder.
  const easier =
    exercise.progression_of_id === null
      ? null
      : vocabulary.exerciseNames.get(exercise.progression_of_id);
  const harder =
    exercise.regression_of_id === null
      ? null
      : vocabulary.exerciseNames.get(exercise.regression_of_id);

  return (
    <>
      <div className="ct-app__exhead">
        <div className="ct-app__exheadtext">
          {/* ⚠️ The badge is DROPPED where `humanise` would render "Other": twelve exercises
              have that kind and the word is worse than absent. */}
          {(badge !== null || aspect !== null || exercise.discipline !== null) && (
            <p className="ct-app__tags">
              {aspect !== null && <span className="ct-app__badge">{aspect.name}</span>}
              {badge !== null && <span className="ct-app__badge">{badge}</span>}
              {exercise.discipline !== null && (
                <span className="ct-app__badge">{humanise(exercise.discipline)}</span>
              )}
            </p>
          )}
          {/* The aspect's own "why", in the voice onboarding already reads it in
              (`profile/steps.tsx`): the description as a caption, unedited. */}
          {aspect !== null && <p className="ct-app__caption">{aspect.description}</p>}
        </div>
        {/* ⚠️ Twenty-one exercises across three aspects have no art, so the placeholder is a
            NORMAL state: a decorative mark plus real text, never an empty box. */}
        <p className={compactShot ? 'ct-app__exshot ct-app__exshot--compact' : 'ct-app__exshot'}>
          {icon === null ? (
            <>
              <IconArtPending className="ct-app__exshotmark" />
              <span>No icon yet</span>
            </>
          ) : (
            <img
              className="ct-app__exshotimg"
              src={publicUrl(iconPath(icon.slug))}
              alt={icon.alt}
              width={ICON_SIDE}
              height={ICON_SIDE}
              loading="lazy"
              decoding="async"
            />
          )}
        </p>
      </div>

      {/* Plain text as React children, which React escapes. No markdown pass, and
          `dangerouslySetInnerHTML` is ruled out repo-wide. */}
      <p className="ct-app__prose">{exercise.instructions}</p>

      {precautions.length > 0 && (
        <>
          <h3>Before you load</h3>
          {precautions.map((precaution) => (
            <p className="ct-app__notice" key={precaution}>
              {precaution}
            </p>
          ))}
        </>
      )}

      <dl className="ct-app__facts">
        <dt>Equipment</dt>
        {/* `equipment_ids` is an AND set, so empty means "requires nothing and is always
            prescribable". It is an answer, not a gap, and must not read as one. */}
        <dd>{equipment.length === 0 ? 'None needed' : equipment.join(', ')}</dd>
        {contraindicated.length > 0 && (
          <>
            <dt>Avoid with</dt>
            <dd>{contraindicated.join(', ')}</dd>
          </>
        )}
        {/* ⚠️ A NULL `substitution_hint` is a SAFETY boundary, not missing content: absent
            means silent, never a placeholder inviting the reader to improvise a finger edge. */}
        {exercise.substitution_hint !== null && (
          <>
            <dt>Substitution</dt>
            <dd>{exercise.substitution_hint}</dd>
          </>
        )}
      </dl>

      {/* Absent is silent here for the same reason: 86 of 106 have neither link, and a
          placeholder would invite the reader to invent the exercise it does not name. */}
      {(easier !== undefined && easier !== null) || (harder !== undefined && harder !== null) ? (
        <>
          <h3>Where it sits</h3>
          <ul className="ct-app__exlinks">
            {easier !== undefined && easier !== null && (
              <li>
                <strong>Easier version</strong> {easier}
              </li>
            )}
            {harder !== undefined && harder !== null && (
              <li>
                <strong>Harder version</strong> {harder}
              </li>
            )}
          </ul>
        </>
      ) : null}

      {exercise.prescriptions.length > 0 && (
        <>
          <h3>In each phase</h3>
          <ul className="ct-app__terms">
            {exercise.prescriptions.map((prescription) => (
              <li key={prescription.phase}>
                <strong>{humanise(prescription.phase)}</strong>{' '}
                {prescriptionTerms(prescription, anchor).join(' · ')}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
