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
 * openapi-sha256: e58a5e17eee54e12fb58cf2ce94a99bd8c5249ff29b045ce0c800e5edbd0380e
 * types-sha256: 2b903d5a68379c5e373c2c33cceb4436e3add67b9f3bb59547a6836b2ac95e56
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
     * ProfilePatchRequest
     * @description Any subset of the profile. Everything omitted is left as it is.
     *
     *     `extra="forbid"`, so a camelCase key or a typo is a 422 rather than a silently
     *     ignored field — and `primary_discipline` is **not** accepted at all: it is derived
     *     from `target_grade_id`.
     */
    ProfilePatchRequest: {
      /** Aspect Ratings */
      aspect_ratings?: components['schemas']['AspectRatingIn'][] | null;
      /** Available Weekdays */
      available_weekdays?: number | null;
      /** Equipment Ids */
      equipment_ids?: number[] | null;
      /** Injuries */
      injuries?: components['schemas']['InjuryIn'][] | null;
      /** Sessions Per Week */
      sessions_per_week?: number | null;
      /** Show Body Metrics */
      show_body_metrics?: boolean | null;
      /** Target Grade Id */
      target_grade_id?: number | null;
    };
    /**
     * ProfileResponse
     * @description The whole profile, and everything the client needs to compute completion.
     *
     *     ⚠️ **Every null here means "not answered yet", never "zero" or "none".** That is the
     *     whole point of revision `0005`, and it binds anything that reads this — the completion
     *     bar, and the plan generator in PR #11, which must refuse to generate rather than
     *     substitute a default for a question the user has not been asked.
     *
     *     The two `*_reviewed_at` fields are how their steps report themselves finished: an empty
     *     `equipment_ids` or `injuries` list means "nothing to record" or "never asked" depending
     *     only on them. Every completion test the client makes reads one of these or a scalar,
     *     which is what keeps the progress bar server truth.
     */
    ProfileResponse: {
      /** Aspect Ratings */
      aspect_ratings: components['schemas']['AspectRatingOut'][];
      /** Available Weekdays */
      available_weekdays: number | null;
      /** Equipment Ids */
      equipment_ids: number[];
      /** Equipment Reviewed At */
      equipment_reviewed_at: string | null;
      /** Injuries */
      injuries: components['schemas']['InjuryOut'][];
      /** Injuries Reviewed At */
      injuries_reviewed_at: string | null;
      primary_discipline: components['schemas']['Discipline'] | null;
      /** Sessions Per Week */
      sessions_per_week: number | null;
      /** Show Body Metrics */
      show_body_metrics: boolean;
      /** Target Grade Id */
      target_grade_id: number | null;
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
