/**
 * The API's closed vocabularies, mirrored for the web.
 *
 * **Hand-written on purpose, and temporarily.** The plan is OpenAPI codegen (PR #9), but
 * no endpoint exposes any of these tables yet, so `openapi-typescript` would run against
 * a schema that mentions none of them and emit nothing. Installing a generator to
 * produce an empty file — and wiring it into the quality gate — would be worse than
 * these six lists: a build step whose output nobody can check is a build step that is
 * wrong silently. So: written by hand now, replaced by codegen when there are endpoints.
 *
 * **The values are the DATABASE values, not display labels.** Each array is exactly the
 * value list of a native Postgres enum (`server/domain/vocabulary.py`, wired up in
 * `server/models.py` with `values_callable`), so a string from here can be sent straight
 * to the API and compared straight against a response. `tests/test_vocabulary_contract.py`
 * parses this file from the Python side and fails if the two ever disagree — that test is
 * what stands in for codegen until PR #9, and it is the reason the arrays below are
 * written as plain literals rather than assembled or spread.
 *
 * **Labels are NOT here.** `redpoint` is shown as "Send" on a boulder and "Redpoint" on a
 * rope, `power_endurance` as "Power endurance" — display strings belong with the
 * components that render them, and mixing them in here is how a label edit turns into a
 * database value edit.
 *
 * `as const` + an indexed access type, rather than a TypeScript `enum`: the array is
 * needed at runtime anyway (to populate a select), and deriving the union from it means
 * the two can never drift. A TS `enum` would give a type and a separate object with no
 * relationship to any list the UI iterates.
 */

/** Boulder or rope. `sport` covers rope grades generally — French and YDS. */
export const DISCIPLINES = ['boulder', 'sport'] as const;
export type Discipline = (typeof DISCIPLINES)[number];

/**
 * What a logged activity was. `climbing` is the only kind with session detail attached;
 * `other` is the escape hatch that keeps an unanticipated kind loggable without a
 * database migration.
 */
export const ACTIVITY_KINDS = ['climbing', 'cardio', 'strength', 'mobility', 'other'] as const;
export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

/**
 * How a climb was done. There is deliberately no separate `send`: it is the boulderer's
 * word for `redpoint`, so it is a label, not a value.
 */
export const ASCENT_STYLES = [
  'onsight',
  'flash',
  'redpoint',
  'top_rope',
  'repeat',
  'attempt',
] as const;
export type AscentStyle = (typeof ASCENT_STYLES)[number];

/** How an exercise is executed in time — what the session player has to drive. */
export const PROTOCOL_KINDS = [
  'max_hang',
  'repeaters',
  'intervals',
  'circuit',
  'limit_boulder',
  'straight_sets',
  'laps',
  'hold',
  'other',
] as const;
export type ProtocolKind = (typeof PROTOCOL_KINDS)[number];

/** A mesocycle's training emphasis. `deload` and `taper` are phases, not week flags. */
export const PHASES = [
  'base',
  'strength',
  'power',
  'power_endurance',
  'performance',
  'deload',
  'taper',
] as const;
export type Phase = (typeof PHASES)[number];

/** Where a *planned* session got to. Never used on a logged one. */
export const SESSION_STATUSES = [
  'planned',
  'in_progress',
  'completed',
  'skipped',
  'rescheduled',
] as const;
export type SessionStatus = (typeof SESSION_STATUSES)[number];
