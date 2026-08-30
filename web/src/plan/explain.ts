import type { Phase, PlanMesocycle, PlanSession, PlanTree, Vocabulary } from '../api/types';
import { humanise } from '../library/browse';

/* How THIS plan applies the phases, from the payload alone: `GET /api/plans/active` already
   carries every fact below, and `climbing_band` carries the training constants (see `PlanOut`). */

/** One row of a plan-specific block. Structured, because interpolated prose breaks at the edges. */
export interface PlanFact {
  label: string;
  value: string;
}

/** One phase, as it appears in THIS plan. `weeks` is every occurrence, not the first. */
export interface PhaseInPlan {
  weeks: string;
  facts: PlanFact[];
}

/** One contiguous run of weeks. A phase RECURS — `deload` has six of these in a 28-week plan. */
interface WeekSpan {
  start: number;
  end: number;
}

function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count === 1 ? one : many}`;
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

/* `generator_input` is `Record<string, unknown>` on the wire — the reproducibility record, not a
   typed model. So it is read defensively: an unrecognised shape omits a fact, never renders one. */
function intField(input: Readonly<Record<string, unknown>>, key: string): number | null {
  const value = input[key];
  return typeof value === 'number' && Number.isInteger(value) ? value : null;
}

function stringField(input: Readonly<Record<string, unknown>>, key: string): string | null {
  const value = input[key];
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function gradeLabel(vocabulary: Vocabulary, gradeId: number | null): string | null {
  if (gradeId === null) return null;
  return vocabulary.grades.find((grade) => grade.id === gradeId)?.label ?? null;
}

/* What this plan is FOR, in its own numbers: grade labels from the vocabulary the screen already
   holds, everything else off the plan. No request, and no training constant derived here. */
export function planGoalFacts(plan: PlanTree, vocabulary: Vocabulary): PlanFact[] {
  const facts: PlanFact[] = [];
  const current = gradeLabel(vocabulary, plan.current_grade_id);
  const target = gradeLabel(vocabulary, plan.target_grade_id);

  if (current !== null && target !== null) {
    facts.push({ label: 'Goal', value: `${current} → ${target}` });
  } else if (plan.grade_gap > 0) {
    // No label to name — the plan was built from an ordinal the vocabulary no longer offers.
    facts.push({ label: 'Goal', value: `${plural(plan.grade_gap, 'rung', 'rungs')} harder` });
  }

  facts.push({
    label: 'Length',
    value: `${plural(plan.week_count, 'week', 'weeks')} in ${plural(
      plan.mesocycles.length,
      'block',
      'blocks',
    )}`,
  });
  facts.push({ label: 'Discipline', value: humanise(plan.discipline) });

  const sessions = intField(plan.generator_input, 'sessions_per_week');
  if (sessions !== null) {
    facts.push({ label: 'Sessions', value: `${plural(sessions, 'session', 'sessions')} a week` });
  }

  const strength = stringField(plan.generator_input, 'strength_aspect_key');
  if (strength !== null) facts.push({ label: 'Your strong point', value: humanise(strength) });
  const weakness = stringField(plan.generator_input, 'weakness_aspect_key');
  if (weakness !== null) facts.push({ label: 'Your weak point', value: humanise(weakness) });

  const band = plan.climbing_band;
  if (band !== null) {
    facts.push({ label: 'Your band', value: humanise(band.level) });
    facts.push({
      label: 'On the wall',
      value:
        `${String(band.climbing_target_pct_low)}–${String(band.climbing_target_pct_high)}% of ` +
        `each week, never under ${String(band.climbing_floor_pct)}%`,
    });
  }

  return facts;
}

/* One phase's place in THIS plan, or `null` when the plan has no block of it. ⚠️ EVERY occurrence:
   `strength` runs twice in a 28-week plan and `deload` six times — never "this block is weeks 5-7". */
export function phaseInPlan(plan: PlanTree, phase: Phase): PhaseInPlan | null {
  const spans = spansOf(plan.mesocycles, phase);
  if (spans.length === 0) return null;

  const weeks = spans.reduce((total, span) => total + (span.end - span.start + 1), 0);
  const facts: PlanFact[] = [
    {
      label: 'Blocks',
      value: `${plural(spans.length, 'block', 'blocks')} · ${String(weeks)} of ${plural(
        plan.week_count,
        'week',
        'weeks',
      )}`,
    },
  ];

  const band = plan.climbing_band;
  // ⚠️ Absent, not "0 sessions": the beginner band owes none, and `finger_phases` is the
  // server's list of the phases that owe any — this file never guesses which those are.
  if (band !== null && band.finger_sessions_per_week > 0 && band.finger_phases.includes(phase)) {
    facts.push({
      label: 'Hangboard',
      value: `${plural(band.finger_sessions_per_week, 'session', 'sessions')} a week`,
    });
  }

  // Only on an exact key match. The aspects a phase leads on live in the generator, so inferring
  // "mobility belongs to deload" here would be a second copy of `selection.py`'s decisions.
  if (stringField(plan.generator_input, 'strength_aspect_key') === phase) {
    facts.push({ label: 'You called this', value: 'a strong point' });
  }
  if (stringField(plan.generator_input, 'weakness_aspect_key') === phase) {
    facts.push({ label: 'You called this', value: 'a weak point' });
  }

  return { weeks: weeksLine(spans), facts };
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
