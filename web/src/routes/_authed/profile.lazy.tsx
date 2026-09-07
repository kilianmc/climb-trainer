import { createLazyFileRoute, useNavigate } from '@tanstack/react-router';
import { useState } from 'react';

import type { Profile, Vocabulary } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import { useProfilePatch, useProfileReset, useProfileScreen } from '../../profile/api';
import {
  ONBOARDING_STEPS,
  STEP_TITLES,
  completionPercent,
  remainingSteps,
  stepCompletion,
  type OnboardingStep,
} from '../../profile/completion';
import { accountPatch, draftFrom, patchForAll, type ProfileDraft } from '../../profile/draft';
import { OnboardingComplete } from '../../profile/OnboardingComplete';
import { ProfileFallback } from '../../profile/ProfileFallback';
import { ProfileProgress } from '../../profile/ProfileProgress';
import { StepFields, StepHeading } from '../../profile/steps';
import { IconUser } from '../../ui/icons';

/**
 * The profile editor — **sections, each revisitable on its own, with one Save at the end.**
 *
 * Round 5 restructured this. It was the wizard's stepper reused: one card at a time, Continue and
 * Back. That is the right shape for a first run and the wrong one for editing, because changing a
 * target grade meant walking past three questions that were already answered. So every section is
 * on the page at once and the step bar became an index into it — click a step, scroll to it.
 *
 * **Onboarding is untouched and stays the linear one-card wizard.** The two screens now differ in
 * more than where the write happens, and that is deliberate rather than drift: a first run needs
 * one decision at a time, an editor needs everything in reach.
 *
 * ⚠️ **Save sends only what was TOUCHED** — `patchForAll(draft, touched)`, where a step joins the
 * set when one of its own fields reports a change. It used to be the set of steps that had been
 * SHOWN, which was the same thing while one card was visible at a time and is not now: every
 * section is shown, so "shown" would mean "all of them", and pressing Save after editing a target
 * grade would stamp `injuries_reviewed_at` and write a default aspect rating for questions
 * the user never looked at. The bar may only ever report answers a user gave.
 *
 * The Account section is a PLACEHOLDER and says so. It marks the space for a display name and a
 * picture; there is no upload, no endpoint and no column behind it.
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

/** One id scheme, so the step bar and the sections cannot disagree about a target. */
function sectionId(step: OnboardingStep): string {
  return `ct-section-${step}`;
}

const ACCOUNT_SECTION_ID = 'ct-section-account';

/**
 * A glyph per section heading.
 *
 * Reused from the existing family wherever one fitted — `IconTarget` was drawn for the goal,
 * `IconSliders` for a set of scales, `IconCalendar` is the nav's own. Only `IconBandage` is new:
 * nothing in the file was medical. All of them are `aria-hidden` from the shared `Icon` frame, so
 * none of them joins a heading's accessible name.
 */
function scrollToId(id: string) {
  const node = document.getElementById(id);
  if (node === null) return;
  // Reduced motion covers programmatic scrolling too — a long smooth scroll is exactly the kind
  // of movement the preference is about.
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  node.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
}

function Editor({ profile, vocabulary }: { profile: Profile; vocabulary: Vocabulary }) {
  const navigate = useNavigate();
  // Read from the mutation's own handlers rather than from `patch.isError`: a superseded mutation
  // is detached from the observer, so that flag can stay false for a write that failed. See
  // `profile/api.ts`. Not named per step — one Save is one body.
  const [failed, setFailed] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [celebrate, setCelebrate] = useState(false);
  const patch = useProfilePatch({
    onError: (error) => {
      setFailed(error instanceof Error ? error.message : 'Please try again.');
    },
    onSuccess: () => {
      setFailed(null);
    },
  });
  // See the same note in `onboarding.lazy.tsx`: a demo token cannot write, so the Save button
  // says so instead of producing a 403.
  const readOnly = useAuth().scope === 'demo';
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFrom(profile, vocabulary));
  const [touched, setTouched] = useState<OnboardingStep[]>([]);
  // The Account section belongs to no step, so its own edit flag is separate — see
  // `accountPatch`.
  const [accountTouched, setAccountTouched] = useState(false);
  const [resetFailed, setResetFailed] = useState<string | null>(null);
  const reset = useProfileReset({
    onError: (error) => {
      setResetFailed(error instanceof Error ? error.message : 'Please try again.');
    },
    onSuccess: () => {
      setResetFailed(null);
    },
  });

  const completion = stepCompletion(profile);
  const open = remainingSteps(completion);

  /**
   * The Account section's own writes. They belong to NO step, so `touched` must not grow: a
   * display name is not an answer to an onboarding question and must never move the bar.
   */
  function setAccount(change: Partial<ProfileDraft>) {
    setDraft({ ...draft, ...change });
    setAccountTouched(true);
    setSaved(false);
  }

  function edit(step: OnboardingStep, change: Partial<ProfileDraft>) {
    setDraft({ ...draft, ...change });
    setTouched((current) => (current.includes(step) ? current : [...current, step]));
    setSaved(false);
  }

  /**
   * ⚠️ **Awaited, and it navigates only after the server has agreed.** The wizard reads the
   * profile to decide which step to open on, so navigating first would race the write and land
   * on whatever the cache still held — the same class of bug as the round-1 finish handler. A
   * failure leaves the user here with a message and an unchanged profile.
   */
  async function startOver() {
    try {
      await reset.mutateAsync();
    } catch {
      return;
    }
    void navigate({ to: '/onboarding' });
  }

  /** The Account section's field, and only if it was edited. See `accountPatch`. */
  function accountBody() {
    return accountTouched ? accountPatch(draft) : {};
  }

  /** The step bar as an index: click a step, scroll to its section. */
  function scrollToSection(step: OnboardingStep) {
    scrollToId(sectionId(step));
  }

  /**
   * Awaited: "Saved." is a claim about the database, so it must not appear before the database
   * has agreed. Nothing unmounts here, so a failure lands in the message below and the optimistic
   * overlay stops applying on its own (`profile/api.ts`).
   */
  async function save() {
    try {
      await patch.mutateAsync({ ...patchForAll(draft, touched), ...accountBody() });
    } catch {
      return;
    }
    setTouched([]);
    setAccountTouched(false);
    setSaved(true);
    // The completion screen, reachable from here too (Kilian, round 5) — he does his walkthroughs
    // in the editor and could not see it otherwise.
    //
    // ⚠️ The condition is "the profile is complete AFTER this save", which for an already-complete
    // profile means every Save celebrates. The right long-term rule is "it was incomplete before
    // and is complete now" — one comparison against a snapshot taken before the write — and that
    // is deliberately NOT what this does, because it would make the screen unreachable for exactly
    // the person reviewing it.
    if (remainingSteps(stepCompletion(profile)).length === 0) setCelebrate(true);
  }

  if (celebrate) return <OnboardingComplete />;

  return (
    <>
      <h1>Profile</h1>

      {/* No live region here: there are no step boundaries to announce, and a bar that spoke on
          every save would be the per-percent chatter the contract rules out. */}
      <ProfileProgress
        percent={completionPercent(completion)}
        label="Profile completion"
        // ⚠️ Node 0 is the ACCOUNT, always complete — it is what the 20% floor credits, and the
        // 0→1 connector is that floor drawn. See `ProfileProgress`.
        nodes={[
          {
            label: 'Account',
            done: true,
            onGo: () => {
              scrollToId(ACCOUNT_SECTION_ID);
            },
          },
          ...ONBOARDING_STEPS.map((step) => ({
            label: STEP_TITLES[step],
            done: completion[step],
            onGo: () => {
              scrollToSection(step);
            },
          })),
        ]}
      />
      {readOnly && (
        <p className="ct-app__badge" role="status">
          Demo — read only
        </p>
      )}

      {open.length > 0 && !readOnly && (
        <p className="ct-app__muted">
          {open.length === 1 ? 'One section' : `${String(open.length)} sections`} still to fill in.
        </p>
      )}

      <AccountSection
        email={profile.email}
        draft={draft}
        onChange={(change) => setAccount(change)}
      />

      {ONBOARDING_STEPS.map((step) => {
        return (
          <section
            className="ct-app__card ct-app__form ct-app__stepcard"
            id={sectionId(step)}
            key={step}
          >
            <StepHeading step={step} />

            <StepFields
              step={step}
              draft={draft}
              vocabulary={vocabulary}
              onChange={(change) => {
                edit(step, change);
              }}
            />
          </section>
        );
      })}

      {/* ⚠️ No anchor: the rail's Finish node is the Injuries STEP now, not a jump to Save, so
          nothing points here any more. It sits immediately after the Injuries section, so landing
          on that step puts Save in reach — and an id nothing targets is dead markup. */}
      <section className="ct-app__card ct-app__form ct-app__stepcard">
        {saved && (
          <p className="ct-app__caption" role="status">
            Saved.
          </p>
        )}

        {failed !== null && (
          <p className="ct-app__error" role="alert">
            Your changes could not be saved, so nothing about them has been counted. {failed}
          </p>
        )}

        <div className="ct-app__actionbar">
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            disabled={readOnly || patch.isPending}
            onClick={() => void save()}
          >
            {patch.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </section>

      <section className="ct-app__card ct-app__form ct-app__stepcard">
        <h2>Start over</h2>
        {/* Kilian's copy, one sentence and word for word. The prototype's second sentence —
            "each step you finish overwrites the old answer for real" — described a client-side
            simulation and is obsolete now that the reset is real server state. */}
        <p className="ct-app__notice" role="note">
          <span>This walks you through setup again from step one with empty fields.</span>
        </p>

        {resetFailed !== null && (
          <p className="ct-app__error" role="alert">
            Your profile could not be reset, so nothing has changed. {resetFailed}
          </p>
        )}

        <div className="ct-app__actionbar">
          <button
            type="button"
            className="ct-app__button"
            disabled={readOnly || reset.isPending}
            onClick={() => void startOver()}
          >
            {reset.isPending ? 'Resetting…' : 'Setup again'}
          </button>
        </div>
      </section>
    </>
  );
}

/**
 * The Account section: the email, a display name, and a password reset.
 *
 * Two of the three are real and one is not, and each says which on screen:
 *
 * - **The email is read-only.** It arrives on `ProfileResponse` (added for this PR — the
 *   client had no way to learn its own account's address before, because `GET /api/auth/me`
 *   returns `{user_id, scope}` and defers profile data by design). It is deliberately not in
 *   `ProfilePatchRequest`: changing an account's identity is a credential flow, not a profile
 *   edit.
 * - **The display name is a real column** (`0006`) with a real `PATCH`. It is prefilled from
 *   the email and stays overwritable: the value falls back to the address only while the
 *   column is NULL, so the first keystroke takes ownership. ⚠️ Clearing it back to nothing is
 *   not offered — `null` means "no change" on this endpoint and `DisplayName` refuses `''`.
 * - **Password reset is unbuilt** (issue #36, unscheduled), so the control is `disabled`
 *   rather than a live-looking button that swallows a click.
 */
function AccountSection({
  email,
  draft,
  onChange,
}: {
  email: string | null;
  draft: ProfileDraft;
  onChange: (change: Partial<ProfileDraft>) => void;
}) {
  return (
    <section className="ct-app__card ct-app__form ct-app__stepcard" id={ACCOUNT_SECTION_ID}>
      <h2 className="ct-app__icon-heading">
        <IconUser />
        Account
      </h2>

      <p className="ct-app__field">
        Email
        <span className="ct-app__readout">{email ?? 'Not available'}</span>
      </p>

      <label className="ct-app__field" htmlFor="ct-account-display-name">
        Display name
        <input
          id="ct-account-display-name"
          className="ct-app__input"
          type="text"
          // The placeholder is also what makes `_primitives.scss`'s committed-value rule work:
          // `input[placeholder]:not(:placeholder-shown)` cannot fire without one.
          placeholder="Your name"
          value={draft.displayName ?? email ?? ''}
          onChange={(event) => {
            onChange({ displayName: event.target.value });
          }}
        />
      </label>

      <div className="ct-app__actionbar">
        <button type="button" className="ct-app__button" disabled>
          Reset password
        </button>
      </div>
      <p className="ct-app__caption">Password reset is not built yet (issue #36).</p>
    </section>
  );
}

export const Route = createLazyFileRoute('/_authed/profile')({ component: ProfileRoute });
