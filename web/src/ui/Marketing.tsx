import { Link } from '@tanstack/react-router';
import type { ReactNode } from 'react';

/**
 * The public landing page, now on the PR #7 design system: the three value sections are cards
 * in the bento grid, and each card's internals respond to the card's own width via
 * `@container`, so the same component reads correctly full-width standalone and narrow inside
 * the shell's ProjectViewer.
 *
 * Structure, DOM order, headings and hrefs are unchanged from PR #6 — several tests assert the
 * exact link lists and heading order, and this PR is class and wrapper changes only.
 *
 * The hero's calls to action stay in flow rather than in the bottom-anchored action bar: DOM
 * order is fixed, and this is a page a visitor reads top to bottom, not a screen they operate
 * one-handed mid-session. The bottom-anchored primitive is applied where it belongs, on the
 * auth forms' submit — see `CredentialsForm.tsx`.
 *
 * The image slots are placeholders on purpose. Real screenshots need the plan UI (PR #8) and
 * the session player (PR #15a) to exist; a mocked-up screenshot of software that does not
 * work yet is the one thing worse than an obvious placeholder.
 */

function Shot({ label }: { label: string }) {
  return (
    <div className="ct-app__shot" aria-hidden="true">
      {label}
    </div>
  );
}

/** `area` places the card in the bento's named grid; it changes no markup semantics. */
function Section({
  area,
  heading,
  shot,
  caption,
  children,
}: {
  area: 'plan' | 'session' | 'diary';
  heading: string;
  shot: string;
  caption: string;
  children: ReactNode;
}) {
  return (
    <section className={`ct-app__card ct-app__bento--${area}`}>
      <h2>{heading}</h2>
      <p>{children}</p>
      <figure className="ct-app__figure">
        <Shot label={shot} />
        <figcaption className="ct-app__caption">{caption}</figcaption>
      </figure>
    </section>
  );
}

export interface MarketingProps {
  onExploreDemo: () => void;
  demoPending: boolean;
  demoError: string | null;
}

export function Marketing({ onExploreDemo, demoPending, demoError }: MarketingProps) {
  return (
    <>
      <header className="ct-app__hero">
        <h1>climb-trainer</h1>
        <p className="ct-app__lede">
          Pick the grade you are training for, and get a plan that covers every aspect of climbing —
          then follow it, set by set, in the gym.
        </p>

        <div className="ct-app__actions">
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            onClick={onExploreDemo}
            disabled={demoPending}
          >
            {demoPending ? 'Opening the demo…' : 'Explore the demo'}
          </button>
          <Link className="ct-app__button" to="/login">
            Log in
          </Link>
          <Link className="ct-app__button" to="/register">
            Create account
          </Link>
        </div>
        {demoError !== null && (
          <p className="ct-app__error" role="alert">
            {demoError}
          </p>
        )}
      </header>

      <div className="ct-app__bento">
        <Section
          area="plan"
          heading="A plan built around your target grade"
          shot="Plan overview"
          caption="Plan overview — arrives with the plan generator."
        >
          Tell the app the grade you want, how often you can train and what you have access to. It
          lays out a block that spends your weeks on the aspects that actually limit you — finger
          strength, power, endurance, technique and mobility — with deloads and a taper where they
          belong, not wherever the calendar happens to fall.
        </Section>

        <Section
          area="session"
          heading="Follow along during the session"
          shot="Session player"
          caption="Guided session player — arrives with the session player."
        >
          A session is a sequence of timed sets, not a list to remember. The player counts you
          through work and rest with a large, readable display and audible cues, so it still works
          with the phone face-down on the mat, and you log each set as you finish it.
        </Section>

        <Section
          area="diary"
          heading="A diary that shows whether it worked"
          shot="Training diary"
          caption="Training diary — arrives with the diary."
        >
          Every session, send and note lands in one timeline. Grades are stored on a shared ladder,
          so a V5 and a 7A are directly comparable and progress is a line rather than a feeling.
        </Section>
      </div>

      <section className="ct-app__card">
        <h2>Have a look around first</h2>
        <p>
          There is a demo account with a full plan and a season of training already in it. It opens
          instantly, needs no email address, and is read-only — you can walk through every screen
          without creating anything.
        </p>
        <figure className="ct-app__figure">
          <Shot label="Demo" />
          <figcaption className="ct-app__caption">
            The demo carries seeded data only. No real training history is ever in it.
          </figcaption>
        </figure>
        <div className="ct-app__actions">
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            onClick={onExploreDemo}
            disabled={demoPending}
          >
            {demoPending ? 'Opening the demo…' : 'Open the demo'}
          </button>
        </div>
      </section>
    </>
  );
}
