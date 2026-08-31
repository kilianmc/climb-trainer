import type { Phase, PlanMesocycle, PlanSession, PlanTree } from '../api/types';

/* How THIS plan applies the phases, from the payload alone: `GET /api/plans/active` already
   carries every fact below. */

/** One row of a plan-specific block. Structured, because interpolated prose breaks at the edges. */
export interface PlanFact {
  label: string;
  value: string;
}

/** One phase, as it appears in THIS plan. `weeks` is every occurrence, not the first. */
export interface PhaseInPlan {
  weeks: string;
}

/** One contiguous run of weeks. A phase RECURS — `deload` has six of these in a 28-week plan. */
interface WeekSpan {
  start: number;
  end: number;
}

/** "5–7" for a run, "7" for one week — the noun is chosen once, by `weeksLine`. */
function spanLabel(span: WeekSpan): string {
  return span.start === span.end ? String(span.start) : `${String(span.start)}–${String(span.end)}`;
}

/** "a, b and c". Serial `and` rather than a bare comma list, which reads as truncated. */
function joinTerms(parts: readonly string[]): string {
  if (parts.length <= 1) return parts.join('');
  return `${parts.slice(0, -1).join(', ')} and ${parts.slice(-1).join('')}`;
}

/** ⚠️ "Week 7" only for ONE single week — matching the mesocycle heading, not a second convention. */
function weeksLine(spans: readonly WeekSpan[]): string {
  if (spans.length === 0) return '';
  const only = spans.length === 1 ? spans[0] : undefined;
  const noun = only !== undefined && only.start === only.end ? 'Week' : 'Weeks';
  return `${noun} ${joinTerms(spans.map(spanLabel))}`;
}

function spansOf(mesocycles: readonly PlanMesocycle[], phase: Phase): WeekSpan[] {
  return mesocycles
    .filter((mesocycle) => mesocycle.phase === phase)
    .map((mesocycle) => ({ start: mesocycle.start_week, end: mesocycle.end_week }));
}

/* One phase's place in THIS plan, or `null` when the plan has no block of it. ⚠️ EVERY occurrence:
   `strength` runs twice in a 28-week plan and `deload` six times — never "this block is weeks 5-7". */
export function phaseInPlan(plan: PlanTree, phase: Phase): PhaseInPlan | null {
  const spans = spansOf(plan.mesocycles, phase);
  if (spans.length === 0) return null;

  return { weeks: weeksLine(spans) };
}

/** Where ONE session sits: the week it is in, and the block of the plan that week belongs to. */
export interface SessionBlock {
  /** Plan-global week number, `1..week_count` — `microcycle.week_no`. */
  weekNo: number;
  phase: Phase;
  startWeek: number;
  endWeek: number;
}

/* Identity, and `id` is null on a PREVIEWED plan: reference equality is what `selectSession`
   actually returns, the id is what survives a re-fetch handing back a fresh object. */
function isSameSession(candidate: PlanSession, session: PlanSession): boolean {
  return candidate === session || (candidate.id != null && candidate.id === session.id);
}

/* ⚠️ `selectSession` FLATTENS the tree, so its `PlanSession` has lost its week and its phase.
   This walks them back. `null` when the session belongs to no block — say nothing, never guess. */
export function sessionBlock(
  plan: PlanTree | null | undefined,
  session: PlanSession | null | undefined,
): SessionBlock | null {
  if (plan == null || session == null) return null;

  for (const mesocycle of plan.mesocycles) {
    for (const microcycle of mesocycle.microcycles) {
      if (!microcycle.sessions.some((candidate) => isSameSession(candidate, session))) continue;
      return {
        weekNo: microcycle.week_no,
        phase: mesocycle.phase,
        startWeek: mesocycle.start_week,
        endWeek: mesocycle.end_week,
      };
    }
  }
  return null;
}

/* The reminder's visible line, as badges. ⚠️ It describes the session ON SCREEN, which on a rest
   day is the NEXT one — so every figure here comes from `block`, never from today's date. */
export function sessionBlockFacts(
  plan: PlanTree,
  block: SessionBlock,
  phaseLabel: string,
): PlanFact[] {
  return [
    { label: 'Week', value: `${String(block.weekNo)} of ${String(plan.week_count)}` },
    {
      label: 'Block',
      value: `${phaseLabel} · wk ${spanLabel({ start: block.startWeek, end: block.endWeek })}`,
    },
  ];
}
