import { useRevealOnMount } from '../ui/reveal';

/**
 * The one card on screen, and its reveal.
 *
 * Issue #54 asks for a card that appears when the step it belongs to becomes the one being
 * edited. Both entry points give this a `key` of the step, so it remounts and the reveal plays
 * again. The technique, and why it is a transition rather than a keyframe, lives in
 * `ui/reveal.ts` — this component is only the frame.
 *
 * ⚠️ `ct-app__reveal` is a separate class from `ct-app__stepcard`'s layout, because the profile
 * editor reuses that layout for sections that are all mounted at once: a resting `opacity: 0`
 * there would leave every section invisible.
 */
export function StepCard({ children }: { children: React.ReactNode }) {
  const card = useRevealOnMount<HTMLElement>();

  return (
    <section ref={card} className="ct-app__card ct-app__form ct-app__stepcard ct-app__reveal">
      {children}
    </section>
  );
}
