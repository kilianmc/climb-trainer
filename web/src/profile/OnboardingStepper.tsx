import {
  ONBOARDING_STEPS,
  STEP_TITLES,
  type OnboardingStep,
  type StepCompletion,
} from './completion';

/**
 * Where you are in the five steps — POSITION, not percentage. The bar next to it carries
 * the percentage; saying the same thing twice in two units is how a stepper starts
 * disagreeing with a progress bar.
 *
 * `<nav aria-label>` → `<ol>` → `<li>` with **`aria-current="step"`**, which is the
 * structure the W3C WAI multi-page-form tutorial specifies: an ordered list is what makes
 * "3 of 5" available without the page having to say it, and `aria-current` is what makes
 * the active one findable.
 *
 * The active step is marked by weight, an outline and `aria-current` — never by hue alone
 * — and a finished step says "Done" in words rather than turning green.
 */
export interface OnboardingStepperProps {
  current: OnboardingStep;
  completion: StepCompletion;
}

export function OnboardingStepper({ current, completion }: OnboardingStepperProps) {
  return (
    <nav className="ct-app__stepper" aria-label="Onboarding steps">
      <ol>
        {ONBOARDING_STEPS.map((step, index) => (
          <li
            key={step}
            className={step === current ? 'ct-app__stepper-step--current' : undefined}
            {...(step === current ? { 'aria-current': 'step' as const } : {})}
          >
            <span className="ct-app__stepper-index">{index + 1}</span>
            <span className="ct-app__stepper-title">{STEP_TITLES[step]}</span>
            {completion[step] && <span className="ct-app__stepper-state">Done</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}
