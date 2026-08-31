import type { PlanMesocycle, PlanSession } from '../api/types';
import { humanise } from '../library/browse';

import { weekdayName } from './blueprint';

/* One phase, week by week: 7 weekday columns x one row per week, ONE BLOCK PER DAY. The
   codes are Kilian's own; `styles/_plan.scss` carries why they are clipped, never hidden. */

/** Monday first, matching `planned_session.weekday` and `blueprint.ts::weekdayName`. */
export const WEEKDAY_COUNT = 7;

/* ⚠️ 1 to 3 characters, and `strength` is deliberately absent: there is no general strength
   aspect yet, so a strength day reads `P`. That is issue #98, sequenced after this table. */
const ASPECT_CODES: Readonly<Record<string, string>> = {
  finger_strength: 'FS',
  power: 'P',
  power_endurance: 'PE',
  endurance: 'E',
  technique: 'T',
  core_tension: 'C&T',
  antagonist_prehab: 'A&P',
  mobility: 'M',
};

/** The eight seeded aspect keys, in legend order. */
export const ASPECT_KEYS: readonly string[] = Object.keys(ASPECT_CODES);

export interface PhaseWeekAspect {
  readonly key: string;
  readonly name: string;
  readonly code: string;
}

export interface PhaseWeekDay {
  readonly weekday: number;
  readonly aspects: readonly PhaseWeekAspect[];
}

export interface PhaseWeekRow {
  readonly weekNo: number;
  readonly days: readonly PhaseWeekDay[];
}

export interface PhaseWeek {
  readonly rows: readonly PhaseWeekRow[];
  readonly legend: readonly PhaseWeekAspect[];
}

/** A key with no code yet gets its initials, so a new aspect is short rather than unrenderable. */
function initials(key: string): string {
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase())
    .join('');
}

export function aspectCode(key: string): string {
  return ASPECT_CODES[key] ?? initials(key);
}

/** The other direction, so the legend and the cells cannot drift apart. */
export function aspectOfCode(code: string): string | null {
  return ASPECT_KEYS.find((key) => aspectCode(key) === code) ?? null;
}

export function aspect(key: string): PhaseWeekAspect {
  return { key, name: humanise(key), code: aspectCode(key) };
}

export const WEEKDAY_LABELS: readonly string[] = Array.from({ length: WEEKDAY_COUNT }, (_, day) =>
  weekdayName(day).slice(0, 3),
);

/* One LINE per block, in `order_index` order — the same blocks in the same order as the week
   card below it. Dropping a repeated aspect would make the two disagree about the day. */
function dayAspects(weekday: number, sessions: readonly PlanSession[]): PhaseWeekAspect[] {
  return sessions
    .filter((session) => session.weekday === weekday)
    .flatMap((session) =>
      [...session.blocks]
        .sort((a, b) => a.order_index - b.order_index)
        .map((block) => aspect(block.aspect_key)),
    );
}

export function phaseWeeks(mesocycle: PlanMesocycle): PhaseWeek {
  return {
    rows: mesocycle.microcycles.map((microcycle) => ({
      weekNo: microcycle.week_no,
      days: Array.from({ length: WEEKDAY_COUNT }, (_, weekday) => ({
        weekday,
        aspects: dayAspects(weekday, microcycle.sessions),
      })),
    })),
    legend: ASPECT_KEYS.map((key) => aspect(key)),
  };
}
