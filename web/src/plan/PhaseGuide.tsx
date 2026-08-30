import type { PhaseGuide, Vocabulary } from '../api/types';
import { humanise } from '../library/browse';

import type { PhaseInPlan, PlanFact } from './explain';

/* The phase copy, rendered. Shared by `/plan` and the session brief so the two screens say the
   same thing in the same words — a second copy of this markup is how they drift apart. */

/** Phase copy indexed by `Phase`, built once per plan and read at four places on `/plan`. */
export type PhaseGuides = ReadonlyMap<string, PhaseGuide>;

export function phaseGuides(vocabulary: Vocabulary): PhaseGuides {
  return new Map(vocabulary.phase_guide.map((guide) => [guide.phase, guide]));
}

/** The guide's own label, which is shorter and more specific than the enum value ("Max
 *  strength", not "Strength"). Falls back to `humanise` so a phase with no copy still names itself. */
export function phaseLabel(guides: PhaseGuides, phase: string): string {
  return guides.get(phase)?.label ?? humanise(phase);
}

/** The plan's own facts as badges — the idiom `PhaseTimeline` already uses on the plan screen. */
export function PlanFacts({ facts }: { facts: readonly PlanFact[] }) {
  if (facts.length === 0) return null;

  return (
    <p className="ct-app__tags">
      {facts.map((fact) => (
        <span className="ct-app__badge" key={`${fact.label}:${fact.value}`}>
          {fact.label}: {fact.value}
        </span>
      ))}
    </p>
  );
}

/* Disclosed, not open: sixteen mesocycles of expanded copy would bury the sessions, and on the
   brief 600 characters of prose above Start would bury the session. Server wording verbatim. */
export function PhaseGuideNote({
  guide,
  inPlan,
}: {
  guide: PhaseGuide | undefined;
  inPlan: PhaseInPlan | null;
}) {
  if (guide === undefined) return null;

  return (
    <details className="ct-app__disclosure">
      <summary>Why this phase</summary>
      <p className="ct-app__muted">{guide.summary}</p>
      <p className="ct-app__muted">
        <strong>How to train it:</strong> {guide.how_to_train}
      </p>
      {inPlan !== null && (
        <>
          <p className="ct-app__muted">
            <strong>In your plan:</strong> {inPlan.weeks}
          </p>
          <PlanFacts facts={inPlan.facts} />
        </>
      )}
      {guide.links.map((link) => (
        <p className="ct-app__muted" key={link.url}>
          {/* A new tab, so a half-read plan is not replaced by somebody else's website — and
              `noreferrer` as well as `noopener`, per CLAUDE.md's security rules. */}
          <a className="ct-app__link" href={link.url} target="_blank" rel="noopener noreferrer">
            {link.label}
          </a>
        </p>
      ))}
    </details>
  );
}
