/**
 * Readable names for the generated API types.
 *
 * `schema.ts` is machine-written and reached through `components['schemas'][…]`, which is
 * accurate and unpleasant to read at every use site. This file is the only place that
 * indexing appears, so a renamed Python model breaks here — one file, one diff — instead
 * of in every component that mentioned it.
 *
 * **This replaced `api/vocabularies.ts`**, which mirrored the closed vocabularies by hand
 * because no endpoint exposed them (PR #8's note said so, and said codegen would retire
 * it). `GET /api/vocabulary` now returns them, so the values arrive at runtime from the
 * server and the *types* come from the schema — the drift the old file's contract test
 * existed to catch is no longer expressible.
 *
 * Types only. Nothing here has a runtime value, which is what lets `verbatimModuleSyntax`
 * erase the whole module at build time.
 */

import type { components } from './schema';

type Schemas = components['schemas'];

/** `GET /api/vocabulary`. Reference data; identical for every user. */
export type Vocabulary = Schemas['VocabularyResponse'];
export type GradeSystem = Schemas['GradeSystemOut'];
export type Grade = Schemas['GradeOut'];
/** A seeded lookup row — a climbing aspect, a piece of equipment, an injury area. */
export type ReferenceRow = Schemas['ReferenceRowOut'];
export type Discipline = Schemas['Discipline'];

/**
 * `GET /api/library?v=<buildId>` — the exercise library, whole, in one response.
 *
 * ⚠️ Reference content, identical for every user, **permanently**: the response is CDN
 * cached with no `Vary: Authorization`. If a field on `LibraryExercise` ever describes the
 * *reader* rather than the exercise, that is a cross-account leak, not a feature — see the
 * rule at the top of `server/library/routes.py`.
 */
export type ExerciseLibrary = Schemas['ExerciseLibraryResponse'];
export type LibraryExercise = Schemas['ExerciseOut'];
export type Prescription = Schemas['PrescriptionOut'];

/** `GET /api/profile` and the body of every `PATCH` response. */
export type Profile = Schemas['ProfileResponse'];
export type AspectRating = Schemas['AspectRatingOut'];
export type Injury = Schemas['InjuryOut'];

/** `PATCH /api/profile`. Every field is optional; a list replaces the set it names. */
export type ProfilePatch = Schemas['ProfilePatchRequest'];
export type AspectRatingInput = Schemas['AspectRatingIn'];
export type InjuryInput = Schemas['InjuryIn'];

/**
 * `POST /api/plans/preview` — the plan the generator would build, never written.
 *
 * ⚠️ **A read expressed as a POST, and per-user.** `private, no-store`: unlike
 * `ExerciseLibrary` this body is assembled from one climber's grades, availability,
 * declared weakness and open injuries, so it must never reach a shared cache. `useQuery`
 * is still the right hook — Query's split is about cache semantics, not HTTP verbs.
 *
 * Two shapes worth knowing before writing the screen: a block names an `exercise_key` on
 * every path and additionally an `exercise_id` once persisted (join either against
 * `useLibrary()`), and `PrescribedSetTarget.target_load_kg` is a **string** (a `Decimal` on
 * the wire) and is `null` for every set in v1.0.0.
 *
 * ⚠️ **`PlanTree` is ONE type for a previewed plan and a persisted one**, so the screen has
 * one renderer. The difference is which nullable fields are filled: a preview is not a row,
 * so every `id` — plus a block's `exercise_id`, a session's `status` and the plan's
 * `activated_at` — is `null`. A persisted plan fills all of them. Every other field has the
 * same name and the same meaning on both paths, `shortfalls` and `notes` included.
 */
export type PlanPreviewRequest = Schemas['PlanPreviewRequest'];
export type PlanTree = Schemas['PlanOut'];
/**
 * `GET /api/plans/active`. ⚠️ **`{plan: null}` is a 200 and it is the empty state**, not an
 * error — every new account is in it. An envelope rather than a bare nullable body so the
 * endpoint can grow a sibling field without changing shape; `server/plans/routes.py::
 * ActivePlanResponse` carries the reasoning.
 */
export type ActivePlanResponse = Schemas['ActivePlanResponse'];
/** `POST /api/plans/{plan_id}/abandon`. The timestamp set, or the one already there. */
export type PlanAbandoned = Schemas['PlanAbandonResponse'];
export type PlanMesocycle = Schemas['MesocycleOut'];
export type PlanMicrocycle = Schemas['MicrocycleOut'];
export type PlanSession = Schemas['SessionOut'];
export type PlanBlock = Schemas['BlockOut'];
export type PrescribedSetTarget = Schemas['SetOut'];
/** An aspect a phase cannot train with the gear assumed, and what would unlock it. Never a gate. */
export type PlanShortfall = Schemas['ShortfallOut'];
/** An honest caveat about the plan as a whole — fewer sessions than asked, or a capped gap. */
export type PlanNote = Schemas['NoteOut'];
export type Phase = Schemas['Phase'];
export type ActivityKind = Schemas['ActivityKind'];
export type ProtocolKind = Schemas['ProtocolKind'];

/** `PUT /api/sessions/{client_uuid}`. ⚠️ `sets` is a DELTA and `duration_minutes` is required
 * on every request — CLAUDE.md's "Logging a session" carries both rules. */
export type SessionLogRequest = Schemas['SessionLogRequest'];
export type SessionLogResponse = Schemas['SessionLogResponse'];
/** One set that happened. Replaced whole by its `client_uuid`; the client mints that uuid. */
export type LoggedSetInput = Schemas['LoggedSetIn'];
/** The server's id for one set, so the outbox can retire it. No user free text is echoed. */
export type LoggedSetAck = Schemas['LoggedSetAck'];
