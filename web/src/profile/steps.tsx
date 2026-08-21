import { useId } from 'react';

import type { Vocabulary } from '../api/types';
import type { OnboardingStep } from './completion';
import { DEFAULT_ASPECT_SCORE, type ProfileDraft } from './draft';

/**
 * The five field groups, and they are the ONLY copy of these fields.
 *
 * Onboarding (`routes/_authed/onboarding.lazy.tsx`) renders one at a time behind a
 * stepper; the profile editor (`routes/_authed/profile.lazy.tsx`) renders all five as
 * sections. One set of fields, two entry points — building the flow twice is how the
 * editor and the wizard end up validating differently.
 *
 * Every group is **presentational**: it reads a draft, reports a change, and knows nothing
 * about requests, steps or completion. Persistence belongs to the container, which is what
 * lets the wizard save on "Continue" and the editor save per section.
 *
 * ## Closed inputs, everywhere
 *
 * There is exactly one free-text field in this whole flow (an injury note, bounded at 500
 * characters server-side). Everything else is a select, a checkbox or a slider over a
 * seeded vocabulary, submitted as ids — CLAUDE.md's cheapest injection defence is having
 * nothing to inject into.
 *
 * Per the testing policy these are not unit-tested: they render the props they were given.
 * What is tested is the part that can be wrong invisibly — `patchFor` in `draft.ts`, which
 * decides the exact key set each step sends.
 */

export interface FieldProps {
  draft: ProfileDraft;
  vocabulary: Vocabulary;
  /** Patch the draft. The container owns the draft and decides when to persist. */
  onChange: (change: Partial<ProfileDraft>) => void;
}

/** Monday first, matching `user_profile.available_weekdays` bit 0 = Monday. */
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const SESSIONS_PER_WEEK = [1, 2, 3, 4, 5, 6, 7];

/** The 1-5 self-rating scale, in words. A bare number is not a self-assessment. */
const SCORE_LABELS = ['Weakest', 'Weak', 'Average', 'Strong', 'Strongest'];

function toggle(ids: number[], id: number): number[] {
  return ids.includes(id) ? ids.filter((current) => current !== id) : [...ids, id];
}

export function TargetGradeFields({ draft, vocabulary, onChange }: FieldProps) {
  const base = useId();
  const system = vocabulary.grade_systems.find((entry) => entry.id === draft.gradeSystemId);
  const grades = vocabulary.grades.filter((grade) => grade.grade_system_id === draft.gradeSystemId);

  return (
    <>
      <p className="ct-app__muted">
        The grade you are training towards. Everything the app plans refers back to it.
      </p>

      <label className="ct-app__field" htmlFor={`${base}-system`}>
        Grade scale
        <select
          id={`${base}-system`}
          className="ct-app__input"
          value={draft.gradeSystemId ?? ''}
          onChange={(event) =>
            // The scale carries the discipline, so changing it invalidates the choice:
            // a Font 7A target and a French 7a target are not the same goal, and the
            // server derives the profile's discipline from whichever id is sent.
            onChange({ gradeSystemId: Number(event.target.value), targetGradeId: null })
          }
        >
          {vocabulary.grade_systems.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.name}
            </option>
          ))}
        </select>
      </label>

      <label className="ct-app__field" htmlFor={`${base}-grade`}>
        Target grade
        <select
          id={`${base}-grade`}
          className="ct-app__input"
          value={draft.targetGradeId ?? ''}
          onChange={(event) => onChange({ targetGradeId: Number(event.target.value) })}
        >
          <option value="">Choose a grade</option>
          {grades.map((grade) => (
            <option key={grade.id} value={grade.id}>
              {grade.label}
            </option>
          ))}
        </select>
      </label>

      {system !== undefined && (
        <p className="ct-app__caption">
          {system.discipline === 'boulder' ? 'Bouldering' : 'Sport climbing'} — boulder and rope
          grades are tracked separately.
        </p>
      )}
    </>
  );
}

export function AvailabilityFields({ draft, onChange }: FieldProps) {
  const base = useId();

  return (
    <>
      <p className="ct-app__muted">How much time you actually have. Be honest, not ambitious.</p>

      <label className="ct-app__field" htmlFor={`${base}-sessions`}>
        Sessions per week
        <select
          id={`${base}-sessions`}
          className="ct-app__input"
          value={draft.sessionsPerWeek ?? ''}
          // ⚠️ The empty option is load-bearing, not tidiness. Revision 0005 exists to stop
          // the server inventing `sessions_per_week = 3`; a select that opened on 3 would put
          // that placeholder back from the client and `patchFor` would send it as if the user
          // had chosen it. Same shape, same reason, as the grade picker's "Choose a grade".
          onChange={(event) =>
            onChange({
              sessionsPerWeek: event.target.value === '' ? null : Number(event.target.value),
            })
          }
        >
          <option value="">Choose a number</option>
          {SESSIONS_PER_WEEK.map((count) => (
            <option key={count} value={count}>
              {count}
            </option>
          ))}
        </select>
      </label>

      <fieldset className="ct-app__fieldset">
        <legend>Days you can train</legend>
        <div className="ct-app__choices">
          {WEEKDAYS.map((day, bit) => {
            const checked = (draft.availableWeekdays & (1 << bit)) !== 0;
            return (
              <label className="ct-app__choice" key={day} htmlFor={`${base}-day-${String(bit)}`}>
                <input
                  id={`${base}-day-${String(bit)}`}
                  type="checkbox"
                  checked={checked}
                  onChange={() =>
                    onChange({ availableWeekdays: draft.availableWeekdays ^ (1 << bit) })
                  }
                />
                {day}
              </label>
            );
          })}
        </div>
      </fieldset>
    </>
  );
}

export function EquipmentFields({ draft, vocabulary, onChange }: FieldProps) {
  const base = useId();

  return (
    <>
      {/* ⚠️ NOT a gear inventory — facilities, gear and rock, which is why the list carries
          `outdoor_boulders` and `outdoor_routes` (Kilian, 2026-08-21). Bodyweight work is
          assumed rather than ticked: there is no `bodyweight` row, and an exercise that needs
          no equipment is always prescribable. Saying that here is what makes an empty
          selection read as a real answer instead of an unfinished form. */}
      <p className="ct-app__muted">
        Anywhere you climb and anything you train with — indoor walls, real rock, gear at home. The
        plan only prescribes what you can actually get to.
      </p>
      {/* ⚠️ The second sentence is a SAFETY boundary and is not optional (Kilian,
          2026-08-21). Improvised load is fine — a backpack, bottles, a rock — but improvised
          FINGER loading (home-made edges, door frames, towel hangs) is the single most
          injury-prone thing a climber can rig, and suggesting it would contradict the whole
          reason `exercise_contraindication` exists. Static copy only: no `improvised_weight`
          row, no substitution mapping. Per-exercise hints belong on the exercise in PR #10,
          next to the movement they apply to. */}
      <p className="ct-app__caption">
        Bodyweight work is always included, so it is fine to tick nothing at all — and most
        exercises that add weight work with whatever is to hand, like a loaded backpack or a couple
        of water bottles. Finger-strength protocols need a real edge, so those are left out rather
        than improvised.
      </p>

      <fieldset className="ct-app__fieldset">
        <legend>What you can train on</legend>
        <div className="ct-app__choices">
          {vocabulary.equipment.map((item) => (
            <label
              className="ct-app__choice ct-app__choice--described"
              key={item.id}
              htmlFor={`${base}-${String(item.id)}`}
            >
              <input
                id={`${base}-${String(item.id)}`}
                type="checkbox"
                checked={draft.equipmentIds.includes(item.id)}
                onChange={() => onChange({ equipmentIds: toggle(draft.equipmentIds, item.id) })}
              />
              {/* The description is rendered, not just fetched. It is the whole point of the
                  reworded copy — "An INDOOR wall climbed without a rope" versus "Bouldering
                  on real rock" is what tells a rock climber which box is theirs — and until
                  now it reached the API payload and the contract test and no user at all.
                  Inside the <label>, so it is part of the control's accessible name and a tap
                  anywhere on the row still toggles the box. */}
              <span className="ct-app__choice-text">
                {item.name}
                <span className="ct-app__choice-hint">{item.description}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    </>
  );
}

export function AspectFields({ draft, vocabulary, onChange }: FieldProps) {
  const base = useId();

  return (
    <>
      <p className="ct-app__muted">
        Rate yourself from 1 to 5. There are no wrong answers — this is what the plan uses to decide
        what to work on first.
      </p>

      {vocabulary.climbing_aspects.map((aspect) => {
        const score = draft.aspectScores[aspect.id] ?? DEFAULT_ASPECT_SCORE;
        const id = `${base}-${String(aspect.id)}`;
        return (
          <div className="ct-app__scale" key={aspect.id}>
            <label className="ct-app__field" htmlFor={id}>
              {aspect.name}
              <input
                id={id}
                type="range"
                min={1}
                max={5}
                step={1}
                value={score}
                onChange={(event) =>
                  onChange({
                    aspectScores: {
                      ...draft.aspectScores,
                      [aspect.id]: Number(event.target.value),
                    },
                  })
                }
              />
            </label>
            {/* The number AND the word: a slider whose value is only a thumb position is
                unreadable, and colour or position alone is not information. */}
            <p className="ct-app__scale-value">
              {score} — {SCORE_LABELS[score - 1]}
            </p>
            <p className="ct-app__caption">{aspect.description}</p>
          </div>
        );
      })}
    </>
  );
}

export function InjuryFields({ draft, vocabulary, onChange }: FieldProps) {
  const base = useId();

  return (
    <>
      <p className="ct-app__muted">
        Anything currently bothering you. The plan withholds exercises that load an injured area —
        leave this empty if there is nothing.
      </p>

      <fieldset className="ct-app__fieldset">
        <legend>Current injuries</legend>
        <div className="ct-app__choices">
          {vocabulary.injury_areas.map((area) => {
            const flagged = area.id in draft.injuries;
            return (
              <label
                className="ct-app__choice"
                key={area.id}
                htmlFor={`${base}-${String(area.id)}`}
              >
                <input
                  id={`${base}-${String(area.id)}`}
                  type="checkbox"
                  checked={flagged}
                  onChange={() => {
                    const next = { ...draft.injuries };
                    if (flagged) delete next[area.id];
                    else next[area.id] = '';
                    onChange({ injuries: next });
                  }}
                />
                {area.name}
              </label>
            );
          })}
        </div>
      </fieldset>

      {vocabulary.injury_areas
        .filter((area) => area.id in draft.injuries)
        .map((area) => (
          <label
            className="ct-app__field"
            key={area.id}
            htmlFor={`${base}-note-${String(area.id)}`}
          >
            {area.name} — anything worth noting (optional)
            <input
              id={`${base}-note-${String(area.id)}`}
              className="ct-app__input"
              type="text"
              // The one free-text field in the flow. Bounded here so a paste cannot be
              // unbounded, and bounded again server-side (`server/fields.py::InjuryNote`).
              maxLength={500}
              value={draft.injuries[area.id] ?? ''}
              onChange={(event) =>
                onChange({ injuries: { ...draft.injuries, [area.id]: event.target.value } })
              }
            />
          </label>
        ))}
    </>
  );
}

const FIELDS: Record<OnboardingStep, (props: FieldProps) => React.ReactElement> = {
  targetGrade: TargetGradeFields,
  availability: AvailabilityFields,
  equipment: EquipmentFields,
  aspects: AspectFields,
  injuries: InjuryFields,
};

/** One step's fields. The dispatcher both entry points share. */
export function StepFields({ step, ...props }: FieldProps & { step: OnboardingStep }) {
  const Fields = FIELDS[step];
  return <Fields {...props} />;
}
