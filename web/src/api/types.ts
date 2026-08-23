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

/** `GET /api/profile` and the body of every `PATCH` response. */
export type Profile = Schemas['ProfileResponse'];
export type AspectRating = Schemas['AspectRatingOut'];
export type Injury = Schemas['InjuryOut'];

/** `PATCH /api/profile`. Every field is optional; a list replaces the set it names. */
export type ProfilePatch = Schemas['ProfilePatchRequest'];
export type AspectRatingInput = Schemas['AspectRatingIn'];
export type InjuryInput = Schemas['InjuryIn'];
