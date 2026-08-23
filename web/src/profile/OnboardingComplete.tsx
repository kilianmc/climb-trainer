import { Link } from '@tanstack/react-router';
import { useEffect, useRef } from 'react';

import { LANDING_IMAGES } from '../ui/landingImages';
import { LandingPicture } from '../ui/LandingPicture';
import { useRevealOnMount } from '../ui/reveal';

/**
 * The screen the last Save lands on, instead of dropping straight to the dashboard.
 *
 * Finishing setup is the one moment in this flow worth marking: the whole feature is built on
 * endowed progress and a Zeigarnik open loop, and a loop that closes with a silent redirect
 * teaches the user that finishing things here feels like nothing.
 *
 * Three constraints shaped it, and each ruled something out:
 *
 * - **The photograph is one already in the repo** (`hero-granite`, the landing hero) rendered
 *   through `LandingPicture`, so it keeps the AVIF/WebP/JPEG ladder and — the part that
 *   matters — resolves its origin through `publicUrl.ts`. A bare `/landing/…` src resolves
 *   against the DOCUMENT, which is kilianmc.com in the federated mount, and 404s there while
 *   working perfectly in dev.
 * - **The confetti is DOM and CSS only.** No dependency, and no `@keyframes`: a keyframe
 *   block's `from`/`to` are selector lists, and `distContract.test.ts` requires every selector
 *   in the built stylesheet to begin with `.ct-app`. So it is one transition per piece, with
 *   per-piece delays in `_profile.scss`, started by a class flipped after mount — the same
 *   technique `StepCard` uses, and for the same reason.
 * - **`prefers-reduced-motion` removes the confetti entirely** (`_profile.scss`), not just its
 *   movement. Everything that carries information — the photograph, the heading, the way
 *   onward — is still there, which is the line between reduced motion and reduced content.
 *
 * No `position: fixed` and no viewport units: the pieces are absolutely positioned inside the
 * card, which clips them, and both mounts share this route tree.
 */

/** Enough to read as a burst, few enough to stay one paint. `_profile.scss` styles each. */
const CONFETTI_PIECES = 18;

export function OnboardingComplete() {
  const confetti = useRef<HTMLDivElement>(null);
  // ⚠️ **A card of its own, and it has to LOOK like one** (Kilian, round 11). It always was a
  // separate `<section class="ct-app__card">` replacing the wizard's — but it arrives in the same
  // slot with the same frame, so without the reveal it reads as the step card's contents being
  // swapped rather than as a new card. Same shared technique as `StepCard`.
  const card = useRevealOnMount<HTMLElement>();

  useEffect(() => {
    const node = confetti.current;
    if (node === null) return;
    const frame = requestAnimationFrame(() => {
      node.classList.add('ct-app__confetti--in');
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <section ref={card} className="ct-app__card ct-app__done ct-app__reveal">
      {/* Decorative and nothing else: hidden from assistive technology, and it cannot take a
          pointer event away from the button underneath it. */}
      <div className="ct-app__confetti" ref={confetti} aria-hidden="true">
        {Array.from({ length: CONFETTI_PIECES }, (_unused, index) => (
          <span className="ct-app__confetti-piece" key={index} />
        ))}
      </div>

      <LandingPicture
        image={LANDING_IMAGES.hero}
        className="ct-app__done-shot"
        // A real measurement, not `100vw`: this card's content column is capped at 28rem.
        sizes="28rem"
      />

      <h1>Ready to start your training</h1>
      <p className="ct-app__muted">
        Your profile is complete. The plan is built from your goal, the time you have and what you
        told us about your climbing — you can change any of it whenever it changes.
      </p>

      <div className="ct-app__actions">
        <Link className="ct-app__button ct-app__button--primary" to="/dashboard">
          Go to your dashboard
        </Link>
      </div>
    </section>
  );
}
