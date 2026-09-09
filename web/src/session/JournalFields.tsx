import type { RefObject } from 'react';

import type { JournalFieldValues } from './journal';
import {
  BODY_WEIGHT_MAX,
  BODY_WEIGHT_MIN,
  JOURNAL_BODY_MAX,
  WELLBEING_VALUES,
  bodyWeightHint,
} from './journal';

/** The diary form's CONTROLS, off a draft plus one handler. Two callers with two different save
 *  paths — the session box and the diary's edit overlay — so neither owns the fields. */

/** Ids are per-instance so two of these could sit on one screen without colliding labels. */
export function JournalFields({
  idPrefix,
  values,
  showBodyMetrics,
  bodyRef,
  onChange,
}: {
  idPrefix: string;
  values: JournalFieldValues;
  showBodyMetrics: boolean;
  bodyRef?: RefObject<HTMLTextAreaElement | null>;
  onChange: (patch: Partial<JournalFieldValues>) => void;
}) {
  const weightHint = bodyWeightHint(values.bodyWeightKg);

  return (
    <>
      <label className="ct-app__field" htmlFor={`${idPrefix}-body`}>
        How it went
        <textarea
          id={`${idPrefix}-body`}
          ref={bodyRef}
          className="ct-app__input"
          rows={4}
          maxLength={JOURNAL_BODY_MAX}
          placeholder="Fingers felt tweaky, backing off the crimps this week…"
          value={values.body}
          onChange={(event) => onChange({ body: event.target.value })}
        />
      </label>

      <p className="ct-app__muted">On the three below, 1 is the worst it gets and 5 the best.</p>
      <ScoreField
        id={`${idPrefix}-feel`}
        label="Energy"
        value={values.feel}
        onPick={(feel) => onChange({ feel })}
      />
      <ScoreField
        id={`${idPrefix}-sleep`}
        label="Last night's sleep"
        value={values.sleepQuality}
        onPick={(sleepQuality) => onChange({ sleepQuality })}
      />
      <ScoreField
        id={`${idPrefix}-skin`}
        label="Skin"
        value={values.skin}
        onPick={(skin) => onChange({ skin })}
      />

      {showBodyMetrics ? (
        <>
          <label className="ct-app__field" htmlFor={`${idPrefix}-weight`}>
            Weight today (kg)
            <input
              id={`${idPrefix}-weight`}
              className="ct-app__input"
              type="number"
              inputMode="decimal"
              step="0.1"
              min={BODY_WEIGHT_MIN}
              max={BODY_WEIGHT_MAX}
              placeholder="e.g. 71.4"
              value={values.bodyWeightKg}
              onChange={(event) => onChange({ bodyWeightKg: event.target.value })}
            />
          </label>
          {weightHint === null ? (
            <p className="ct-app__muted">
              Just what the scale said today. It is recorded, never scored — nothing in this app
              asks you to change it.
            </p>
          ) : (
            <p className="ct-app__error">{weightHint}</p>
          )}
        </>
      ) : null}
    </>
  );
}

/** One 1-5 select on the shared `ct-app__select` primitive — `SessionRpe`'s markup exactly,
 *  because five buttons in a row is a wall on a phone and the chevron is drawn once. */
function ScoreField({
  id,
  label,
  value,
  onPick,
}: {
  id: string;
  label: string;
  value: number | null;
  onPick: (value: number | null) => void;
}) {
  return (
    <label className="ct-app__field" htmlFor={id}>
      {label}
      <span className="ct-app__select">
        <select
          id={id}
          className="ct-app__input"
          value={value ?? ''}
          onChange={(event) => {
            const picked = Number(event.target.value);
            onPick(Number.isFinite(picked) && picked > 0 ? picked : null);
          }}
        >
          <option value="">Rather not say</option>
          {WELLBEING_VALUES.map((score) => (
            <option key={score} value={score}>
              {String(score)}
            </option>
          ))}
        </select>
      </span>
    </label>
  );
}
