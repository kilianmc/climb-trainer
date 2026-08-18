import { Link } from '@tanstack/react-router';
import type { ReactNode } from 'react';

/**
 * The public landing page. **Structure now, styling in PR #7.**
 *
 * Kilian's call for PR #6: build the whole page shape — hero, positioning line, the value
 * sections, the "explore the demo" section and the three calls to action — but style it with
 * nothing more than the five existing custom properties plus one input, one button, one error
 * and one badge. A visitor should be able to *read* and get the idea, or step inside and look
 * around, and PR #7's design system then styles a structure that is already correct rather
 * than inventing one late.
 *
 * So, deliberately absent: cards, grid, bento areas, a shadow scale, container queries, and
 * any token outside `.ct-app`. If you are tempted to add one of those here, it belongs in
 * PR #7. See the UI design direction section of CLAUDE.md.
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

function Section({
  heading,
  shot,
  caption,
  children,
}: {
  heading: string;
  shot: string;
  caption: string;
  children: ReactNode;
}) {
  return (
    <section className="ct-app__section">
      <h2>{heading}</h2>
      <p>{children}</p>
      <figure className="ct-app__figure">
        <Shot label={shot} />
        <figcaption className="ct-app__muted">{caption}</figcaption>
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
      <header className="ct-app__section">
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

      <Section
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
        heading="Follow along during the session"
        shot="Session player"
        caption="Guided session player — arrives with the session player."
      >
        A session is a sequence of timed sets, not a list to remember. The player counts you through
        work and rest with a large, readable display and audible cues, so it still works with the
        phone face-down on the mat, and you log each set as you finish it.
      </Section>

      <Section
        heading="A diary that shows whether it worked"
        shot="Training diary"
        caption="Training diary — arrives with the diary."
      >
        Every session, send and note lands in one timeline. Grades are stored on a shared ladder, so
        a V5 and a 7A are directly comparable and progress is a line rather than a feeling.
      </Section>

      <section className="ct-app__section">
        <h2>Have a look around first</h2>
        <p>
          There is a demo account with a full plan and a season of training already in it. It opens
          instantly, needs no email address, and is read-only — you can walk through every screen
          without creating anything.
        </p>
        <figure className="ct-app__figure">
          <Shot label="Demo" />
          <figcaption className="ct-app__muted">
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
