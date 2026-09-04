# CLAUDE.md — climb-trainer

The code, its tests and its module docstrings are the source of truth for *how* anything works.
This file holds only what working code cannot tell you: prohibitions, traps, and decisions already
reversed once. The reasoning, the measurements and the history are frozen verbatim at
`../.archive/climb-trainer-CLAUDE-2026-09-03.md` (one level above the repo root).
**Grep the archive by the heading named on the tripwire line; never `Read` it whole.** Guard
docstrings elsewhere in this repo cite section headings that now live only in that archive.
**To add a line here, archive one.**

## Tripwires

One line each; `→` names the archive heading that holds the reasoning.

### Deployment and `vercel.json`

- `framework` must be `null` in `vercel.json` **and** cleared on the Vercel project itself — a `vercel link` re-detects FastAPI and routes 100% of traffic to the function; the symptom is `/` returning JSON `{"detail":"Not Found"}` → *1. The `framework: "fastapi"` trap*
- An unmatched `/api/*` path must return FastAPI's own JSON 404, never the SPA shell; the negative lookahead in the second rewrite is what keeps the two rules apart → *2. `/api/*` must always be FastAPI JSON, never the SPA shell*
- `Access-Control-Allow-Origin: *` belongs on `/remoteEntry.js` and `/assets/*` only, never on `/api/*`; do not copy another repo's `vercel.json` wholesale → *2. `/api/*` must always be FastAPI JSON*
- Never add a `requirements.txt`: `pyproject.toml` wins and the requirements file is silently ignored → *3. Never add a `requirements.txt`*
- Never give a secret a `VITE_*` prefix — the repo is public and the bundle is plain text; the one injected build-time value, `__BUILD_ID__`, is deliberately NOT a `VITE_*` var and must not become configurable → *4. `VITE_*` is PUBLIC, by definition*
- The function region must match Neon's, which is fixed at project creation → *5. Function region and Neon region must match*
- Never reflect raw request headers; diagnostics use an allowlist of names, because Vercel injects a live `x-vercel-oidc-token` on every request → *6. Never reflect raw request headers*
- Never delete or raise `maxDuration` on `api/index.py` — it is a correctness setting, the thing that makes the client's auth abort an *outer* bound → *7. `maxDuration` is pinned*
- Do not move the app into `api/`, do not delete the `sys.path` line in `api/index.py`, and add any new `server/` subpackage to `[tool.setuptools] packages` in the same commit — there is no autodiscovery → *Repo layout — do not rearrange it*

### Frontend, router, MF, PWA

- The API base resolves from `import.meta.url` and guards the content-type; never "simplify" it to a bare relative `fetch('/api/…')` → *API base: resolve from `import.meta.url`*
- Never register a service worker from `web/src/remote.tsx` → *Never register a service worker from `remote.tsx`*
- Never hand-edit `web/src/routeTree.gen.ts`, never *spread* a history object, and name every lazy leaf `<route>.lazy.tsx` — the two route factories must not be mixed → *Routing: one tree, two histories*
- In the federated mount `localStorage` is the SHELL's storage, so namespace every key → *In the federated mount, `localStorage` is the SHELL's storage*
- Grep for the shared-singleton string; never assert a React-instance count, which is vacuous. `VITE_CLIMB_REMOTE_URL` is the SHELL's variable and must be a branch alias or custom domain, never a deployment-specific URL → *Module Federation shared singletons — the silent one*
- Tokens live on `.ct-app`, never `:root`, and container queries replace media queries; both are structural, not stylistic → *Container queries, not media queries*
- No `position: fixed` and no viewport units anywhere the route tree can reach — an inline style never becomes CSS, so there is no backstop → *Accessibility is part of the design*
- Full height is an in-flow `100%` chain over flexed `body` and `#root`, not `fixed` and not `100dvh`; a plain `min-block-size: 100%` collapses to zero → *The full-height chain*
- Do not use `backdrop-filter` and do not reintroduce translucent "glass" surfaces → *Glassmorphism: considered and REJECTED*
- No text over a photograph on the landing page, and the scrim that made it possible is deleted — do not reintroduce it → *Landing imagery*
- `web/scripts/gen-landing-images.mjs` is an authoring tool and must never enter `build` → *Landing imagery*
- Icons are SVG components, never `<img src="…svg">`, and an icon-only control owes its own `aria-label` → *Landing imagery* · *The nav's thresholds are MEASUREMENTS*
- Generated API types are COMMITTED: regenerate with `npm run codegen:api`, never loosen the `openapi-sha256` digest header, and never recreate `web/src/api/vocabularies.ts`; a FastAPI or Pydantic bump fails that test and Dependabot cannot fix it → *OpenAPI codegen*
- PWA: `registerType: 'autoUpdate'` with `injectRegister: null`; the asset generator is deliberately not a devDependency and its config stays plain JS → *PWA — only the decisions a reader would otherwise reverse*
- `&__prose` is `56ch` and the number is MEASURED — do not "fix" it up to the usual `65ch` → *The reading measure is a GRID COLUMN*
- The four screen sizes are NAMED container sizes and some widths are deliberately not on the scale; read them out of `web/src/styles/_tokens.scss` rather than inventing one → *The four screen sizes are NAMED*
- The phase week table never transposes, its short codes are applied by CLIPPING rather than `display: none`, and its sizing custom properties are component-scoped and must not move into the token file → *The phase week table*
- Expand-all and collapse-all are ICON-ONLY at every width, and clicking a phase expands before it scrolls, then moves focus (Kilian) → *The plan timeline is measured in DAYS*
- Light and dark have two known gaps that are documented rather than fixed (Kilian's call); do not "fix" either without asking → *Light and dark: the `data-theme` override*
- TypeScript stays on 6.x — `typescript-eslint` peers `<6.1.0`, and the TS6-for-lint / TS7-for-`tsc` side-by-side alias is rejected → *TypeScript stays on 6.x*
- The forced `eslint-plugin-jsx-a11y` peer override in `web/package.json` is load-bearing; delete it only when the plugin ships an `^10` peer, and re-prove the rules still fire → *ESLint 10 rests on a forced jsx-a11y peer*

### Database and compute

- Neon bills AWAKE TIME, not writes: how spread out the queries are is the entire cost model → *Neon bills AWAKE TIME, not writes*
- The UI never waits on the database, and the outbox has explicitly NO debounce timer and NO item-count trigger — `Finish`, `tab-hidden` and `online` only → *Two write tiers*
- Never write `last_used_at` / `last_seen` on read, and never cron-ping Neon to defeat autosuspend → *The other compute rules*
- `GET /api/library` is USER-INDEPENDENT, permanently; per-user state about exercises goes on a separate endpoint that is never CDN-cached → *`/api/library` is USER-INDEPENDENT, permanently*
- Sync SQLAlchemy 2 with `def` endpoints, psycopg3 never asyncpg, `TIMESTAMPTZ` never naive — the engine's omissions are deliberate and must not be "completed" → *Engine config — the omissions are the point*
- `DATABASE_URL` is pooled and `DATABASE_URL_UNPOOLED` is direct; they are different hosts and one cannot stand for the other → *Database and compute budget*
- Never store a grade as a display string alone, and never accept a free-typed grade or a client-supplied `ordinal` → *Prefer CLOSED inputs over free text*
- Tests run against real Postgres: never substitute SQLite to dodge a skip, and never make the gate *require* a database → *SQLite is disqualified for tests*
- Expand → deploy → contract, always; never migrate at startup, never `alembic downgrade` against production, and a migration touching `app_user` must be ADDITIVE → *Migrations run out-of-band* · *Production data durability — real accounts, no undo*
- Migrate production BEFORE promoting, never after, and read the applied revision back afterwards → *Branch model* · *Three traps, all paid for on the day it first ran*
- `server/seed.py` upserts and never deletes; `server/contentseed.py` is the one seed that may delete `exercise` rows → *Production data durability — real accounts, no undo*
- Do not "complete the set" of indexes, or of `ON DELETE` behaviours, in the domain schema — every remaining foreign key is `NO ACTION`/`RESTRICT` deliberately → *The domain schema*
- `.github/workflows/migrate.yml` never prints a connection string, and nothing on that path logs one; keep it that way → *How to actually run one*
- Minting an invite is a LOCAL command and must never become a workflow → *Minting an invite is a LOCAL command* · *Local accounts, and the two things that are NOT `server/seed.py`*

### Security and auth

- Every query is scoped by `user_id` taken from the token, never from the request → *Security rules*
- CORS is an allowlist, never `"*"`, and `AUTH_SECRET` is read lazily rather than at import time → *Security rules* · *Auth implementation — where each piece lives*
- Bound parameters only: never an f-string, `%`, `.format()`, `+`, or interpolated `text()`. Identifiers cannot be parameterised — use an allowlist → *Bound parameters only — never string-built SQL* · *Identifiers cannot be parameterised*
- A 422 must never echo the request back and FastAPI's default handler does, so do not remove the custom one; never build an ORM object by splatting request data → *Validate at the edge with Pydantic*
- Notes are untrusted on OUTPUT too: build DOM nodes, never assemble an HTML string → *Notes are untrusted on OUTPUT too*
- When you add a free-text column, add its row to the inventory in the SAME PR — that table has been wrong three times and every time the new field did not look like "a note" (`logged_session.location`, `user_injury.note`, `invite.label`, all bound by the output-escaping rule too); the bounds themselves live in `server/fields.py` and are proven by `tests/test_profile_validation.py` → *The free-text inventory — ELEVEN fields, and three of them get forgotten*
- Never set `Cross-Origin-Resource-Policy` or `Cross-Origin-Embedder-Policy`, and we deliberately do not set HSTS → *Security response headers*
- Drop the token before EVERY `POST /api/auth/*`, not just login and register; demo scope re-mints and cannot refresh → *Auth UI — the client half of the contract*
- The client's give-up deadline must stay the OUTER bound and must never clear `inFlight`, and the UI tier deliberately does not release the Web Lock → *Auth UI — the client half of the contract*
- Every route must be in `PUBLIC_ROUTE_IDS` or under `_authed`, and the route guard never reads `window.location` → *Auth UI — the client half of the contract*
- Registration is invite-gated: per-person digests in a table, never a shared env secret, and the rejection messages must never be split → *Registration is invite-gated*
- Do not tick any of the end-to-end security verification off from memory → *TODO — the end-to-end security verification pass*

### Domain and product rules

- The app never recommends losing weight: low strength-to-weight means "get stronger" and never "get lighter", in no copy, tip, badge, chart annotation or generated recommendation → *The app never recommends losing weight*
- Never suggest improvising finger loading → *Onboarding and the profile*
- Unanswered is `NULL` and nothing may substitute a fallback — the generator refuses to generate rather than assume → *Onboarding and the profile*
- There is deliberately no `bodyweight` equipment row, and the generator never refuses for missing equipment: it generates and names the shortfall → *Onboarding and the profile* · *The plan generator*
- A route may only replace itself with an error when there is nothing to show — gate on `data === undefined`, never on `isError` — and a credential change must reset the query cache → *Onboarding and the profile*
- Climbing is allocated first and every week has a floor — a deload's is its own lower `DELOAD_CLIMBING_FLOOR_PCT` and mobility or technique leads it, every other week's is its band's; the band is a target range, not only a floor, over those other weeks; eligibility is `prescribable()` and on-the-wall is a preference, never a filter → *The plan generator*
- The server sends the plan's derived facts and the client never re-implements a training rule → *The plan generator*
- There is no abandon endpoint, and an `IntegrityError` is never re-raised → *Persisting a plan*
- An item is done or not — no skipped state on the server — and completion is the blocks at 100%, never the Finish button → *Logging a session* · *Session player invariants*
- The `sets` array is a DELTA, not a replacement, and `set_index` is the whole session's 1..N ordinal → *The `sets` array is a DELTA, not a replacement*
- `duration_minutes` only ever grows, and a session's status never moves backwards → *`duration_minutes` only ever grows*
- A 4xx on flush is PERMANENT — quarantine it, never retry; 5xx is retryable → *Logging a session*
- Which sets a block owns is `prescribed_set_id` membership, never an ordinal window → *Session player invariants*
- `requestAnimationFrame` drives the clock, never `setInterval` counting, and player state goes on `data-phase` / `data-state`, never an interpolated class name → *Session player invariants*
- Colour is never the only carrier of a session's state → *Logging a session*
- The wake lock reflects REAL state, not intent; release it on finish, abort and unmount, and never let timing depend on it → *Screen Wake Lock*

### Docs, tests and dependencies

- Pin every version to one verified against the registry in the same turn, never one recalled from memory → *Dependency policy*
- `.github/dependabot.yml` and `workflow_dispatch` registration are read from the DEFAULT branch (`main`) only, and alerts are raised there too, so that class of file needs a two-sided `dev` + `main` copy → *`.github/dependabot.yml`* · *Branch model*
- Some pinned action SHAs are immutable releases Dependabot can never bump; check those by hand → *Pinned actions Dependabot can never bump*
- Never hardcode a version literal in Python: the root `package.json` is the sole source of truth, and `web/package.json` and `pyproject.toml` stay at `0.0.0` → *Versioning*
- Never put a database URL in `.env` — the test URL lives in `CT_TEST_DATABASE_URL` and nowhere else, exported from `~/.zshrc`, which a non-interactive shell does not read → *Local Postgres for the test suite*
- An exported variable beats the file, and the Vite dev proxy is NOT Vercel's rewrite → *`.env` is loaded for you — but only outside Vercel*
- The dev database and the test database are the same database, and a local database means LOCAL ACCOUNTS ONLY → *Local Postgres for the test suite* · *Local development*
- A dev server running during the gate can blank every route; the trigger is UNCONFIRMED, so do not substitute a fresh guess for the recorded one → *A dev server and the gate at the same time can blank every route*
- A guard test must be SHOWN to fail before it is trusted: break the thing, capture the red, restore, and put the failure in the PR → *A guard test must be SHOWN to fail*
- A class name in markup with no CSS fails SILENTLY, and interpolated class names are that guard's one blind spot → *A class name in markup with no CSS fails SILENTLY*
- Prose is capped and an executable claim must not be prose: plain comments 2 lines, module docstrings 10, wire-contract docstrings 20; over-cap needs a row in `tests/comment_budget_allowlist.toml` with a real reason, and `BASELINE_RATCHET` may only go down → *Prose is capped, and an executable claim must not be prose*
- Never weaken the generated digest header to satisfy gitleaks, and `useDefault = true` must stay in the gitleaks config or the default ruleset is REPLACED → *Quality gate*

## Quality gate

One command. Batch your edits and run it once at the end, not once per file.

```bash
npm run check          # == check:web && check:server
npm run check:web      # format:check && lint && typecheck && build && test
npm run check:server   # ruff check && ruff format --check && mypy && pytest
```

`build` runs before `test` deliberately (issue #26). CI's three required status checks are `web`,
`server` and `secrets`; add steps to a job freely, but **never rename a job** — the ruleset then
waits forever for a check that will never report.

Working agreement:

- Two long-lived branches: `dev` (integration) and `main` (production). Feature PRs target `dev`;
  `main` takes only promotion PRs, merged by Kilian after he has tested the dev deploy.
- `npm run version:dev` bumps the minor on `dev`; `npm run version:release` bumps the major at a
  promotion.
- Migrations are dispatched out-of-band from Actions, never on push and never from the API
  function. **Ask Kilian first, and say what you are about to apply before you dispatch it.**
- Test critical logic, core user paths and anything that can lose user data; skip static or
  presentational UI, and ask rather than defaulting to writing a test → *Testing policy*.

## Findings inbox — one line each, dated. Emptied at every promotion to main.

New findings land HERE, never as a new `##` section. At each promotion every line goes to
exactly ONE of these, then leaves the inbox:
  1. a GUARD     — the claim is executable, so it becomes a test  (best outcome)
  2. a TRIPWIRE  — a prohibition nobody could infer from working code (one line, stays above)
  3. the ARCHIVE — reasoning, or history
  4. DELETED     — it did not matter after all  (most lines should end here)

- 2026-09-04 — the base on-wall `endurance` pool is now exactly 7 entries and `_wall_picks` indexes it `(spread + depth) % len(pool)` while `_spread`'s stride is `DAYS_PER_WEEK` = 7, so the week term vanishes mod 7 and a given session slot draws the same exercise every week — a pool length equal to the stride collapses the week dimension entirely. Belongs to **issue #117** ("loading weeks 1, 2 and 3 are byte-identical"): this aliasing is a direct cause. Found while re-measuring PR C's library reach.
- 2026-09-04 — §3.4's tier ordering makes `anaerobic_capacity` open **157** of the power-endurance block's sessions against power endurance's **32** (was 96 / 67), because An Cap is more intense than Aero Pow and the source orders on intensity. Doctrinally right, and it HARDENS ruling 16: `PHASE_GUIDE[POWER_ENDURANCE]` may not be upgraded to a lead claim until the weekly frequency ceilings (ruling 9, backlog item 3) land. A line, not a change.
- 2026-09-03 — the `## Quality gate` chain-claim arm in `tests/test_claude_md_claims.py` tests each documented step with `step in script_value`, i.e. substring membership. It therefore catches a RENAMED step but not a REORDERED chain, and a claim of `ruff format` passes against a script running `ruff format --check`. Its own docstring says the documented order is the only place the gate's order exists (issue #26), so the arm does not currently prove that. Found by rewording the `check:server` line to `pyright` during the PR #72-style trim: the rename went red, dropping `--check` stayed green.

## Where things live

- `README.md` — the pitch only: *What it does* and *Stack*. No section may return to it, and no ten-word run of prose may live in both files.
- `../issuesplan.md` — current versions, the applied revision, and every open issue.
- Module docstrings carry the detail: `server/db.py` (engine and session wiring), `server/auth/`
  (one file per auth concern), `server/domain/grades.py` (the ordinal ladder) and
  `web/src/styles/_layout.scss` (the reading measure as a grid column).
- The doc guards: `tests/test_claude_md_claims.py` (every path, script, env var and README
  section this file names still resolves), `tests/test_docs_layout.py` (the pitch stays a pitch),
  `tests/test_comment_budget.py` (the prose caps and the allowlist's staleness arms). This
  section replaces *What lives outside this file — the master map* in the archive.
