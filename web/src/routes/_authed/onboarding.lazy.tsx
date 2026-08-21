import { createLazyFileRoute, Navigate, useNavigate } from '@tanstack/react-router';
import { useState } from 'react';

import type { Profile, Vocabulary } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import { useProfilePatch, useProfileScreen } from '../../profile/api';
import {
  ONBOARDING_STEPS,
  STEP_TITLES,
  completionPercent,
  remainingSteps,
  stepCompletion,
  type OnboardingStep,
} from '../../profile/completion';
import { canSubmit, draftFrom, patchFor, stepOf, type ProfileDraft } from '../../profile/draft';
import { OnboardingStepper } from '../../profile/OnboardingStepper';
import { ProfileFallback } from '../../profile/ProfileFallback';
import { ProfileProgress } from '../../profile/ProfileProgress';
import { StepFields } from '../../profile/steps';

/**
 * Onboarding: five steps, one decision each, in the order `ONBOARDING_STEPS` fixes.
 *
 * ## It RESUMES, and that is the whole reason the endpoint takes a partial profile
 *
 * The wizard opens on the first step that is not already answered, so someone who closed
 * the tab after step 2 lands on step 3 rather than starting again (the plan's Zeigarnik
 * point). Every "Continue" is one `PATCH` carrying only that step's fields, so the profile
 * row exists from step 1 onward and there is always something to come back to. A visitor
 * whose profile is already complete is sent to the editor rather than walked through five
 * finished screens.
 *
 * ## ⚠️ Steps 1-4 never wait. The FINAL step is awaited, and only it.
 *
 * The round-1 bug was not the optimism — it was navigating in the same handler as the
 * write. On the last step that unmounted the component before the mutation settled, so a
 * failed write was invisible (its error had nowhere to render) and credited (the bar read
 * 100% with no injury in the database, which PR #11's generator would trust).
 *
 * For steps 1-4 nothing unmounts, so the documented Tier-1 shape is enough and is what
 * CLAUDE.md asks for: apply the patch optimistically, advance immediately, and say which step
 * failed. There is nothing to roll back — the optimism is an overlay derived from the pending
 * mutation, so it stops applying by itself (`profile/api.ts`). Awaiting there would buy
 * nothing and cost a Neon cold start at each of four boundaries, in the one flow whose whole
 * premise is not losing people mid-way.
 *
 * The final step is the exception, and `finish()` is where the await lives. It is the only
 * boundary where the component really does go away, so it is the only one where "we told
 * you it saved" cannot be corrected afterwards.
 * `web/src/onboardingSubmit.test.tsx` fails if that await is removed.
 *
 * The fields themselves live in `profile/steps.tsx` and are shared with the profile
 * editor at `/profile`. This file is only the flow: which step, what it saves, where
 * "Finish" goes.
 */
function OnboardingRoute() {
  const { profile, vocabulary, profileFailed, vocabularyFailed, retry } = useProfileScreen();

  // ⚠️ Gated on "there is nothing to show", NEVER on `isError`. A failed background refetch
  // leaves `status: "error"` with the data still in place (`query.js`'s error reducer sets it
  // unconditionally), and swapping the wizard out on that flag destroyed the user's draft —
  // including a typed injury note — with no way back, since nothing refetches on focus.
  if (profile === undefined || vocabulary === undefined) {
    return (
      <ProfileFallback
        title="Set up your profile"
        profileFailed={profileFailed}
        vocabularyFailed={vocabularyFailed}
        retry={retry}
      />
    );
  }

  return <Wizard profile={profile} vocabulary={vocabulary} />;
}

function Wizard({ profile, vocabulary }: { profile: Profile; vocabulary: Vocabulary }) {
  const navigate = useNavigate();
  const { scope } = useAuth();
  // Which steps' writes have failed, and the last reason given. A SET, because two steps
  // can be in flight at once (the equipment and aspect steps both need no input, so two
  // clicks in one tick is ordinary) and reporting only the latest would hide the other.
  //
  // Two known and accepted limits: two SIMULTANEOUS failures show only the last `reason`
  // (they are the same server error in practice), and finishing the last step navigates away
  // with any earlier failure still in this set, so that notice is discarded. The dashboard
  // then converges on server truth rather than lying — but note what the consolation is: a
  // NUMBER (the bar drops back and the step reads unanswered), not a message. Nobody is told
  // which answer was lost.
  const [failure, setFailure] = useState<{ steps: OnboardingStep[]; reason: string }>({
    steps: [],
    reason: '',
  });
  const patch = useProfilePatch({
    // Both handlers go through `useMutation`, never through `mutate(vars, …)`: a superseded
    // mutation is detached from the observer and per-call options would never fire — which
    // is how a failed step-1 write followed by a successful step-2 write produced no
    // message at all. The step comes from the PATCH itself, not from a closure.
    onError: (error, body) => {
      const step = stepOf(body);
      setFailure((current) => ({
        steps:
          step === null || current.steps.includes(step) ? current.steps : [...current.steps, step],
        reason: message(error),
      }));
    },
    // A later success clears only ITS OWN step. Clearing everything would erase the notice
    // that some earlier answer was lost, which is the whole point of keeping it.
    onSuccess: (_profile, body) => {
      const step = stepOf(body);
      setFailure((current) =>
        step === null ? current : { ...current, steps: current.steps.filter((s) => s !== step) },
      );
    },
  });
  // Demo tokens 403 on every mutating route (enforced twice — see server/auth/deps.py), so
  // the buttons are disabled rather than left to fail. The fields still render: looking
  // around is the whole point of the demo.
  const readOnly = scope === 'demo';

  // Initialised once, from the profile as it was when the wizard opened. Later cache
  // updates must not overwrite what the user is currently typing.
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFrom(profile, vocabulary));
  const [entryOpenSteps] = useState(() => remainingSteps(stepCompletion(profile)).length);
  const [step, setStep] = useState<OnboardingStep>(() => {
    const [firstOpen] = remainingSteps(stepCompletion(profile));
    return firstOpen ?? ONBOARDING_STEPS[0];
  });
  const completion = stepCompletion(profile);
  const percent = completionPercent(completion);
  const index = ONBOARDING_STEPS.indexOf(step);
  const isLast = index === ONBOARDING_STEPS.length - 1;

  /**
   * Steps 1-4: optimistic, no wait. The optimism is an overlay derived from the pending
   * mutation, so a failure needs no rollback — the overlay simply stops applying — and the
   * message names the step (`profile/api.ts`).
   */
  function advance(next: OnboardingStep) {
    patch.mutate(patchFor(step, draft));
    setStep(next);
  }

  /**
   * Step 5: awaited, because success unmounts this component and a failure afterwards
   * would have nowhere to show and nothing to roll back on screen.
   */
  async function finish() {
    try {
      await patch.mutateAsync(patchFor(step, draft));
    } catch {
      // Stay put. `onError` has already recorded the step, and the optimistic overlay drops
      // itself when the mutation leaves `pending`; the rejection is swallowed here rather
      // than escaping to an error boundary that would replace the form the user needs.
      return;
    }
    void navigate({ to: '/dashboard' });
  }

  // Nothing was left to ask when this screen was ENTERED. Walking someone through five
  // completed steps — bar already at 100%, a "Continue" that re-submits what they answered —
  // is worse than sending them where the editing happens.
  //
  // Decided from the ENTRY SNAPSHOT rather than from the live profile: finishing the last
  // step updates the cache to a complete profile before `navigate` runs, so a live check
  // would race /dashboard against this redirect. ⚠️ That ordering is prevented structurally
  // and is NOT test-guarded — reverting this line to a live check leaves
  // `onboardingSubmit.test.tsx` green, because jsdom never renders the intermediate state.
  // Keep the snapshot; do not expect a test to catch you removing it.
  if (entryOpenSteps === 0) return <Navigate to="/profile" replace />;

  return (
    <>
      <h1>Set up your profile</h1>

      <ProfileProgress
        percent={percent}
        label="Profile completion"
        // Announced at step boundaries only — one sentence, when the step changes.
        announcement={`Step ${String(index + 1)} of ${String(ONBOARDING_STEPS.length)}, ${STEP_TITLES[step].toLowerCase()} — ${String(percent)}% complete`}
      />
      <OnboardingStepper current={step} completion={completion} />

      <section className="ct-app__card ct-app__form">
        <h2>{STEP_TITLES[step]}</h2>

        <StepFields
          step={step}
          draft={draft}
          vocabulary={vocabulary}
          onChange={(change) => setDraft({ ...draft, ...change })}
        />

        {readOnly && (
          <p className="ct-app__badge" role="status">
            Demo — read only
          </p>
        )}

        {failure.steps.length > 0 && (
          <p className="ct-app__error" role="alert">
            {failure.steps.length === 1
              ? `Your ${describe(failure.steps)} answer could not be saved, so it has not been counted.`
              : `These answers could not be saved, so they have not been counted: ${describe(failure.steps)}.`}{' '}
            {failure.reason}
          </p>
        )}

        <div className="ct-app__actionbar">
          {index > 0 && (
            <button
              type="button"
              className="ct-app__button"
              onClick={() => setStep(ONBOARDING_STEPS[index - 1] ?? ONBOARDING_STEPS[0])}
            >
              Back
            </button>
          )}
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            // Only the awaited step disables while in flight; the other four do not wait,
            // so disabling them would be a wait with no purpose.
            disabled={readOnly || (isLast && patch.isPending) || !canSubmit(step, draft)}
            onClick={() => {
              const next = ONBOARDING_STEPS[index + 1];
              if (next === undefined) void finish();
              else advance(next);
            }}
          >
            {isLast && patch.isPending ? 'Saving…' : isLast ? 'Finish' : 'Continue'}
          </button>
        </div>
      </section>
    </>
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Please try again.';
}

/** Step titles, lowercased and joined — in `ONBOARDING_STEPS` order, not failure order. */
function describe(steps: OnboardingStep[]): string {
  return ONBOARDING_STEPS.filter((step) => steps.includes(step))
    .map((step) => STEP_TITLES[step].toLowerCase())
    .join(', ');
}

export const Route = createLazyFileRoute('/_authed/onboarding')({ component: OnboardingRoute });
