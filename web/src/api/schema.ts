/**
 * GENERATED FILE — do not edit by hand.
 *
 * `npm run codegen:api` (repo root) regenerates it from the FastAPI application:
 * `server/openapi_schema.py` prints the OpenAPI document and
 * `web/scripts/gen-api-types.mjs` turns it into these types.
 *
 * `tests/test_vocabulary_contract.py` checks BOTH digests below, so this file can
 * neither fall behind the server nor be edited by hand without failing the gate:
 *
 *   openapi-sha256  the OpenAPI document it was generated from
 *   types-sha256    everything below this comment block
 *
 * openapi-sha256: c5da8bc588e9614dc6158f521bd44e2d2b11fb376c569c3c1220b2ad1c00ec87
 * types-sha256: 2d270260237467cad70a6cef475f580d06db6f9f840af838455897b9e1a1d172
 */

export interface paths {
  '/api/auth/demo': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Demo
     * @description Issue a 1-hour, read-only token for the seeded demo account. **Issues ZERO SQL.**
     *
     *     ## The empty signature is the security control
     *
     *     Note what is *not* a parameter: there is no `Session`, no `Request`, nothing that can
     *     reach the database. That is deliberate and structural — zero-DB holds **by
     *     construction**, not by a test or a convention, and reintroducing a query means adding
     *     a dependency back to this line, which is a visible diff a reviewer will stop on.
     *     Do not "just look up the demo user", do not cache or memoise a lookup: the handler
     *     must remain unable to query. `DEMO_USER_ID` is pinned in `server/seed.py` precisely so
     *     the token's `sub` needs no lookup.
     *
     *     ## Why, with the arithmetic
     *
     *     Neon Free is 100 CU-hr/month at the 0.25 CU floor = **400 awake-hours** in a 730-hour
     *     month, and autosuspend is fixed at 5 minutes (not configurable on Free). A bot
     *     trickling **one request per minute** at a DB-touching public endpoint therefore keeps
     *     the compute awake 100% of the time, costs ~182 CU-hr/month and busts the whole
     *     allowance by itself — while staying inside any rate limit we are able to configure.
     *     The old Postgres rate limit could not stop that, because enforcing it was itself a
     *     write. So the query is gone instead, and the rate limit moved to a **Vercel WAF rule
     *     on `/api/auth/*`**. Unlimited minting now costs invocations and CPU, and zero Neon
     *     time, which is what makes it an acceptable worst case.
     *
     *     ## Consequence: the 503 is gone, and that is on purpose
     *
     *     This used to return 503 when the seed had not run. It cannot detect that any more, so
     *     **demo mode always issues a token** — against an unseeded database the user simply
     *     sees empty data. That is the better failure: the endpoint stays up, and an empty demo
     *     is a visibly wrong deployment rather than a broken one. Nobody should have to discover
     *     it, hence this paragraph.
     */
    post: operations['demo_api_auth_demo_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/auth/login': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Login
     * @description Exchange credentials for an access token and a fresh refresh family.
     */
    post: operations['login_api_auth_login_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/auth/logout': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Logout
     * @description Revoke the presented refresh family and clear the cookie.
     *
     *     Idempotent, and never an error: no cookie, an expired cookie or a forged one all
     *     return the same success. A logout that could fail would be a way to probe which
     *     tokens are real, and a client stuck unable to log out is worse than useless.
     */
    post: operations['logout_api_auth_logout_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/auth/me': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Me
     * @description The authenticated principal, straight from the verified token.
     *
     *     **Touches no database at all.** Two reasons, both in CLAUDE.md: access-token
     *     verification is stateless precisely so an authenticated request does not wake Neon,
     *     and there must be no `last_seen` / `last_used_at` column — a write-per-read is the
     *     classic accident that defeats every other compute rule here. Profile data (email,
     *     target grade, settings) belongs to the profile endpoint in a later PR, where reading
     *     it is the point of the request.
     */
    get: operations['me_api_auth_me_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/auth/refresh': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Refresh Tokens
     * @description Rotate the refresh cookie and mint a new access token.
     *
     *     The client calls this **lazily, only after a 401** — never on a timer. A periodic
     *     refresh is a periodic database write, which is the largest avoidable consumer of the
     *     compute budget (CLAUDE.md).
     *
     *     **409** means the cookie presented was rotated seconds ago by another mount or tab and
     *     the client should simply send it again; **401** means there is no usable family left.
     *     Documented here rather than in a `responses=` block because no route in this module
     *     declares one — `register`'s 409 and `login`'s 401 are described the same way, and
     *     `/openapi.json` is off in production anyway.
     */
    post: operations['refresh_tokens_api_auth_refresh_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/auth/register': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Register
     * @description Create an account, log it in, and start a refresh family.
     *
     *     **A duplicate email returns 409, and that is a considered trade-off.** The textbook
     *     anti-enumeration answer is a generic "check your inbox" that reveals nothing — but it
     *     only works when there IS an inbox step. This product has no email verification, so a
     *     generic response would leave a real person staring at a form that appears to have
     *     worked while no account exists, with no way to discover that they already have one.
     *     Being honest here is worth more than hiding a fact that `/api/auth/login` timing and
     *     a password-reset flow would eventually expose anyway. **Rate limiting is the
     *     mitigation**: `REGISTER` is 3 per hour per client, which makes enumerating a list of
     *     addresses impractical.
     *
     *     **Invite-gated since issue #35.** A valid, unexpired, unrevoked, not-exhausted code is
     *     required, and spending it happens in this handler's transaction so that a registration
     *     which fails afterwards does not burn a use. The invite's id is recorded on the account,
     *     so a use is attributable to a person and not merely to a counter.
     */
    post: operations['register_api_auth_register_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/health': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Health
     * @description Liveness only — deliberately leaks nothing about the deployment.
     *
     *     Public (listed in `PUBLIC_ROUTES`) and DB-free: a health check that queried the
     *     database would restart Neon's five-minute awake window on every probe.
     */
    get: operations['health_api_health_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/library': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Read Library
     * @description The library, ordered by aspect. Authenticated like every other route.
     *
     *     User-independent: nothing here is scoped by `user_id` because nothing here belongs to
     *     a user, and per the rule at `_CACHE_CONTROL` nothing here ever will. Read-only — the
     *     library is written by `server/contentseed.py`, out of band.
     *
     *     `v` is **declared and deliberately unused**. It exists so the client can put a build id
     *     in the URL and so the schema documents it; reading it here — even to log it — is the
     *     one change that would make the CDN's single cache entry wrong.
     */
    get: operations['read_library_api_library_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/plans': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Create Plan
     * @description Generate this user's plan, persist it activated, and return it with ids. **201.**
     *
     *     A **Tier-1 write**: one request, one transaction, one Neon wake.
     *
     *     **The server regenerates; it never accepts a tree.** The body is `PlanPreviewRequest` —
     *     `start_date` and nothing else, `extra="forbid"`. A client-supplied tree would let any caller
     *     fabricate an arbitrary plan, prescriptions against exercises their injuries contraindicate
     *     included, and it would be a ~600 KiB request body. `user_id` comes from `principal.user_id`
     *     and from nowhere else. The generation path is the preview's, reused rather than reimplemented,
     *     so a plan can never be persisted in a shape the preview would not have shown.
     *
     *     **One transaction, all-or-nothing.** Four steps, one `commit()` at the end (each route commits
     *     itself; `get_session` deliberately does not): stand the active plan down, resolve every
     *     `exercise_key`, insert the tree, serialise. A failure anywhere leaves zero rows in all six
     *     tables, because nothing before the `commit()` is durable.
     *
     *     **409 is a legitimate answer, not a fault.** A double-tap races: both requests stand the same
     *     plan down and both insert, and the second trips `uq_plan_one_active_per_user`. The user does
     *     have an active plan, so the client treats it as "you already have one" and refetches.
     */
    post: operations['create_plan_api_plans_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/plans/active': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Active Plan
     * @description This user's active plan with ids, or `{"plan": null}`. Always **200** — see the model.
     *
     *     `.one_or_none()` rather than `.first()`: "at most one" is `uq_plan_one_active_per_user`'s job,
     *     and if the index were ever dropped a silent `LIMIT 1` would hide that while quietly picking an
     *     arbitrary plan.
     */
    get: operations['active_plan_api_plans_active_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/plans/preview': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Preview Plan
     * @description Build the plan this user's profile implies, and return it. **Writes nothing.**
     *
     *     Enforced three ways rather than asserted: the generator is pure (ruff `TID251` in
     *     `server/domain/.ruff.toml`), this handler issues only `SELECT`s, and for a demo principal
     *     `SET LOCAL transaction_read_only` is already on, so Postgres itself would refuse.
     *     `tests/test_plans_api.py` counts rows after a successful preview.
     */
    post: operations['preview_plan_api_plans_preview_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/profile': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Read Profile
     * @description The authenticated user's profile. Reads only — nothing is created on a GET.
     *
     *     A touch-on-read write is the classic accident that defeats every other compute rule
     *     in CLAUDE.md, and "create the row when it is first read" is exactly that.
     */
    get: operations['read_profile_api_profile_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    /**
     * Patch Profile
     * @description Upsert any subset of the profile and return the whole of it.
     *
     *     A **Tier-1 write** (CLAUDE.md, "Two write tiers"): a profile change is deliberate and
     *     low-frequency, so it goes through immediately rather than into the outbox.
     *
     *     Order matters and is not incidental: **every reference in the body is resolved before
     *     the first write**, so a 422 leaves nothing behind. The full profile comes back so the
     *     caller never needs a follow-up GET to redraw the completion bar, and so the bar can
     *     never disagree with the database about what is set.
     */
    patch: operations['patch_profile_api_profile_patch'];
    trace?: never;
  };
  '/api/profile/reset': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Reset Profile
     * @description Un-answer the four onboarding steps, in one transaction, and return the profile.
     *
     *     Exists so that `PATCH` did not have to change: making `null` mean "clear" in
     *     `ProfilePatchRequest` was **considered and rejected**, because `null` there means "not in
     *     this request", which is what lets onboarding send one step at a time — flipping it would
     *     turn every omission into a destructive spelling one typo away.
     *
     *     It clears every column the four steps own (including `primary_discipline`, derived from the
     *     target grade and so it has to go with it) and every `user_aspect_rating` row.
     *     ⚠️ **Open `user_injury` rows only — resolved rows are HISTORY and are not touched**:
     *     flag -> resolve -> re-flag is what that table exists for, and a reset is not a claim about a
     *     past injury. **Not** `display_name` or `show_body_metrics`, which belong to no step.
     *
     *     A Tier-1 write. It returns the whole profile so the caller redraws the completion bar from
     *     the response and can never disagree with the database. **Idempotent, and it creates no row.**
     */
    post: operations['reset_profile_api_profile_reset_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/sessions/completion': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Session Completion
     * @description How much of each planned session in `from`..`to` actually got done.
     *
     *     **Partial completion is a DERIVED QUERY, not a column.** `planned_session.status` says
     *     whether Finish was pressed; this counts the blocks with at least one logged set, which is
     *     the only figure that can say WHICH two of three parts — and the rule behind it will be
     *     tuned, which is why no `planned_session` column holds it.
     *
     *     **Its own endpoint, deliberately.** `GET /api/plans/active` is already the heaviest payload
     *     in the app and only this screen reads these numbers, so they are fetched beside it rather
     *     than inside it.
     *
     *     **One statement, no per-row N+1**, one Neon wake, and read-only: a demo token may call it.
     *     `skipped` is inferred from `as_of` — nothing in the app writes that status.
     */
    get: operations['session_completion_api_sessions_completion_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/sessions/{client_uuid}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /**
     * Log Session
     * @description Create or locate this climber's session by the uuid their client minted, and merge. 200.
     *
     *     A **Tier-1 write**: one request, one transaction, one Neon wake, and **at most five
     *     statements whatever the set count**. Called at start (`sets: []`), at every mid-run moment
     *     that piggybacks the outbox, and at Finish (`finished: true`).
     *
     *     **`sets` merges, it never replaces.** A set is replaced whole by its `client_uuid`; a set
     *     already stored and absent from this payload is untouched, because a piggyback carries only
     *     the unsent tail. **`duration_minutes` only ever grows** — the client must send elapsed
     *     minutes so far, never an estimate, and issue #12's "edit a logged session" cannot reuse
     *     this route because it cannot shorten one.
     *
     *     A `planned_session_id` or `prescribed_set_id` outside the caller's own plan tree is a 404
     *     identical to the missing case. A set whose `exercise_id` disagrees with its prescription is
     *     a 422 that rejects the **whole flush**, because the rest of that block is then suspect.
     *     `planned_session.status` advances to `in_progress`, or `completed` when finished, and never
     *     regresses. Ascents are not loggable here.
     */
    put: operations['log_session_api_sessions__client_uuid__put'];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/vocabulary': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Read Vocabulary
     * @description Everything onboarding and the loggers need to render a closed input.
     *
     *     Authenticated like every other route (deny-by-default), but user-independent: nothing
     *     here is scoped by `user_id` because nothing here belongs to a user.
     */
    get: operations['read_vocabulary_api_vocabulary_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /**
     * ActivePlanResponse
     * @description `{"plan": null}` when there is none — a **200**, not a 404.
     *
     *     "No plan yet" is the state every new account is in, and the `/plan` screen renders it as an
     *     ordinary view with a Generate button. A 404 would make the normal case an error at three
     *     layers that all treat 4xx as failure: `apiFetch` throws, the query retry predicate skips 4xx
     *     as unwinnable, and a route-level guard would see `data === undefined` and swap itself for a
     *     fallback.
     *
     *     A wrapper object rather than a bare nullable body, so the endpoint can grow a sibling field
     *     without changing shape and no client has to handle a top-level `null`.
     */
    ActivePlanResponse: {
      plan: components['schemas']['PlanOut'] | null;
    };
    /**
     * ActivityKind
     * @description What a logged activity *was*, on the `activity` supertype.
     *
     *     **`other` is the escape hatch, and it is load-bearing.** Without it, the first kind
     *     of training nobody anticipated (a yoga class, a swim, a physio appointment) is
     *     unloggable until someone ships an `ALTER TYPE ... ADD VALUE` migration — so the
     *     honest options would be "lie about it" or "don't log it", and both corrupt the load
     *     history that readiness and rest-day logic read.
     *
     *     Only `climbing` has a subtype row (`logged_session`); see `Activity` in
     *     `server/models.py` for why that is one table and not five.
     * @enum {string}
     */
    ActivityKind: 'climbing' | 'cardio' | 'strength' | 'mobility' | 'other';
    /**
     * AscentStyle
     * @description How a climb was done.
     *
     *     **There is deliberately no separate `send` value.** "Send" is the boulderer's word
     *     for what a rope climber calls a redpoint — one thing, two vernaculars — and storing
     *     both would mean every "did they top it?" query has to remember to list two values,
     *     which is exactly the kind of near-duplicate that gets one of them forgotten. The UI
     *     is free to *label* `REDPOINT` as "Send" on a boulder; the label is display, the
     *     value is data.
     *
     *     `ATTEMPT` records work on something not topped. It exists because a projecting
     *     session is real training load and real history, and a log that can only hold
     *     successes quietly overstates a climber's level.
     * @enum {string}
     */
    AscentStyle: 'onsight' | 'flash' | 'redpoint' | 'top_rope' | 'repeat' | 'attempt';
    /** AspectRatingIn */
    AspectRatingIn: {
      /** Climbing Aspect Id */
      climbing_aspect_id: number;
      /** Score */
      score: number;
    };
    /**
     * AspectRatingOut
     * @description One self-rated aspect. `rated_at` is what lets a stale rating be shown as stale.
     */
    AspectRatingOut: {
      /** Climbing Aspect Id */
      climbing_aspect_id: number;
      /**
       * Rated At
       * Format: date-time
       */
      rated_at: string;
      /** Score */
      score: number;
    };
    /**
     * BlockOut
     * @description One block of a session.
     *
     *     ⚠️ **`exercise_key` AND `exercise_id`, not one or the other.** The domain is DB-free and
     *     speaks keys, so a preview has the key and no id; a persisted block holds the id and the key is
     *     derived from it (`_exercise_reference`). Carrying both means the client's library lookup is
     *     written once for both paths.
     *
     *     ⚠️ `aspect_key` is read LIVE off `exercise.climbing_aspect_id` and can therefore drift, unlike
     *     the snapshotted `protocol_kind` — an accepted asymmetry, recorded on `models.py::SessionBlock`.
     *     It is also **not** `shortfall.aspect_key`, which names the aspect the generator *wanted* and
     *     could not fill — precisely why a block's shortfall has to be stored rather than derived.
     */
    BlockOut: {
      /** Aspect Key */
      aspect_key: string;
      /** Exercise Id */
      exercise_id?: number | null;
      /** Exercise Key */
      exercise_key: string;
      /** Id */
      id?: number | null;
      /** Order Index */
      order_index: number;
      protocol_kind: components['schemas']['ProtocolKind'];
      /** Rest After Seconds */
      rest_after_seconds: number | null;
      /** Rest Between Sets Seconds */
      rest_between_sets_seconds: number | null;
      /** Sets */
      sets: components['schemas']['SetOut'][];
      shortfall: components['schemas']['ShortfallOut'] | null;
    };
    /**
     * ClimbingBandOut
     * @description The training constants THIS plan was generated under. Derived, never stored.
     *
     *     ⚠️ **Keyed off `generator_input.current_ordinal`, never off the profile's grade today.**
     *     `Level` is not persisted (`server/domain/planner/climbing.py`), and it is what
     *     `CLIMBING_FLOOR_PCT`, `CLIMBING_TARGET_PCT` and `FINGER_SESSIONS_PER_WEEK` were read
     *     with when the tree was built. A climber who logs a harder grade tomorrow has not changed
     *     the plan in front of them, so a band re-derived from the profile would make the payload
     *     misdescribe its own contents.
     *
     *     Sent so **no client re-implements a training constant**: the ordinal thresholds are four
     *     named ceilings in one Python module, and re-deriving them in TypeScript would put the
     *     same numbers in two languages with nothing able to see them drift.
     *
     *     `finger_phases` is the set those sessions are owed in, so a client can place the figure
     *     without knowing which phases they are; `finger_sessions_per_week` is **0 for beginner**
     *     by design, and a renderer must omit the line rather than print a zero.
     */
    ClimbingBandOut: {
      /** Climbing Floor Pct */
      climbing_floor_pct: number;
      /** Climbing Target Pct High */
      climbing_target_pct_high: number;
      /** Climbing Target Pct Low */
      climbing_target_pct_low: number;
      /** Finger Phases */
      finger_phases: components['schemas']['Phase'][];
      /** Finger Sessions Per Week */
      finger_sessions_per_week: number;
      level: components['schemas']['Level'];
    };
    /**
     * ClosedVocabulariesOut
     * @description The native Postgres enums, as their persisted **values** (never member names).
     *
     *     Order is declaration order, which is also Postgres's `ORDER BY` order for these
     *     types and the order a picker should present them in.
     */
    ClosedVocabulariesOut: {
      /** Activity Kinds */
      activity_kinds: components['schemas']['ActivityKind'][];
      /** Ascent Styles */
      ascent_styles: components['schemas']['AscentStyle'][];
      /** Disciplines */
      disciplines: components['schemas']['Discipline'][];
      /** Phases */
      phases: components['schemas']['Phase'][];
      /** Protocol Kinds */
      protocol_kinds: components['schemas']['ProtocolKind'][];
      /** Session Statuses */
      session_statuses: components['schemas']['SessionStatus'][];
    };
    /**
     * Discipline
     * @description Closed vocabulary, mirrored by the native Postgres `discipline` enum.
     *
     *     `SPORT` covers rope grades generally (French, YDS) — the user-facing choice is
     *     "boulder or sport", which is why it is not called `ROUTE`.
     * @enum {string}
     */
    Discipline: 'boulder' | 'sport';
    /**
     * ExerciseLibraryResponse
     * @description The whole library. An object rather than a bare array, so the payload can grow a
     *     sibling field (a content revision, say) without breaking every client.
     */
    ExerciseLibraryResponse: {
      /** Exercises */
      exercises: components['schemas']['ExerciseOut'][];
    };
    /**
     * ExerciseOut
     * @description One library exercise, with everything a browse + detail UI needs.
     *
     *     `key` is the data contract and the rest is display or generator input, the same split
     *     as `ReferenceSpec`. `equipment_ids` is an **AND set**: every id is a requirement, so
     *     an empty list means the exercise needs nothing and is always prescribable — which is
     *     what replaces the `bodyweight` equipment row that deliberately does not exist.
     *
     *     `discipline` is NULL for most of the library (a hangboard protocol serves boulderers
     *     and rope climbers alike). `substitution_hint` is NULL for every finger-loading
     *     protocol on purpose — see `server/domain/exercises.py` for the safety boundary.
     */
    ExerciseOut: {
      /** Climbing Aspect Id */
      climbing_aspect_id: number;
      /** Contraindicated Injury Area Ids */
      contraindicated_injury_area_ids: number[];
      discipline: components['schemas']['Discipline'] | null;
      /** Equipment Ids */
      equipment_ids: number[];
      /** Id */
      id: number;
      /** Instructions */
      instructions: string;
      /** Key */
      key: string;
      /** Media Url */
      media_url: string | null;
      /** Name */
      name: string;
      /** Prescriptions */
      prescriptions: components['schemas']['PrescriptionOut'][];
      /** Progression Of Id */
      progression_of_id: number | null;
      protocol_kind: components['schemas']['ProtocolKind'];
      /** Regression Of Id */
      regression_of_id: number | null;
      /** Substitution Hint */
      substitution_hint: string | null;
    };
    /**
     * GradeOut
     * @description One rung of one scale.
     *
     *     `ordinal` is the shared integer ladder and is sent so the client can sort and compare
     *     without a second request. It is display/ordering input only — **a client never sends
     *     an ordinal back**; a grade goes on the wire as its `id` (CLAUDE.md).
     */
    GradeOut: {
      /** Grade System Id */
      grade_system_id: number;
      /** Id */
      id: number;
      /** Label */
      label: string;
      /** Ordinal */
      ordinal: number;
    };
    /**
     * GradeSystemOut
     * @description A grading scale. `discipline` is what makes the boulder/rope split selectable.
     */
    GradeSystemOut: {
      discipline: components['schemas']['Discipline'];
      /** Id */
      id: number;
      /** Key */
      key: string;
      /** Name */
      name: string;
    };
    /**
     * GuideLinkOut
     * @description One further-reading link. A record, not two parallel scalars: a URL with no label
     *     renders as bare markup, and only a pair can be `for`-looped without pairing checks.
     */
    GuideLinkOut: {
      /** Label */
      label: string;
      /** Url */
      url: string;
    };
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components['schemas']['ValidationError'][];
    };
    /**
     * InjuryIn
     * @description One flagged injury area, and optionally a note about it.
     *
     *     See the module docstring: **omitting `note` preserves whatever is stored; sending an
     *     explicit `null` clears it.** `note_was_sent` is the only way to tell, and it must be
     *     asked before the value — `None` is the post-validation value in both cases.
     */
    InjuryIn: {
      /** Injury Area Id */
      injury_area_id: number;
      /** Note */
      note?: string | null;
    };
    /**
     * InjuryOut
     * @description A currently-open injury. Resolved ones are history and are not returned here.
     *
     *     `note` is user free text and is escaped on output by React — never
     *     `dangerouslySetInnerHTML` (CLAUDE.md, "Notes are untrusted on OUTPUT too").
     */
    InjuryOut: {
      /** Injury Area Id */
      injury_area_id: number;
      /** Note */
      note: string | null;
      /**
       * Started On
       * Format: date
       */
      started_on: string;
    };
    /**
     * Level
     * @description The climber's band, by CURRENT grade. Never persisted — derived on every generate.
     * @enum {string}
     */
    Level: 'beginner' | 'intermediate' | 'advanced';
    /**
     * LoggedSetAck
     * @description The server's id for one set, so the client can retire it from the outbox.
     *
     *     Nothing the user typed is echoed back; see `SessionLogResponse`.
     */
    LoggedSetAck: {
      /**
       * Client Uuid
       * Format: uuid
       */
      client_uuid: string;
      /** Id */
      id: number;
      /** Set Index */
      set_index: number;
    };
    /**
     * LoggedSetIn
     * @description One set that happened, replaced whole by its `client_uuid`.
     *
     *     There is no omitted-versus-null distinction per set: a `logged_set` is minted complete when
     *     the set finishes, and a multi-row `VALUES` requires identical keys in every row anyway.
     */
    LoggedSetIn: {
      /** Actual Load Kg */
      actual_load_kg?: number | string | null;
      /** Actual Reps */
      actual_reps?: number | null;
      /** Actual Work Seconds */
      actual_work_seconds?: number | null;
      /** Body Weight As Of */
      body_weight_as_of?: string | null;
      /** Body Weight Kg */
      body_weight_kg?: number | string | null;
      /**
       * Client Uuid
       * Format: uuid
       */
      client_uuid: string;
      /** Completed At */
      completed_at?: string | null;
      /** Exercise Id */
      exercise_id: number;
      /** Note */
      note?: string | null;
      /** Prescribed Set Id */
      prescribed_set_id?: number | null;
      /** Rpe */
      rpe?: number | null;
      /** Set Index */
      set_index: number;
    };
    /** LoginRequest */
    LoginRequest: {
      /**
       * Email
       * Format: email
       */
      email: string;
      /** Password */
      password: string;
    };
    /** LogoutResponse */
    LogoutResponse: {
      /**
       * Status
       * @default ok
       * @constant
       */
      status: 'ok';
    };
    /** MeResponse */
    MeResponse: {
      /**
       * Scope
       * @enum {string}
       */
      scope: 'user' | 'demo';
      /** User Id */
      user_id: number;
    };
    /**
     * MesocycleOut
     * @description One phase block, `start_week`..`end_week` inclusive and 1-based.
     *
     *     Flattening the tree here would drop the phase spans the `/plan` timeline draws.
     */
    MesocycleOut: {
      /** End Week */
      end_week: number;
      /** Id */
      id?: number | null;
      /** Microcycles */
      microcycles: components['schemas']['MicrocycleOut'][];
      phase: components['schemas']['Phase'];
      /** Start Week */
      start_week: number;
    };
    /**
     * MicrocycleOut
     * @description One week. `is_deload` is exactly `phase is Phase.DELOAD`; a taper is known by `phase`.
     *
     *     `phase` is carried even though `microcycle` has no phase column: it is read off the
     *     parent mesocycle, which the serialiser is walking anyway.
     */
    MicrocycleOut: {
      /** Id */
      id?: number | null;
      /** Is Deload */
      is_deload: boolean;
      phase: components['schemas']['Phase'];
      /** Sessions */
      sessions: components['schemas']['SessionOut'][];
      /**
       * Start Date
       * Format: date
       */
      start_date: string;
      /** Week No */
      week_no: number;
    };
    /**
     * NoteKind
     * @description Why a plan carries a note. Closed, so the client can style or order them.
     *
     *     A note is **never a gate**: the plan is complete and nothing is disabled. It exists so
     *     that a plan which is not quite what was asked for says so, in the plan, instead of
     *     leaving the user to notice.
     * @enum {string}
     */
    NoteKind: 'fewer_sessions_than_requested' | 'target_beyond_one_plan';
    /**
     * NoteOut
     * @description One honest caveat about the plan as a whole. `kind` is the contract, `message` is copy.
     */
    NoteOut: {
      kind: components['schemas']['NoteKind'];
      /** Message */
      message: string;
    };
    /**
     * Phase
     * @description A mesocycle's training emphasis.
     *
     *     `DELOAD` and `TAPER` are phases rather than flags on a week: a deload is a block
     *     with its own prescriptions (lower volume, same intensity), not a week where the
     *     normal block is scaled by a multiplier, and treating it as a flag is how deload
     *     weeks end up accidentally as hard as the weeks around them.
     * @enum {string}
     */
    Phase: 'base' | 'strength' | 'power' | 'power_endurance' | 'performance' | 'deload' | 'taper';
    /**
     * PhaseGuideOut
     * @description What this phase IS and how it is trained — universal, identical for every climber.
     *
     *     Authored copy from `server/domain/vocabulary.py`, not a database row: a phase is a
     *     native enum on `mesocycle`, so there is nothing to seed and nothing to migrate.
     *
     *     Sent **once per response, keyed by `phase`** rather than on the plan payload, which
     *     repeats a mesocycle up to sixteen times and is already 583 KiB at its worst. The plan
     *     screen already reads this endpoint, so the copy costs no extra request.
     *
     *     ⚠️ **The per-plan half is NOT here.** How this phase applies to one climber's plan is
     *     derived on `PlanOut.climbing_band` plus the plan's own weeks; this endpoint is cached
     *     for an hour and shared by every user, so nothing here may describe the reader.
     */
    PhaseGuideOut: {
      /** How To Train */
      how_to_train: string;
      /** Label */
      label: string;
      /** Links */
      links: components['schemas']['GuideLinkOut'][];
      phase: components['schemas']['Phase'];
      /** Summary */
      summary: string;
    };
    /**
     * PlanOut
     * @description A whole plan — previewed or persisted — plus what would be needed to reproduce it.
     *
     *     `generator_input` is the canonical JSON of the `PlannerInput` actually used, plus
     *     `generator_version` and `library_digest`. That digest is load-bearing:
     *     `server/models.py::Plan` promises that re-running a version on the same input reproduces the
     *     tree, and **the library is a third input** — without it the promise is silently false the
     *     first time content is edited.
     *
     *     ⚠️ `target_grade_id` and `current_grade_id` are set by this MODULE and are always `None` on
     *     the blueprint, because `PlannerInput` carries ordinals and the domain never sees a `grade.id`.
     *     Both are real `plan` columns (`0008`), so both survive a reload — the profile's current grade
     *     drifts as the climber improves and nothing else recovers what the plan was built from.
     *
     *     `grade_gap` is derived on the persisted path rather than stored; see `_grade_gap`.
     *
     *     ⚠️ **Size against the PERSISTED response, not the preview** (figures in PR #11b): the raw
     *     bytes are identical for the same tree, but gzipped the persisted body is ~1.9x, because
     *     thousands of repeated `null` ids compress away and distinct integers do not. If it ever bites,
     *     the lever is trimming sets beyond the first N weeks, not splitting the endpoint.
     */
    PlanOut: {
      /** Activated At */
      activated_at?: string | null;
      /**
       * @description Computed on serialisation, on both paths, from fields already on this model —
       *     which is why a persisted plan and a preview cannot disagree about it.
       */
      readonly climbing_band: components['schemas']['ClimbingBandOut'] | null;
      /** Current Grade Id */
      current_grade_id: number | null;
      discipline: components['schemas']['Discipline'];
      /** Generator Input */
      generator_input: {
        [key: string]: unknown;
      };
      /** Generator Version */
      generator_version: string;
      /** Grade Gap */
      grade_gap: number;
      /** Id */
      id?: number | null;
      /** Mesocycles */
      mesocycles: components['schemas']['MesocycleOut'][];
      /** Name */
      name: string;
      /** Notes */
      notes: components['schemas']['NoteOut'][];
      /** Shortfalls */
      shortfalls: components['schemas']['ShortfallOut'][];
      /**
       * Start Date
       * Format: date
       */
      start_date: string;
      /** Target Grade Id */
      target_grade_id: number | null;
      /** Week Count */
      week_count: number;
    };
    /**
     * PlanPreviewRequest
     * @description One field, and `extra="forbid"` so a probing or typo'd field is a 422, never silence.
     *
     *     `start_date` is optional: omitted means "the Monday on or after today, UTC". The server
     *     normalises whatever it is given the same way, so the two paths cannot disagree — which
     *     also means a Monday is returned unchanged and today counts as "on or after today".
     */
    PlanPreviewRequest: {
      /** Start Date */
      start_date?: string | null;
    };
    /**
     * PrescriptionOut
     * @description The default prescription for one exercise in one phase.
     *
     *     `reps` and `work_seconds` are independent and both nullable — a repeater has seconds
     *     and no reps, a pull-up set has reps and no seconds, and a circuit legitimately has
     *     neither. `intensity_pct` has no anchor field: what the percentage is *of* follows from
     *     the exercise's `protocol_kind` (see `PrescriptionTemplate` in `server/models.py`).
     */
    PrescriptionOut: {
      /** Intensity Pct */
      intensity_pct: number | null;
      phase: components['schemas']['Phase'];
      /** Reps */
      reps: number | null;
      /** Rest Between Sets Seconds */
      rest_between_sets_seconds: number | null;
      /** Rest Seconds */
      rest_seconds: number | null;
      /** Sets */
      sets: number;
      /** Target Rpe */
      target_rpe: number | null;
      /** Work Seconds */
      work_seconds: number | null;
    };
    /**
     * ProfilePatchRequest
     * @description Any subset of the profile. Everything omitted is left as it is.
     *
     *     `extra="forbid"`, so a camelCase key or a typo is a 422 rather than a silently
     *     ignored field — and `primary_discipline` is **not** accepted at all: it is derived
     *     from `target_grade_id`.
     *
     *     ⚠️ **`null` means "no change", for every field, and that contract is deliberate.**
     *     Issue #54 wanted a way to un-answer the four steps; making `null` mean "clear" here was
     *     considered and rejected, because it would turn every "I am not touching this" into a
     *     destructive spelling one typo away. `POST /api/profile/reset` does that job instead,
     *     explicitly and in one transaction.
     *
     *     ⚠️ **`equipment_ids` is gone from this model** (issue #54). The equipment step is no
     *     longer part of onboarding, and the owned-vs-lacked question the issue raises is
     *     deliberately deferred to PR #10, where the exercise library's alternatives lookup is what
     *     gives a "I do not have this" flag its meaning. `user_equipment` and every
     *     `exercise_equipment` row are untouched; what is gone is a write path whose semantics are
     *     undecided. Re-adding it is PR #10's job, with the decision attached.
     */
    ProfilePatchRequest: {
      /** Aspect Ratings */
      aspect_ratings?: components['schemas']['AspectRatingIn'][] | null;
      /** Available Weekdays */
      available_weekdays?: number | null;
      /** Current Grade Id */
      current_grade_id?: number | null;
      /** Display Name */
      display_name?: string | null;
      /** Injuries */
      injuries?: components['schemas']['InjuryIn'][] | null;
      /** Sessions Per Week */
      sessions_per_week?: number | null;
      /** Show Body Metrics */
      show_body_metrics?: boolean | null;
      /** Strength Aspect Id */
      strength_aspect_id?: number | null;
      /** Target Grade Id */
      target_grade_id?: number | null;
      /** Weakness Aspect Id */
      weakness_aspect_id?: number | null;
    };
    /**
     * ProfileResponse
     * @description The whole profile, and everything the client needs to compute completion.
     *
     *     ⚠️ **Every null here means "not answered yet", never "zero" or "none"** (revision `0005`).
     *     Anything reading this must refuse to act rather than substitute a default for a question the
     *     user has not been asked. `injuries_reviewed_at` is how its step reports itself finished: an
     *     empty `injuries` list means "nothing to record" or "never asked" depending only on it.
     *
     *     ⚠️ **`email` is the ONE null that does not mean "not answered yet".** It is read from
     *     `app_user`, where it is `NOT NULL`, so a null can only mean the row behind an authenticated
     *     principal has gone. It is read-only — the client displays it and has no way to change it,
     *     which is why it is absent from `ProfilePatchRequest`.
     *
     *     `equipment_ids` and `equipment_reviewed_at` are gone (issue #54): the step left onboarding,
     *     and dropping them also drops a `SELECT` from every profile read. The table is untouched.
     */
    ProfileResponse: {
      /** Aspect Ratings */
      aspect_ratings: components['schemas']['AspectRatingOut'][];
      /** Available Weekdays */
      available_weekdays: number | null;
      /** Current Grade Id */
      current_grade_id: number | null;
      /** Display Name */
      display_name: string | null;
      /** Email */
      email: string | null;
      /** Injuries */
      injuries: components['schemas']['InjuryOut'][];
      /** Injuries Reviewed At */
      injuries_reviewed_at: string | null;
      primary_discipline: components['schemas']['Discipline'] | null;
      /** Sessions Per Week */
      sessions_per_week: number | null;
      /** Show Body Metrics */
      show_body_metrics: boolean;
      /** Strength Aspect Id */
      strength_aspect_id: number | null;
      /** Target Grade Id */
      target_grade_id: number | null;
      /** Weakness Aspect Id */
      weakness_aspect_id: number | null;
    };
    /**
     * ProtocolKind
     * @description How an exercise is executed in time — the shape the session player has to drive.
     *
     *     This is what the protocol compiler (PR #15) turns into a phase timeline, so the
     *     distinctions here are *timing* distinctions, not muscle-group ones: what the aspect
     *     trained is lives in `climbing_aspect`, and what it is done on lives in `equipment`.
     *
     *     `other` for the same reason `ActivityKind.OTHER` exists.
     * @enum {string}
     */
    ProtocolKind:
      | 'max_hang'
      | 'repeaters'
      | 'intervals'
      | 'circuit'
      | 'limit_boulder'
      | 'straight_sets'
      | 'laps'
      | 'hold'
      | 'other';
    /**
     * ReferenceRowOut
     * @description A seeded lookup row: the stable `key` plus the display text.
     *
     *     `key` is the data contract and `name`/`description` are display only — the same
     *     split as `server.domain.vocabulary.ReferenceSpec`. `sort_order` is not sent: the
     *     arrays below are already returned in it.
     */
    ReferenceRowOut: {
      /** Description */
      description: string;
      /** Id */
      id: number;
      /** Key */
      key: string;
      /** Name */
      name: string;
    };
    /** RegisterRequest */
    RegisterRequest: {
      /**
       * Email
       * Format: email
       */
      email: string;
      /** Invite Code */
      invite_code: string;
      /** Password */
      password: string;
    };
    /**
     * SessionCompletionOut
     * @description How much of ONE planned session got done — **derived**, never a stored column.
     *
     *     `done_block_ids` says WHICH blocks got done, over the join
     *     `logged_set.prescribed_set_id → session_block`: every block with at least one logged set,
     *     keyed on `session_block.id`, the id `plans.BlockOut` carries for a persisted plan.
     *     `blocks_done` is its length. A set with null `actual_*` values is a **real** completion —
     *     the "I did this myself" affordance mints exactly those — so nothing here filters them out.
     *
     *     `status` is what the write path stored: `completed` means "pressed Finish", never "did it
     *     all". `state` is derived from it and from `as_of`: `completed`, `pending` for a session still
     *     to come, `skipped` for one whose day has passed unfinished.
     *
     *     ⚠️ **`skipped` names the OUTCOME, not the cause: "past and not finished, whatever the
     *     reason".** A past `in_progress` session reads `skipped` and that is CORRECT — unfinished and
     *     skipped are the same result in real life (Kilian, 2026-08-30), which is why the UI shows only
     *     the percentage. Never render it as "the climber chose to skip this".
     *
     *     `percent` is `null` for a session with no blocks at all: there is nothing to have done, and
     *     reporting 0% for that would read as a failure nobody had.
     */
    SessionCompletionOut: {
      /** Block Count */
      block_count: number;
      /** Blocks Done */
      blocks_done: number;
      /** Done Block Ids */
      done_block_ids: number[];
      /** Percent */
      percent: number | null;
      /** Planned Session Id */
      planned_session_id: number;
      /**
       * Scheduled On
       * Format: date
       */
      scheduled_on: string;
      /**
       * State
       * @enum {string}
       */
      state: 'completed' | 'skipped' | 'pending';
      status: components['schemas']['SessionStatus'];
    };
    /**
     * SessionCompletionResponse
     * @description Completion for every planned session of this climber's inside the window.
     *
     *     `as_of` is the server's own date, i.e. the boundary `state` was decided against, so the
     *     client never re-derives "past" from a clock of its own.
     *
     *     Sessions from a stood-down plan are included when their date falls in the window — the
     *     response is keyed by `planned_session_id`, so a caller reads the ones it asked about.
     */
    SessionCompletionResponse: {
      /**
       * As Of
       * Format: date
       */
      as_of: string;
      /** Sessions */
      sessions: components['schemas']['SessionCompletionOut'][];
    };
    /**
     * SessionLogRequest
     * @description The activity/logged_session envelope plus the delta of sets. `extra="forbid"`.
     *
     *     An **omitted** envelope field means "no change"; an explicit **`null`** means "clear", read
     *     through `model_fields_set` — the idiom at `server/profile/routes.py::InjuryIn`.
     *
     *     `finished` is a request field and **not a column**: the only server behaviour that depends
     *     on finish-ness is the `planned_session.status` transition, which is why this endpoint needed
     *     no Alembic revision. `duration_minutes` must be **elapsed minutes so far**, floored at 1,
     *     never the plan's `estimated_minutes` — see the handler's `GREATEST` rule.
     */
    SessionLogRequest: {
      discipline: components['schemas']['Discipline'];
      /** Duration Minutes */
      duration_minutes: number;
      /**
       * Finished
       * @default false
       */
      finished: boolean;
      /** Location */
      location?: string | null;
      /** Notes */
      notes?: string | null;
      /**
       * Occurred On
       * Format: date
       */
      occurred_on: string;
      /** Planned Session Id */
      planned_session_id?: number | null;
      /** Rpe */
      rpe?: number | null;
      /**
       * Sets
       * @default []
       */
      sets: components['schemas']['LoggedSetIn'][];
      /** Started At */
      started_at?: string | null;
    };
    /**
     * SessionLogResponse
     * @description What the server now holds for this session. **Always 200**, never a conditional 201.
     *
     *     A replayed PUT must not change the status code, because the outbox does not branch on it.
     *     `duration_minutes` is the post-`GREATEST` value, so a client can see that a stale retry did
     *     not shorten the session.
     *
     *     **No user free text is echoed** — `notes`, `location` and each set's `note` are all absent.
     *     So nothing in this body needs escaping downstream, and a mid-run piggyback response stays
     *     small even when it acknowledges a hundred sets.
     */
    SessionLogResponse: {
      /**
       * Client Uuid
       * Format: uuid
       */
      client_uuid: string;
      /** Duration Minutes */
      duration_minutes: number;
      /** Id */
      id: number;
      /**
       * Occurred On
       * Format: date
       */
      occurred_on: string;
      /** Planned Session Id */
      planned_session_id: number | null;
      planned_session_status: components['schemas']['SessionStatus'] | null;
      /** Rpe */
      rpe: number | null;
      /** Sets */
      sets: components['schemas']['LoggedSetAck'][];
    };
    /**
     * SessionOut
     * @description One planned session. `estimated_minutes` is `null` for a session with no blocks.
     *
     *     `status` is `null` on a preview: a preview has no lifecycle, and inventing `planned` would
     *     make "not a row yet" and "a row nobody has started" the same answer.
     *
     *     `shortfalls` here are the slots that produced **no block at all**. Stored, not derived —
     *     nothing in the tree records a slot that was never filled.
     */
    SessionOut: {
      activity_kind: components['schemas']['ActivityKind'];
      /** Blocks */
      blocks: components['schemas']['BlockOut'][];
      /** Estimated Minutes */
      estimated_minutes: number | null;
      /** Id */
      id?: number | null;
      /**
       * Scheduled On
       * Format: date
       */
      scheduled_on: string;
      /** Shortfalls */
      shortfalls: components['schemas']['ShortfallOut'][];
      status?: components['schemas']['SessionStatus'] | null;
      /** Title */
      title: string;
      /** Weekday */
      weekday: number;
    };
    /**
     * SessionStatus
     * @description Where a *planned* session got to. Never used on a logged one.
     *
     *     `SKIPPED` and `RESCHEDULED` are distinct on purpose — adherence should not punish
     *     someone who moved Tuesday to Wednesday the same way it treats a session that never
     *     happened.
     * @enum {string}
     */
    SessionStatus: 'planned' | 'in_progress' | 'completed' | 'skipped' | 'rescheduled';
    /**
     * SetOut
     * @description One prescribed set, straight off the `(exercise, phase)` prescription template.
     *
     *     `target_load_kg` and `target_grade_id` are present and always `null` in v1.0.0, so the wire
     *     shape is stable when they are filled. Deriving a load is the one place a bodyweight figure
     *     could creep into a plan, which CLAUDE.md's weight rule forbids outright.
     *
     *     The id is the point of the persisted response: the session player logs a `logged_set` against
     *     `prescribed_set.id`, so re-fetching to learn it would cost a round trip before the user could
     *     start.
     */
    SetOut: {
      /** Id */
      id?: number | null;
      /** Set Index */
      set_index: number;
      /** Target Grade Id */
      target_grade_id: number | null;
      /** Target Intensity Pct */
      target_intensity_pct: number | null;
      /** Target Load Kg */
      target_load_kg: string | null;
      /** Target Reps */
      target_reps: number | null;
      /** Target Rest Seconds */
      target_rest_seconds: number | null;
      /** Target Rpe */
      target_rpe: number | null;
      /** Target Work Seconds */
      target_work_seconds: number | null;
    };
    /**
     * ShortfallOut
     * @description An aspect this phase cannot train with the gear assumed, and what would unlock it.
     *
     *     `options` is an OR of AND sets: each inner list is a combination that would fill the
     *     cell. Never a gate — the plan is complete and nothing is disabled.
     */
    ShortfallOut: {
      /** Aspect Key */
      aspect_key: string;
      /** Message */
      message: string;
      /** Options */
      options: string[][];
      phase: components['schemas']['Phase'];
    };
    /**
     * TokenResponse
     * @description The access token, for the client to hold **in memory only**.
     *
     *     Never `localStorage`: in the federated mount that storage belongs to kilianmc.com and
     *     is shared with the whole portfolio (CLAUDE.md). The refresh token is not in this body
     *     at all — it is the httpOnly cookie.
     */
    TokenResponse: {
      /** Access Token */
      access_token: string;
      /** Expires In */
      expires_in: number;
      /**
       * Scope
       * @enum {string}
       */
      scope: 'user' | 'demo';
      /**
       * Token Type
       * @default bearer
       * @constant
       */
      token_type: 'bearer';
    };
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, never>;
      /** Input */
      input?: unknown;
      /** Location */
      loc: (string | number)[];
      /** Message */
      msg: string;
      /** Error Type */
      type: string;
    };
    /** VocabularyResponse */
    VocabularyResponse: {
      /** Climbing Aspects */
      climbing_aspects: components['schemas']['ReferenceRowOut'][];
      enums: components['schemas']['ClosedVocabulariesOut'];
      /** Equipment */
      equipment: components['schemas']['ReferenceRowOut'][];
      /** Grade Systems */
      grade_systems: components['schemas']['GradeSystemOut'][];
      /** Grades */
      grades: components['schemas']['GradeOut'][];
      /** Injury Areas */
      injury_areas: components['schemas']['ReferenceRowOut'][];
      /** Phase Guide */
      phase_guide: components['schemas']['PhaseGuideOut'][];
      /** Plan Goal */
      plan_goal: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  demo_api_auth_demo_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['TokenResponse'];
        };
      };
    };
  };
  login_api_auth_login_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['LoginRequest'];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['TokenResponse'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  logout_api_auth_logout_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['LogoutResponse'];
        };
      };
    };
  };
  me_api_auth_me_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['MeResponse'];
        };
      };
    };
  };
  refresh_tokens_api_auth_refresh_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['TokenResponse'];
        };
      };
    };
  };
  register_api_auth_register_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['RegisterRequest'];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['TokenResponse'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  health_api_health_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': {
            [key: string]: string;
          };
        };
      };
    };
  };
  read_library_api_library_get: {
    parameters: {
      query?: {
        v?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ExerciseLibraryResponse'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  create_plan_api_plans_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['PlanPreviewRequest'];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['PlanOut'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  active_plan_api_plans_active_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ActivePlanResponse'];
        };
      };
    };
  };
  preview_plan_api_plans_preview_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['PlanPreviewRequest'];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['PlanOut'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  read_profile_api_profile_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProfileResponse'];
        };
      };
    };
  };
  patch_profile_api_profile_patch: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['ProfilePatchRequest'];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProfileResponse'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  reset_profile_api_profile_reset_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProfileResponse'];
        };
      };
    };
  };
  session_completion_api_sessions_completion_get: {
    parameters: {
      query: {
        from: string;
        to: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['SessionCompletionResponse'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  log_session_api_sessions__client_uuid__put: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        client_uuid: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['SessionLogRequest'];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['SessionLogResponse'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  read_vocabulary_api_vocabulary_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['VocabularyResponse'];
        };
      };
    };
  };
}
