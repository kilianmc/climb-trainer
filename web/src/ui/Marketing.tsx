import { Link } from '@tanstack/react-router';
import type { ReactNode } from 'react';

import { LandingPicture } from './LandingPicture';
import { LANDING_IMAGES, type LandingImage } from './landingImages';
import {
  IconJournal,
  IconPlay,
  IconSignIn,
  IconSliders,
  IconTarget,
  IconTimer,
  IconUserPlus,
} from './icons';

/**
 * The public landing page.
 *
 * **What this redesign is, and what it deliberately is not.** The page was reviewed as wasting
 * the whole width of a desktop window and reading as basic, and the honest diagnosis was that it
 * was **missing content, not missing CSS** — it contained zero images. So the fix is full-bleed
 * photographic bands carrying the imagery and the colour, with the copy held to a ~65–75
 * character column. It is emphatically **not** "raise `max-inline-size` and let the text run 140
 * characters wide", which is the change that looks like using the space and is unreadable.
 *
 * `ct-app__bleed` is how a section escapes the reading measure, and `_layout.scss` documents why
 * it is a grid column rather than `100vw` or `position: fixed`: this file renders in BOTH mounts
 * from one route tree, and in the federated mount those two resolve against kilianmc.com's
 * viewport rather than the card the remote was given.
 *
 * **The one `100vw` on this page is in a `sizes` attribute, and that is not the same thing.**
 * `sizes` picks which file to download; it moves no boxes. In the federated mount a band is
 * narrower than the window, so the hint over-estimates and the browser may fetch one rung more
 * than it needs — bytes, never geometry. The alternative, a fixed length, would either
 * under-serve a 2560px desktop hero or make every phone download a desktop-sized band.
 *
 * **DOM order, headings, hrefs and button labels are unchanged where tests assert them** —
 * `router.test.tsx`, `routeGuard.test.tsx` and `remote.guard.test.tsx` pin the `climb-trainer`
 * h1 and the exact "Explore the demo" accessible name, which is also why every icon is
 * `aria-hidden` (see `icons.tsx`).
 *
 * The four `ct-app__shot` frames are untouched: they are placeholders for real app screenshots,
 * which need the plan UI and the session player to exist. A photograph of climbing is not a
 * screenshot of this software and must not be presented as one — hence the imagery below sits in
 * bands and figures of its own, and the empty frames stay honest.
 */

function Shot({ image, square = false }: { image: LandingImage; square?: boolean }) {
  return (
    <div className={`ct-app__shot${square ? ' ct-app__shot--square' : ''}`}>
      <LandingPicture image={image} sizes={square ? '23rem' : '41rem'} />
    </div>
  );
}

/** `area` places the card in the bento's named grid; it changes no markup semantics. */
function Section({
  area,
  icon,
  heading,
  image,
  square,
  caption,
  children,
}: {
  area: 'plan' | 'session' | 'diary';
  icon: ReactNode;
  heading: string;
  image: LandingImage;
  square?: boolean;
  caption: string;
  children: ReactNode;
}) {
  return (
    <section className={`ct-app__card ct-app__bento--${area}`}>
      <h2 className="ct-app__icon-heading">
        {icon}
        {heading}
      </h2>
      <p className="ct-app__prose">{children}</p>
      <figure className="ct-app__figure">
        <Shot image={image} {...(square === true ? { square } : {})} />
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
      <header className="ct-app__hero ct-app__bleed">
        <LandingPicture image={LANDING_IMAGES.hero} sizes="100vw" priority />
        <div className="ct-app__measured">
          <div className="ct-app__prose ct-app__prose--centre">
            <h1>climb-trainer</h1>
            <p className="ct-app__lede">
              Pick the grade you are training for, and get a plan that covers every aspect of
              climbing — then follow it, set by set, in the gym.
            </p>
          </div>

          {/* Outside `__prose` so the row may use the full measure rather than the 56ch column. */}
          <div className="ct-app__actions ct-app__actions--centre">
            <button
              type="button"
              className="ct-app__button ct-app__button--primary"
              onClick={onExploreDemo}
              disabled={demoPending}
            >
              <IconPlay />
              {demoPending ? 'Opening the demo…' : 'Explore the demo'}
            </button>
            <Link className="ct-app__button" to="/login">
              <IconSignIn />
              Log in
            </Link>
            <Link className="ct-app__button" to="/register">
              <IconUserPlus />
              Create account
            </Link>
          </div>
          {demoError !== null && (
            <p className="ct-app__error" role="alert">
              {demoError}
            </p>
          )}
        </div>
      </header>

      <div className="ct-app__bento">
        <Section
          area="plan"
          icon={<IconTarget />}
          heading="A plan built around your target grade"
          image={LANDING_IMAGES.shotPlan}
          caption="Stand-in photograph — the plan overview arrives with the plan generator."
        >
          Tell the app the grade you want, how often you can train and what you have access to. It
          lays out a block that spends your weeks on the aspects that actually limit you — finger
          strength, power, endurance, technique and mobility — with deloads and a taper where they
          belong, not wherever the calendar happens to fall.
        </Section>

        <Section
          area="session"
          icon={<IconTimer />}
          heading="Follow along during the session"
          image={LANDING_IMAGES.shotSession}
          square
          caption="Stand-in photograph — the guided session player arrives with the player."
        >
          A session is a sequence of timed sets, not a list to remember. The player counts you
          through work and rest with a large, readable display and audible cues, so it still works
          with the phone face-down on the mat, and you log each set as you finish it.
        </Section>

        <Section
          area="diary"
          icon={<IconJournal />}
          heading="A diary that shows whether it worked"
          image={LANDING_IMAGES.shotDiary}
          square
          caption="Stand-in photograph — the training diary arrives with the diary."
        >
          Every session, send and note lands in one timeline. Grades are stored on a shared ladder,
          so a V5 and a 7A are directly comparable and progress is a line rather than a feeling.
        </Section>
      </div>

      <section className="ct-app__band ct-app__bleed">
        <LandingPicture image={LANDING_IMAGES.effort} sizes="100vw" />
        {/* Two wrappers, not two classes on one element: `__measured` and `__prose` both set
            `max-inline-size`, so combining them would make the narrower one depend on the order
            the partials happen to be included in. */}
        <div className="ct-app__measured">
          <div className="ct-app__prose ct-app__prose--centre">
            <h2>The hard part is showing up on the right day</h2>
            <p>
              A plan is only worth having if it tells you what today is for. Every session in yours
              has a job — build, sharpen, or back off — and the app is honest about which one it is.
            </p>
          </div>
        </div>
      </section>

      <section className="ct-app__card">
        <h2 className="ct-app__icon-heading">
          <IconSliders />
          Built around what you actually have
        </h2>
        <div className="ct-app__detail">
          <p className="ct-app__prose">
            A board, a pull-up bar and two evenings a week is a different plan from four sessions
            and a full gym. Tell it your equipment, your availability and anything you are working
            around, and the sessions it prescribes are ones you can actually do — a plan you skip
            half of is not a plan.
          </p>
          <figure className="ct-app__detail-media">
            <LandingPicture image={LANDING_IMAGES.detail} sizes="22rem" />
          </figure>
        </div>
      </section>

      <section className="ct-app__card">
        <h2>Have a look around first</h2>
        <p className="ct-app__prose">
          There is a demo account with a full plan and a season of training already in it. It opens
          instantly, needs no email address, and is read-only — you can walk through every screen
          without creating anything.
        </p>
        <p className="ct-app__caption">
          The demo carries seeded data only. No real training history is ever in it.
        </p>
        {/* No imagery: this is a closing call to action, and a photograph here competes with the
            button rather than explaining anything. */}
        <div className="ct-app__actions ct-app__actions--centre">
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            onClick={onExploreDemo}
            disabled={demoPending}
          >
            <IconPlay />
            {demoPending ? 'Opening the demo…' : 'Open the demo'}
          </button>
        </div>
      </section>
    </>
  );
}
