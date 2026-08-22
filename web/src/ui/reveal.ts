import { useEffect, useRef } from 'react';

/**
 * Fade-and-lift a card in when it mounts. Two callers, one technique.
 *
 * Used by `profile/StepCard` (the wizard's one-card-at-a-time frame) and by
 * `profile/OnboardingComplete` (the celebration that replaces it). Both need a card to read as a
 * NEW card rather than as the previous one with different words in it, which is the whole point:
 * the completion screen appears in the same slot and the same frame as the step card it replaces,
 * so without this it looks like the step card's contents changed.
 *
 * Three constraints shape it, and none is optional:
 *
 * - **A transition, not a `@keyframes`.** `distContract.test.ts` asserts that every selector list
 *   in the built remote stylesheet begins with `.ct-app`, and a keyframe block's `from`/`to` are
 *   selector lists that never can.
 * - **The class goes on the DOM node, not into state.** `react-hooks`' `set-state-in-effect` rule
 *   rejects a `setState` in an effect body, and it is right to: this is a one-way instruction to
 *   the browser, not React state anything renders from.
 * - **`requestAnimationFrame` is what makes it work at all.** It guarantees the pre-transition
 *   style has been painted before the class lands, which is the only reason the transition has
 *   something to run from.
 *
 * Under `prefers-reduced-motion` the transition is dropped in `_profile.scss` and the class simply
 * arrives — reduced motion is not reduced information.
 */
export function useRevealOnMount<T extends HTMLElement>() {
  const node = useRef<T>(null);

  useEffect(() => {
    const element = node.current;
    if (element === null) return;
    const frame = requestAnimationFrame(() => {
      element.classList.add('ct-app__reveal--in');
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, []);

  return node;
}
