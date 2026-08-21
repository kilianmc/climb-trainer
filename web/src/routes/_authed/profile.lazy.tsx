import { createLazyFileRoute, Link } from '@tanstack/react-router';
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
import { ProfileFallback } from '../../profile/ProfileFallback';
import { ProfileProgress } from '../../profile/ProfileProgress';
import { StepFields } from '../../profile/steps';

/**
 * The profile editor — **the same five field groups as onboarding**, all on one page.
 *
 * `profile/steps.tsx` is the single copy of the fields; the only difference between the
 * two entry points is the flow around them. Here each section saves on its own, which is
 * the right shape for editing (change one thing, save one thing) and the same Tier-1
 * write onboarding uses.
 *
 * `show_body_metrics` is deliberately not on this screen. It is a real setting with real
 * behaviour and it is not one of the five onboarding steps, so it belongs to the settings
 * work rather than being bolted onto the last card here.
 */
function ProfileRoute() {
  const { profile, vocabulary, profileFailed, vocabularyFailed, retry } = useProfileScreen();

  // Same gate as the wizard, and for the same reason: this screen also holds a draft in
  // `useState`. See `ProfileFallback`.
  if (profile === undefined || vocabulary === undefined) {
    return (
      <ProfileFallback
        title="Profile"
        profileFailed={profileFailed}
        vocabularyFailed={vocabularyFailed}
        retry={retry}
      />
    );
  }

  return <Editor profile={profile} vocabulary={vocabulary} />;
}

function Editor({ profile, vocabulary }: { profile: Profile; vocabulary: Vocabulary }) {
  // Per SECTION rather than one banner, and read from the mutation's own handlers rather
  // than from `patch.isError`: a superseded mutation is detached from the observer, so that
  // flag can stay false for a write that failed. See `profile/api.ts`.
  const [failed, setFailed] = useState<{ step: OnboardingStep; reason: string } | null>(null);
  const patch = useProfilePatch({
    onError: (error, body) => {
      const step = stepOf(body);
      if (step !== null) {
        setFailed({ step, reason: error instanceof Error ? error.message : 'Please try again.' });
      }
    },
    onSuccess: (_saved, body) => {
      const step = stepOf(body);
      setFailed((current) => (current !== null && current.step === step ? null : current));
    },
  });
  // See the same note in `onboarding.lazy.tsx`: a demo token cannot write, so the Save
  // buttons say so instead of producing a 403.
  const readOnly = useAuth().scope === 'demo';
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFrom(profile, vocabulary));
  const [savedStep, setSavedStep] = useState<OnboardingStep | null>(null);

  const completion = stepCompletion(profile);
  const open = remainingSteps(completion);

  /**
   * Awaited, unlike the wizard's steps 1-4, and for one reason: "Saved." is a claim about
   * the database, so it must not appear before the database has agreed. Nothing unmounts
   * here, so a failure lands in the message below and the optimistic overlay stops applying
   * on its own (`profile/api.ts`) — the await only gates the confirmation text.
   */
  async function save(step: OnboardingStep) {
    try {
      await patch.mutateAsync(patchFor(step, draft));
    } catch {
      return;
    }
    setSavedStep(step);
  }

  return (
    <>
      <h1>Profile</h1>

      {/* No live region here: there are no step boundaries to announce, and a bar that
          spoke on every save would be the per-percent chatter the contract rules out. */}
      <ProfileProgress percent={completionPercent(completion)} label="Profile completion" />

      {readOnly && (
        <p className="ct-app__badge" role="status">
          Demo — read only
        </p>
      )}

      {open.length > 0 && !readOnly && (
        <p className="ct-app__muted">
          {open.length === 1 ? 'One section' : `${String(open.length)} sections`} still to fill in.{' '}
          <Link to="/onboarding">Walk through them step by step</Link>.
        </p>
      )}

      {ONBOARDING_STEPS.map((step) => (
        <section className="ct-app__card ct-app__form" key={step}>
          <h2>{STEP_TITLES[step]}</h2>

          <StepFields
            step={step}
            draft={draft}
            vocabulary={vocabulary}
            onChange={(change) => {
              setDraft({ ...draft, ...change });
              setSavedStep(null);
            }}
          />

          {savedStep === step && (
            <p className="ct-app__caption" role="status">
              Saved.
            </p>
          )}

          {failed?.step === step && (
            <p className="ct-app__error" role="alert">
              That change could not be saved, so nothing about it has been counted. {failed.reason}
            </p>
          )}

          <div className="ct-app__actionbar">
            <button
              type="button"
              className="ct-app__button ct-app__button--primary"
              disabled={readOnly || patch.isPending || !canSubmit(step, draft)}
              onClick={() => void save(step)}
            >
              {patch.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </section>
      ))}
    </>
  );
}

export const Route = createLazyFileRoute('/_authed/profile')({ component: ProfileRoute });
