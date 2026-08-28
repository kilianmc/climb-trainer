import type { LibraryExercise, PlanBlock, PlanSession, PlanTree, ProtocolKind } from '../api/types';

/** Plan-tree builders shared by the session tests. Not a `.test.ts` file because several
 * suites need the same shapes, and a duplicated nine-field `SetOut` is how they drift. */

export interface SetSpec {
  id?: number | null;
  set_index?: number;
  target_reps?: number | null;
  target_work_seconds?: number | null;
  target_rest_seconds?: number | null;
}

export function makeSet(spec: SetSpec = {}) {
  return {
    id: spec.id ?? null,
    set_index: spec.set_index ?? 1,
    target_grade_id: null,
    target_intensity_pct: null,
    target_load_kg: null,
    target_reps: spec.target_reps ?? null,
    target_rest_seconds: spec.target_rest_seconds ?? null,
    target_rpe: null,
    target_work_seconds: spec.target_work_seconds ?? null,
  };
}

export interface BlockSpec {
  protocol_kind?: ProtocolKind;
  exercise_key?: string;
  exercise_id?: number | null;
  order_index?: number;
  rest_between_sets_seconds?: number | null;
  rest_after_seconds?: number | null;
  sets?: ReturnType<typeof makeSet>[];
}

export function makeBlock(spec: BlockSpec = {}): PlanBlock {
  return {
    aspect_key: 'finger_strength',
    // `?? 11` would swallow an explicit `null`, which is the previewed-plan case.
    exercise_id: 'exercise_id' in spec ? (spec.exercise_id ?? null) : 11,
    exercise_key: spec.exercise_key ?? 'max_hangs',
    id: 101,
    order_index: spec.order_index ?? 0,
    protocol_kind: spec.protocol_kind ?? 'max_hang',
    rest_between_sets_seconds: spec.rest_between_sets_seconds ?? null,
    rest_after_seconds: spec.rest_after_seconds ?? null,
    sets: spec.sets ?? [makeSet()],
    shortfall: null,
  };
}

export function makeSession(blocks: PlanBlock[], scheduledOn = '2026-08-28'): PlanSession {
  return {
    activity_kind: 'strength',
    blocks,
    estimated_minutes: 90,
    id: 5001,
    scheduled_on: scheduledOn,
    shortfalls: [],
    status: 'planned',
    title: 'Finger strength',
    weekday: 4,
  };
}

/** One mesocycle, one microcycle, whatever sessions are handed in. */
export function makePlan(sessions: PlanSession[]): PlanTree {
  return {
    activated_at: '2026-08-24T09:00:00Z',
    current_grade_id: 206,
    discipline: 'sport',
    generator_input: {},
    generator_version: '1.0.0',
    grade_gap: 2,
    id: 900,
    mesocycles: [
      {
        end_week: 4,
        id: 910,
        microcycles: [
          {
            id: 920,
            is_deload: false,
            phase: 'base',
            sessions,
            start_date: '2026-08-24',
            week_no: 1,
          },
        ],
        phase: 'base',
        start_week: 1,
      },
    ],
    name: 'Road to 7a',
    notes: [],
    shortfalls: [],
    start_date: '2026-08-24',
    target_grade_id: 208,
    week_count: 4,
  };
}

export function makeLibrary(): ReadonlyMap<string, LibraryExercise> {
  return new Map();
}
