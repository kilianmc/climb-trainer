import { useId, useState } from 'react';

import type { Discipline, Vocabulary } from '../api/types';
import { IconBandage, IconCalendar, IconSliders, IconTarget } from '../ui/icons';
import { STEP_TITLES, type OnboardingStep } from './completion';
import { compareToGoal, gradesForSystem, type GoalComparison } from './grades';
import { DEFAULT_ASPECT_SCORE, STRENGTH_SCORE, WEAKNESS_SCORE, type ProfileDraft } from './draft';

/**
 * The four field groups, and they are the ONLY copy of these fields.
 *
 * Onboarding (`routes/_authed/onboarding.lazy.tsx`) and the profile editor
 * (`routes/_authed/profile.lazy.tsx`) render the same groups behind the same stepper, one
 * card at a time — one interaction model, not two (issue #54). Building the flow twice is
 * how the editor and the wizard end up validating differently.
 *
 * Every group is **presentational**: it reads a draft, reports a change, and knows nothing
 * about requests, steps or completion. Persistence belongs to the container, which is what
 * lets the wizard save on "Continue" and the editor save once at the end.
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

/**
 * ⚠️ Not cosmetic. The ordinal ladders are **disjoint by discipline** and
 * `server/domain/grades.py::convert` raises `CrossDisciplineError`, so a user who picks
 * French 6c+ while thinking in boulder grades has set a goal the generator can never
 * compare against their climbing (issue #54). The discipline therefore rides on every
 * label, not just in a caption underneath.
 */
const DISCIPLINE_LABELS: Record<Discipline, string> = {
  boulder: 'boulder',
  sport: 'sport',
};

/**
 * The one select wrapper, so the arrow is drawn once.
 *
 * The native arrow is the platform's, at the platform's size and colour, and it read as
 * borrowed next to controls built on this app's tokens. `appearance: none` plus a
 * `currentColor` chevron drawn in CSS (`_profile.scss`) keeps it inside the design system
 * and inherits the field's own colour in both schemes — no image, which also means nothing
 * for `img-src 'self' data:` to allow.
 */
function SelectField({
  id,
  label,
  value,
  onChange,
  children,
}: {
  id: string;
  label: string;
  value: number | '';
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="ct-app__field" htmlFor={id}>
      {label}
      <span className="ct-app__select">
        <select
          id={id}
          className="ct-app__input"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {children}
        </select>
      </span>
    </label>
  );
}

export function TargetGradeFields({ draft, vocabulary, onChange }: FieldProps) {
  const base = useId();
  const system = vocabulary.grade_systems.find((entry) => entry.id === draft.gradeSystemId);
  // Floored at the base of 5 — see `grades.ts` for the rule and why it is not a seed change.
  const grades = gradesForSystem(vocabulary, draft.gradeSystemId);

  return (
    <>
      <p className="ct-app__muted">
        The grade you are training towards. Everything the app plans refers back to it.
      </p>

      <SelectField
        id={`${base}-system`}
        label="Grade scale"
        value={draft.gradeSystemId ?? ''}
        // The scale carries the discipline, so changing it invalidates both choices: a Font
        // 7A target and a French 7a target are not the same goal, the server derives the
        // profile's discipline from whichever id is sent, and a current grade on the other
        // ladder cannot be compared with either.
        onChange={(value) =>
          onChange({ gradeSystemId: Number(value), targetGradeId: null, currentGradeId: null })
        }
      >
        {vocabulary.grade_systems.map((entry) => (
          <option key={entry.id} value={entry.id}>
            {entry.name} ({DISCIPLINE_LABELS[entry.discipline]})
          </option>
        ))}
      </SelectField>

      <SelectField
        id={`${base}-grade`}
        label="Target grade"
        value={draft.targetGradeId ?? ''}
        onChange={(value) => onChange({ targetGradeId: Number(value) })}
      >
        <option value="">Choose a grade</option>
        {grades.map((grade) => (
          <option key={grade.id} value={grade.id}>
            {grade.label}
          </option>
        ))}
      </SelectField>

      {system !== undefined && (
        <p className="ct-app__caption">
          {system.discipline === 'boulder' ? 'Bouldering' : 'Sport climbing'} — boulder and rope
          grades sit on separate ladders, so the plan can only compare a goal with climbing of the
          same kind.
        </p>
      )}
    </>
  );
}

/**
 * Availability — **"any day" is the default**, with the specific-day picker behind a disclosure
 * (Kilian, round 5). The same shape as the injuries step, for the same reason: the answer most
 * people would give is already there, and the seven checkboxes are for the people it is wrong
 * for.
 *
 * ⚠️ **The help text stays, and it matters MORE now.** Sessions-per-week and weekdays read like
 * one question, and with "any day" pre-selected a reader could conclude the second question has
 * been answered for them. It has: the answer is "all of them", and the sentence says why that is
 * a different fact from how often they train.
 *
 * Mutually exclusive with picking days, in both directions, and never destructive: ticking "any
 * day" leaves the mask in the draft and stops sending it, so un-ticking restores exactly what was
 * chosen, and collapsing the disclosure touches nothing at all.
 */
export function AvailabilityFields({ draft, onChange }: FieldProps) {
  const base = useId();
  const chosenDays = WEEKDAYS.filter(
    (_day, bit) => !draft.allWeekdays && (draft.availableWeekdays & (1 << bit)) !== 0,
  );
  // Read once, at mount: bound to the live count it would slam the panel shut the moment the
  // user un-ticked their last day. The card remounts per step, so "at mount" is "when they got
  // here", which is the question this asks.
  const [openAtMount] = useState(() => chosenDays.length > 0);

  return (
    <>
      <p className="ct-app__muted">How much time you actually have. Be honest, not ambitious.</p>

      <SelectField
        id={`${base}-sessions`}
        label="Sessions per week"
        value={draft.sessionsPerWeek ?? ''}
        // ⚠️ The empty option is load-bearing, not tidiness. Revision 0005 exists to stop
        // the server inventing `sessions_per_week = 3`; a select that opened on 3 would put
        // that placeholder back from the client and `patchFor` would send it as if the user
        // had chosen it. Same shape, same reason, as the grade picker's "Choose a grade".
        onChange={(value) => onChange({ sessionsPerWeek: value === '' ? null : Number(value) })}
      >
        <option value="">Choose a number</option>
        {SESSIONS_PER_WEEK.map((count) => (
          <option key={count} value={count}>
            {count}
          </option>
        ))}
      </SelectField>

      <label className="ct-app__choice ct-app__choice--span" htmlFor={`${base}-any-day`}>
        <input
          id={`${base}-any-day`}
          type="checkbox"
          checked={draft.allWeekdays}
          onChange={() => onChange({ allWeekdays: !draft.allWeekdays })}
        />
        Any day — I can fit training around the week
      </label>

      <details className="ct-app__disclosure" open={openAtMount}>
        <summary>
          {chosenDays.length === 0
            ? 'Only certain days work — pick them'
            : `Only certain days work (${String(chosenDays.length)} selected)`}
        </summary>

        <fieldset className="ct-app__fieldset">
          <legend>Days you can train</legend>
          <div className="ct-app__choices">
            {WEEKDAYS.map((day, bit) => {
              const checked = !draft.allWeekdays && (draft.availableWeekdays & (1 << bit)) !== 0;
              return (
                <label className="ct-app__choice" key={day} htmlFor={`${base}-day-${String(bit)}`}>
                  <input
                    id={`${base}-day-${String(bit)}`}
                    type="checkbox"
                    checked={checked}
                    onChange={() =>
                      // The other half of the exclusion: naming days is not "any day".
                      onChange({
                        availableWeekdays: draft.availableWeekdays ^ (1 << bit),
                        allWeekdays: false,
                      })
                    }
                  />
                  {day}
                </label>
              );
            })}
          </div>
        </fieldset>
      </details>

      {/* The two questions sound like one, and until #54 nothing said why both are asked. */}
      <p className="ct-app__caption">
        These are two different answers. The number is how often you train; the days are when you
        could — three sessions across five possible days is what lets the plan pick the ones that
        rest you properly.
      </p>
    </>
  );
}

/**
 * Where the climber is now: a current grade, one strength, one weakness — and the eight
 * sliders kept behind a disclosure.
 *
 * ⚠️ **This replaced eight 1-5 sliders as the step's question** (issue #54). Eight
 * self-ratings were hard to answer honestly and were the step most likely to hand the
 * generator garbage. "I climb 6c and I want 7a" is a far stronger signal than any
 * self-rating: a 6c climber is measurably closer to 7a than a 6a climber is.
 *
 * The current grade is read on the **same scale as the goal**, which is the discipline
 * constraint made structural rather than explained — there is no control here that can
 * select the other ladder.
 *
 * All three are real columns since `0006`, and picking a strength or a weakness also writes
 * that aspect's rating — so the eight scores and the two picks can never disagree. See
 * `UserAspectRating`'s docstring for why both exist.
 */
export function ClimbingNowFields({ draft, vocabulary, onChange }: FieldProps) {
  const base = useId();
  const system = vocabulary.grade_systems.find((entry) => entry.id === draft.gradeSystemId);
  const grades = gradesForSystem(vocabulary, draft.gradeSystemId);
  const target = vocabulary.grades.find((grade) => grade.id === draft.targetGradeId);
  const aspects = vocabulary.climbing_aspects;
  // `null` unless both grades exist AND sit on the same ladder — the ordinals are banded per
  // discipline and are meaningless across one.
  const versusGoal = compareToGoal(vocabulary, draft.currentGradeId, draft.targetGradeId);
  const warned = versusGoal === 'above' || versusGoal === 'equal';

  /** A pick seeds its aspect's slider and releases the one it replaced. */
  function pick(field: 'strengthAspectId' | 'weaknessAspectId', id: number) {
    const scores = { ...draft.aspectScores };
    const previous = draft[field];
    if (previous !== null) scores[previous] = DEFAULT_ASPECT_SCORE;
    const isStrength = field === 'strengthAspectId';
    scores[id] = isStrength ? STRENGTH_SCORE : WEAKNESS_SCORE;
    onChange({
      ...(isStrength ? { strengthAspectId: id } : { weaknessAspectId: id }),
      aspectScores: scores,
    });
  }

  return (
    <>
      <p className="ct-app__muted">
        What you climb today, and the two things you would name first about your climbing. This is
        what the plan works from.
      </p>

      <SelectField
        id={`${base}-current`}
        label={system === undefined ? 'Current grade' : `Current grade (${system.name})`}
        value={draft.currentGradeId ?? ''}
        onChange={(value) => onChange({ currentGradeId: value === '' ? null : Number(value) })}
      >
        <option value="">Choose a grade</option>
        {grades.map((grade) => (
          <option key={grade.id} value={grade.id}>
            {grade.label}
          </option>
        ))}
      </SelectField>

      {/* ⚠️ **ONE line in this slot, which changes character** (Kilian, round 5). It was a
          helper line plus a separate notice underneath, and two messages arguing about the same
          two fields is how a form ends up contradicting itself. So the copy is replaced and the
          colour goes with it.
          Still not an error: amber rather than `--ct-danger`, `role="status"` rather than
          `alert`, nothing disabled and nothing corrected — a climber may enter whatever they
          climb. The region is in the DOM at every state, which is what makes the change
          announce; one added at the same moment as its text frequently is not. */}
      <p
        className={warned ? 'ct-app__caption ct-app__caption--warning' : 'ct-app__caption'}
        role="status"
      >
        {goalLine(target?.label, versusGoal)}
      </p>

      <SelectField
        id={`${base}-strength`}
        label="Your strongest side"
        value={draft.strengthAspectId ?? ''}
        onChange={(value) => {
          if (value === '') onChange({ strengthAspectId: null });
          else pick('strengthAspectId', Number(value));
        }}
      >
        <option value="">Choose one</option>
        {aspects
          .filter((aspect) => aspect.id !== draft.weaknessAspectId)
          .map((aspect) => (
            <option key={aspect.id} value={aspect.id}>
              {aspect.name}
            </option>
          ))}
      </SelectField>

      <SelectField
        id={`${base}-weakness`}
        label="What holds you back most"
        value={draft.weaknessAspectId ?? ''}
        onChange={(value) => {
          if (value === '') onChange({ weaknessAspectId: null });
          else pick('weaknessAspectId', Number(value));
        }}
      >
        <option value="">Choose one</option>
        {aspects
          .filter((aspect) => aspect.id !== draft.strengthAspectId)
          .map((aspect) => (
            <option key={aspect.id} value={aspect.id}>
              {aspect.name}
            </option>
          ))}
      </SelectField>

      <details className="ct-app__disclosure">
        <summary>Rate all eight, if you want to be specific</summary>
        <p className="ct-app__caption">
          Optional. Your two answers above are already set here; the rest start in the middle and
          are saved exactly as you leave them.
        </p>

        {aspects.map((aspect) => {
          const score = draft.aspectScores[aspect.id] ?? DEFAULT_ASPECT_SCORE;
          const id = `${base}-${String(aspect.id)}`;
          // "Committed" for a slider means "off the default", which is the only test available:
          // neither CSS nor this component can know whether a thumb was dragged. It is true for a
          // value written by the strength/weakness picks too, which is correct — those ARE
          // answers.
          const set = score !== DEFAULT_ASPECT_SCORE;
          return (
            <div
              className={set ? 'ct-app__scale ct-app__scale--set' : 'ct-app__scale'}
              key={aspect.id}
            >
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
      </details>
    </>
  );
}

/**
 * Injuries — **"nothing is hurting" is the DEFAULT answer**, and the list is behind a
 * disclosure (Kilian, rounds 2 and 3).
 *
 * Most people are not injured, so the step opens on the answer most people would give and the
 * seven areas stay out of the way until someone says otherwise — the same disclosure pattern
 * as "rate all eight" on the previous card.
 *
 * ⚠️ **A default tick is not an answer, and this is the boundary that keeps the bar honest.**
 * Nothing is credited by rendering: `injuries_reviewed_at` is stamped only by the `PATCH` that
 * `patchFor` builds, and that request is only ever sent for a step the user has actually been
 * on — the wizard sends the card it is leaving, and the editor sends only the cards it showed
 * (`patchForAll(draft, visited)`). A tick nobody looked at reaches the database never.
 *
 * `injuries_reviewed_at` is why no column is needed for this ("a step needs a `*_reviewed_at`
 * column exactly when zero rows is a legitimate answer"): ticked and submitted sends
 * `injuries: []`, which stamps it, and `draftFrom` reads the pair back.
 *
 * Mutually exclusive with a listed injury in both directions, and **never destructive**:
 * ticking None leaves the notes in the draft and stops sending them, opening and collapsing
 * the disclosure touches nothing at all, and un-ticking brings back exactly what was typed.
 */
/**
 * The one line under the current-grade picker, in all four of its states.
 *
 * Separated out because the interesting part is that they share a SLOT: the reader sees one
 * sentence in one position whose meaning and colour change, not a stack of advice.
 */
function goalLine(goal: string | undefined, versus: GoalComparison | null): string {
  if (goal === undefined) {
    return 'The same scale as your goal — the two are only comparable on one ladder.';
  }
  if (versus === 'above') {
    return `That is harder than your goal of ${goal}. Training runs upwards, so one of the two is probably not what you meant — either is fine to leave as it is.`;
  }
  if (versus === 'equal') {
    return `That is your goal of ${goal} exactly. A grade you already climb leaves the plan nothing to aim at, so you may want to set the goal higher.`;
  }
  return `Your goal is ${goal}. The distance between the two is what the plan is built on.`;
}

export function InjuryFields({ draft, vocabulary, onChange }: FieldProps) {
  const base = useId();
  const flagged = vocabulary.injury_areas.filter(
    (area) => !draft.noInjuries && area.id in draft.injuries,
  );
  // Read ONCE, at mount. Bound to the live count it would slam the panel shut under the user
  // the moment they un-ticked their last area; the card remounts per step, so "at mount" is
  // "when they arrived here", which is the question this actually asks.
  const [openAtMount] = useState(() => flagged.length > 0);

  return (
    <>
      <p className="ct-app__muted">
        Anything currently bothering you. The plan withholds exercises that load an injured area.
      </p>

      <label className="ct-app__choice ct-app__choice--span" htmlFor={`${base}-none`}>
        <input
          id={`${base}-none`}
          type="checkbox"
          checked={draft.noInjuries}
          // Ticking hides the list without clearing it; un-ticking restores it.
          onChange={() => onChange({ noInjuries: !draft.noInjuries })}
        />
        None — nothing is hurting
      </label>

      <details className="ct-app__disclosure" open={openAtMount}>
        <summary>
          {flagged.length === 0
            ? 'Something is hurting — pick the area'
            : `Something is hurting (${String(flagged.length)} selected)`}
        </summary>

        <fieldset className="ct-app__fieldset">
          <legend>Where it hurts</legend>
          <div className="ct-app__choices">
            {vocabulary.injury_areas.map((area) => {
              const checked = !draft.noInjuries && area.id in draft.injuries;
              return (
                <label
                  className="ct-app__choice"
                  key={area.id}
                  htmlFor={`${base}-${String(area.id)}`}
                >
                  <input
                    id={`${base}-${String(area.id)}`}
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const next = { ...draft.injuries };
                      if (checked) delete next[area.id];
                      else next[area.id] = '';
                      // The other half of the exclusion: an area cannot be flagged while
                      // "nothing is hurting" is still the answer.
                      onChange({ injuries: next, noInjuries: false });
                    }}
                  />
                  {area.name}
                </label>
              );
            })}
          </div>
        </fieldset>

        {flagged.map((area) => (
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
              // ⚠️ The placeholder is not decoration: `_primitives.scss` marks a committed field
              // with `input[placeholder]:not(:placeholder-shown)`, and an input with no
              // placeholder attribute can never match `:placeholder-shown`, so it would read as
              // committed while empty. The label above it is still the accessible name.
              placeholder="e.g. sore on crimps"
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
      </details>
    </>
  );
}

const FIELDS: Record<OnboardingStep, (props: FieldProps) => React.ReactElement> = {
  targetGrade: TargetGradeFields,
  availability: AvailabilityFields,
  aspects: ClimbingNowFields,
  injuries: InjuryFields,
};

/**
 * A glyph per step, and the heading that carries it.
 *
 * ⚠️ **One heading treatment, two callers** — the wizard's cards and the editor's sections render
 * this same component, so a step looks like itself in both places rather than the two drifting.
 * The editor had the map privately and the wizard had bare headings (round 11 addendum).
 *
 * `ct-app__icon-heading` is the existing primitive: it centres the glyph on the heading's FIRST
 * line rather than on the block, which is what keeps it right when a heading wraps. The glyphs are
 * `aria-hidden` from the shared `Icon` frame and sized in `em`, so none of them joins a heading's
 * accessible name.
 *
 * ⚠️ There is no Account entry, and that is not an omission: Account is not an `OnboardingStep`.
 * The editor renders its own heading for it with `IconUser`; the wizard has no Account card at
 * all, which is why step 0's rail node is inert there.
 */
const STEP_ICONS: Record<OnboardingStep, (props: { className?: string }) => React.ReactElement> = {
  targetGrade: IconTarget,
  availability: IconCalendar,
  aspects: IconSliders,
  injuries: IconBandage,
};

export function StepHeading({ step }: { step: OnboardingStep }) {
  const Glyph = STEP_ICONS[step];

  return (
    <h2 className="ct-app__icon-heading">
      <Glyph />
      {STEP_TITLES[step]}
    </h2>
  );
}

/** One step's fields. The dispatcher both entry points share. */
export function StepFields({ step, ...props }: FieldProps & { step: OnboardingStep }) {
  const Fields = FIELDS[step];
  return <Fields {...props} />;
}
