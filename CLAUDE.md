# CLAUDE.md — climb-trainer

Guidance for AI agents (and humans) working in this repo. **Read it before opening a
PR, and before touching `vercel.json`, the API client, or anything that writes to the
database.**

Most of what follows is not style preference. Each rule below records a failure that
either already happened (in spike S0, or in the `fund-dashboard` repo) or was measured
as a live risk. The *reason* is given with every rule, because a rule without its
reason gets "simplified" away by the next well-meaning change.

## Overview

**`climb-trainer`** is the third showcase project in the kilianmc.com portfolio, and
the first with a **database and a non-JS backend**. Product shape: log in → pick a
**target grade** → the app generates a plan covering the **aspects of climbing** →
**follow along during the session** with a timer and audio cues, logging as you go →
review it in a **training diary**.

It ships **two mounts from one route tree**:

- **Standalone** — `climb.kilianmc.com`. Browser history, deep links, PWA-installable.
  This is the real product.
- **Federated remote** — MF remote name **`climbTrainer`**, exposed as
  `./App` from `src/remote.tsx`, mounted inside `portfolio-shell`'s `ProjectViewer`
  with `createMemoryHistory` so the remote never fights the host over
  `window.location`.

**The repo is PUBLIC on GitHub.** Every secret lives in Vercel env vars or the GitHub
Actions `production` environment. `gitleaks` runs in CI on full history.

## Stack

- **Frontend** — React 19 · TypeScript 6 (strict) · Vite 8 · SCSS · Vitest + RTL.
- **Backend** — FastAPI on the Vercel Python runtime, Python 3.13, **sync**
  SQLAlchemy 2 + `def` endpoints (anyio threadpool), **psycopg3**, Alembic.
- **DB** — Neon Postgres (free tier, EU region to match the function region).
- **Deploy** — **one** Vercel project serving both the SPA and `/api/*`, so `/api` is
  same-origin for the standalone app. Validated in spike S0.

## Repo layout — do not rearrange it

Spike S0 verified this exact layout end-to-end on a real deployment. It is load-bearing.

```text
package.json          root — the version source of truth
vercel.json           framework:null + buildCommand + outputDirectory + rewrites
pyproject.toml        Python deps (requires-python = ">=3.13"). NO requirements.txt.
uv.lock               committed
.python-version       "3.13"
.nvmrc                24
alembic.ini           Alembic config. NO `sqlalchemy.url` — env.py reads the env.
api/index.py          thin Vercel entrypoint: sys.path.insert + `from server.app import app`
migrations/           Alembic env.py + versions/
server/               the FastAPI application actually lives here
  app.py              the FastAPI app
  settings.py         env config (CORS allowlist, the two DB URLs) + loads `.env` once
  db.py               engine + session wiring. READ ITS DOCSTRING before touching it.
  models.py           SQLAlchemy 2 models, naming convention, TIMESTAMPTZ default
  seed.py             reference-data seed — the same module CI and production use
  domain/             PURE Python: no DB, no clock, no RNG, no I/O
web/                  the Vite SPA, built to web/dist
tests/                pytest (backend). conftest.py skips DB tests without DATABASE_URL.
```

`server/` being importable from `api/index.py` was genuinely uncertain before S0 — it
works because `api/index.py` inserts the deployment root onto `sys.path`. Don't move
the app into `api/`; don't delete that `sys.path` line.

---

## Deployment traps (S0 findings — the expensive ones)

### 1. The `framework: "fastapi"` trap — the single worst failure mode

`vercel link` **auto-detects FastAPI** and writes `framework: "fastapi"` at the
**project level**. That preset routes **100% of traffic to the Python function**: the
SPA becomes unreachable, and even `/api/health` 404s, because the preset hands the
function a path the app doesn't route.

**`vercel.json` alone does NOT fix this.** The project-level setting wins. Both are
required:

1. `"framework": null` in `vercel.json`, **and**
2. clear it on the project itself:
   `PATCH /v9/projects/<name>?teamId=…` with body `{"framework": null}`.

**Symptom to recognise instantly: `/` returns `{"detail":"Not Found"}` as JSON.**
If you ever see that, this is what happened — don't go debugging the rewrites.

Re-check this after any `vercel link`, project re-creation, or git-connection repair,
because auto-detection can silently set it again.

### 2. `/api/*` must always be FastAPI JSON, never the SPA shell

```jsonc
"rewrites": [
  { "source": "/api/(.*)", "destination": "/api/index" },
  { "source": "/((?!api/).*)", "destination": "/index.html" }
]
```

Two properties this depends on, both confirmed in S0:

- **The rewrite preserves the ORIGINAL path.** The function sees `/api/nope`, not
  `/api/index`, so FastAPI routes on the real URL. The whole `/api/*` design depended
  on this and it was not obvious.
- **An unmatched `/api/*` path must return FastAPI's own JSON 404**, not the SPA
  fallback. If the SPA rewrite ever swallows `/api/*`, the client gets
  `200 text/html`: `res.ok` is **true** and `res.json()` throws somewhere unrelated —
  the worst possible failure to debug from the browser.

`tests/test_routing.py` guards this. Do not weaken those assertions. The negative
lookahead in the second rewrite is what keeps the two rules from overlapping — if you
edit either `source`, re-verify `/api/nope` on a real deploy, not just in tests.

Also: do **not** copy `ai-portfolio-project1/vercel.json` wholesale. It puts
`Access-Control-Allow-Origin: *` on everything. The wildcard belongs on
`/remoteEntry.js` and `/assets/*` **only** — never on `/api/*`, where it would let any
site read authenticated responses.

### 3. Never add a `requirements.txt`

If both `requirements.txt` and `pyproject.toml` exist, **`pyproject.toml` wins and the
requirements file is silently ignored** — you get a deployment that installs the wrong
set of packages with no error. Dependencies go in `pyproject.toml`; the committed
`uv.lock` pins them. CI runs `uv sync --frozen`, so the lock can never drift unnoticed.

### 4. `VITE_*` is PUBLIC, by definition

Anything named `VITE_*` is **inlined into the client bundle at build time**. It ships
to every visitor as plain text in a JS file. **Never give a secret that prefix**, and
remember this repo is public on GitHub, so there is no second line of defence. Server
secrets are read in `server/settings.py` from unprefixed env vars.

### 5. Function region and Neon region must match

S0's function ran in `iad1` (US East) while serving Barcelona. **Neon's region is
fixed at project creation** — pick the EU region and pin the function region to match.

### 6. Never reflect raw request headers

Vercel injects `x-vercel-oidc-token` on **every** request. It is a real, short-lived
credential. Any diagnostic endpoint must use an **allowlist** of header names. S0 hit
this while dumping `x-vercel-*` for debugging.

---

## Frontend rules

### API base: resolve from `import.meta.url` + guard the content-type

See `web/src/api/client.ts`. A **relative `/api/...` from the federated remote hits
the SHELL's SPA rewrite** (the code is running on kilianmc.com, not
climb.kilianmc.com) and gets back `200 text/html`. `res.ok` is true, and `res.json()`
throws far away from the cause. **This already bit the fund dashboard once** —
`ai-portfolio-project1/src/services/navService.js` exists for precisely this reason.

So `apiFetch` does two things and both must stay:

1. resolves `API_BASE` from `import.meta.url`, i.e. the origin this *chunk* was served
   from — which is the API origin in both mounts;
2. **throws `NotJsonError` when the content-type isn't JSON**, instead of trusting
   `res.ok`. Even same-origin, a misconfigured rewrite can return the SPA shell with a
   200.

Never replace this with a bare relative `fetch('/api/…')`, and never "simplify away"
the content-type check.

### Routing: one tree, two histories (PR #4)

`src/router.tsx` builds the router from a passed-in history and is the only place router
or Query defaults live. `main.tsx` gives it `createBrowserHistory`, `remote.tsx`
`createMemoryHistory`. The history is the *only* difference between the mounts.

- **`src/routeTree.gen.ts` is COMMITTED, and must stay committed.** `web/vitest.config.ts`
  **replaces** `web/vite.config.ts` rather than merging it, so the router plugin never
  runs under Vitest and cannot regenerate the tree. Verified by deleting it and watching
  `vitest` fail with no regeneration. It is excluded from ESLint (`ignores`) and Prettier
  (`.prettierignore`) — it ships without semicolons, so `format:check` fails on it
  otherwise. Never hand-edit it.
- **⚠️ A lazy leaf must be named `<route>.lazy.tsx`.** `createLazyFileRoute` inside a
  plain `plan.tsx` **still builds, emits no warning, and is bundled EAGERLY** — verified
  2026-08-14: no separate chunk appears. Only the `.lazy.tsx` filename makes the
  generator emit `.lazy(() => import(…))`. Renaming one of those files silently deletes
  its code-splitting: `format:check`, `lint`, `typecheck`, `test` and `build` all stay
  green. (The other valid shape is `autoCodeSplitting: true` with plain `createFileRoute`;
  the two must not be mixed.) **`web/src/routeTree.lazy.test.ts` asserts it** via router
  state — an unloaded `options.component` — rather than by reading `dist/`, because
  `vitest` runs before `build` and a `dist`-reading test would skip itself on a clean
  checkout. Note `routeTree` is a module singleton whose route objects `.lazy()` mutates in
  place, so that file needs `resetModules` + dynamic import to stay order-independent.
- **`defaultPreloadStaleTime: 0`** because Query is the single source of staleness truth.
  Raising it gives the router a second cache with its own expiry and the two disagree.
- **No query-cache `localStorage` persistence** — PR #14, because the demo-scope
  exclusion needs auth state that does not exist until PR #6. Do not leave a persister
  half-built.
- Query retries skip 4xx and `NotJsonError`: both are unwinnable, and every retry is
  another Neon wake-up.
- **Router-plugin × MF-plugin ordering is not sensitive** — all four orderings of
  `tanstackRouter` / `react` / `federation` were verified to build, emit `remoteEntry.js`
  and split the lazy leaves (2026-08-14). `tanstackRouter` is listed first as the
  documented order, not a required one. Neither plugin needs a CSP `unsafe-*`: the built
  output contains no `eval`, no `new Function`, no `blob:` and no inline script or style.
- **Styles are split by mount**, which is what keeps the `.ct-app` rule honest:
  `styles/app.scss` is imported from `routes/__root.tsx` (so both mounts get it, and it
  contains zero `:root`/`body` rules), `styles/global.scss` only from `main.tsx` (the
  document reset, which must never reach the shell). The built remote's stylesheet was
  checked for `:root` leakage.

### Never register a service worker from `remote.tsx`

A service worker registered from the federated entry would be **scoped to
kilianmc.com** and start intercepting the production portfolio's requests. Low
likelihood, severe blast radius. **SW registration lives in `main.tsx` only** —
PR #7 (PWA) must keep it there.

`web/src/remote.guard.test.tsx` enforces this plus the `localStorage` rules below. It
shipped **vacuous** and was hardened on 2026-08-14; three jsdom facts caused that, and all
three will catch the next person out too:

- **`document.readyState` is already `'complete'` when a test runs**, so a listener added
  during `render()` never fires. `vite-plugin-pwa`'s `virtual:pwa-register` registers from
  a `window` `load` listener, which made the most likely PR #7 regression the one the guard
  could not see. The test dispatches `load` itself.
- **`localStorage.foo = 'x'` writes the value while completely bypassing
  `Storage.prototype.setItem`**, so a `setItem` spy misses it. Assert on
  `Object.keys(localStorage)`, not only on recorded calls.
- **`clear()` and `removeItem()` leave no trace in the final state** — and a remote calling
  `localStorage.clear()` wipes the *portfolio's* storage, which is worse than one bad key.
  Spy both.
- Module-scope side effects run when the test file's static imports are hoisted, i.e.
  **before any spy exists**. The entry is therefore imported dynamically, with
  `resetModules` per test, so module evaluation happens inside the observation window.

**It also carries a positive control asserting each detector can see its own violation.**
Keep it. Every storage assertion there passes on an empty set, so a mis-wired spy or an
undispatched event is indistinguishable from compliance — the same vacuity that hid the
FastAPI 0.137 route-walk defect while its test still passed.

### In the federated mount, `localStorage` is the SHELL's storage

The remote runs on the kilianmc.com origin, so it shares storage with the portfolio.

- **Namespace every key `ct:`.** No exceptions.
- **Store no tokens** anywhere in `localStorage`, in either mount.
- **Skip query-cache persistence in demo scope.**

Also scope the remote's CSS under a single **`.ct-app`** root, with design tokens as
custom properties **on that element** — not on `:root`/`body`. `fund-dashboard` gets
away with a global reset because it lives inside a full-viewport overlay; a
full-screen session player will fight the shell's `ProjectViewer` chrome.

### Module Federation shared singletons — the silent one

With `singleton: true` and no explicit `strictVersion`, MF defaults to
`strictVersion: false`. A React version mismatch is therefore **only a console
warning** — then MF **silently hoists the highest React** and hands it to code
compiled against the other version. Failures surface later and look completely
unrelated.

**Consequence: Track 0 (React 19 in `portfolio-shell` and `ai-portfolio-project1`)
MUST land before PR #5** (adding the `climbTrainer` remote to the shell). This repo is
already on React 19; shipping the remote into an 18 host is exactly the silent-hoist
scenario. Verify the shell console is warning-free at Track 0 step 5.

Remote contract (mirrors `ai-portfolio-project1/vite.config.js`):
`filename: 'remoteEntry.js'`, `dts: false`, react/react-dom singletons at `^19.0.0`
**plus scoped `'react/'` and `'react-dom/'` shares** so `react/jsx-runtime` and
`react-dom/client` resolve from the one instance, and `Access-Control-Allow-Origin: *` on
`/remoteEntry.js` + `/assets/*` only — see the two reasons in the CSP section.

**No explicit `build.target` — corrected 2026-08-14.** Earlier wording here required a
"modern `build.target`" on the grounds that MF needs top-level `await`. **That is false on
Vite 8**, whose default target (`baseline-widely-available`, i.e. chrome111+) already
supports it: removing the option leaves the top-level `await` in the output untouched, with
no warning. `ai-portfolio-project1` pins `chrome89` because it predates that default, so
copying it here would only **lower** our baseline. Do not re-add it "for MF".

`VITE_TRAINER_REMOTE_URL` in the shell must point at a **stable alias** (git-branch
alias or custom domain), never a deployment-specific URL — Hobby prunes deployments
after 30 days.

### TypeScript stays on 6.x

`typescript-eslint@8.67.0` peers **`typescript: >=4.8.4 <6.1.0`**, and the blocker is
upstream, not upstream slowness: TS 7 is the Go port, `require('typescript')` exposes
only `version` and `versionMajorMinor`, so `typescript-estree` has no compiler API to
read. Forcing it does not degrade quietly — `npm ci` fails on the peer range, and
`npm install` followed by a lint crashes inside `typescript-estree`
(typescript-eslint#12518, closed `not_planned`; tracking issue #10940, open).

The TS6-for-lint / TS7-for-`tsc` side-by-side alias works but is rejected here: it would
typecheck and lint against different compilers, so the two can disagree.

**ESLint 10 is a separate axis and is not blocked** — the same release peers
`eslint: ^8.57.0 || ^9.0.0 || ^10.0.0`. Bumping ESLint does nothing for TS 7.

**Decision 2026-08-12, re-verified 2026-08-14: stay on TS 6.x.** Revisit when #10940
closes, then re-verify `no-floating-promises` and `no-misused-promises` still fire —
they are the two rules an app built on optimistic writes and a background outbox needs
most.

### ESLint 10 rests on a forced jsx-a11y peer

`web/package.json` carries an `overrides` block forcing `eslint-plugin-jsx-a11y`'s
`eslint` peer to ours. Without it `npm ci` fails `ERESOLVE`: the plugin's range stops at
`^9` and 6.10.2 (2024-10-26) is the newest that exists.

Unlike the TS 7 case above this is **stale metadata, not a missing API** — verified
2026-08-14 before forcing it: none of the ten APIs ESLint 10 removed appear anywhere in
the plugin's source, and on ESLint 10.8.1 four of its rules still produce correct
diagnostics. The override is scoped to that one package deliberately; `--legacy-peer-deps`
would let unrelated peer conflicts through unnoticed.

**Delete the override** when jsx-a11y publishes an `^10` peer, and re-run the lint
against a known-bad component to confirm the rules still fire — a plugin that fails to
register is silent, and an a11y lint that checks nothing looks exactly like one that
passes.

---

## Database and compute budget

### Neon bills AWAKE TIME, not writes

Neon charges **CU-hours = compute size × time active**, and the compute stays up for
**5 minutes** after the last query. The cost driver is therefore **how spread out the
queries are**, not how many rows are written. This is the most counterintuitive fact
about the whole setup and it drives everything below. Free allowance: **100 CU-hr/mo**,
0.25 CU floor, 0.5 GB.

### Two write tiers

**The UI never waits on the database, in either tier.** Every action updates the local
cache optimistically and re-renders immediately. "Reflected in the UI" and "written to
the DB" are independent questions; the first is always *yes*.

**Tier 1 — write through immediately.** Deliberate, low-frequency, high-value actions,
one request each, fired the moment they happen, rolled back locally on failure:

- creating / switching / activating / abandoning a **plan**; editing a planned session
- **profile / target-grade** changes, equipment, availability, injury flags
- **ascents** — a send is the emotional payload of the whole app; never sit on one
- **notes / diary entries**, including a mid-session note
- **starting** a session (so a mid-run crash has something to attach to) and
  **finishing** one

A Tier-1 action taken mid-run **bypasses the outbox and piggybacks the pending
outbox in the same request** — the DB is being woken anyway, so the marginal cost of
flushing everything caught up so far is zero.

**Tier 2 — batched.** Only the repetitive per-set logging inside a live run: set
completions, actual load/reps/seconds/RPE. Flushed at **`Finish` only**, plus
`tab-hidden` and `online` as recovery safety nets.

> **Explicitly NO debounce timer and NO item-count trigger.** Any periodic flush would
> hold Neon awake for the entire session (~45–90 min) for zero user benefit, because the
> persisted local store is already authoritative and a run has exactly one writer.
> "Add a debounce so we don't lose data" is exactly the well-meaning change that would
> undo this — the reasoning belongs in a code comment next to the flush logic too.

**The rule for any future feature: if the user chose to do it, write it. If the app
recorded it as a side effect, batch it.**

### The other compute rules

- **Access tokens live 3 h, not 15 min.** Refresh rotation is a DB **write**, so a
  short-lived token would wake Neon every 15 minutes for a whole training session and
  quietly become the largest consumer of the compute budget. Refresh **lazily**, only
  on a 401.
- **Never write `last_used_at` / `last_seen` on read.** A touch-on-read column is the
  classic accidental write-per-request that defeats every other rule here.
- **Never cron-ping Neon to defeat autosuspend.** A 5-minute ping is ≈ **730
  CU-hr/month** against a **100 CU-hr** allowance — the free tier is gone in ~4 days.
- **No per-action telemetry rows.**
- **The Postgres rate limiter does NOT protect awake time — corrected 2026-08-13.** The
  original plan's risk #4 named "hard rate-limit `POST /api/auth/demo`" as the mitigation
  for the 100 CU-hr ceiling. **That wording is superseded and must not be restored from
  the plan.** `server/auth/ratelimit.py` counts with an upsert **and commits before it
  checks the limit** — so a request that gets a 429 has still written to Postgres and has
  still restarted the five-minute autosuspend window. Rejected traffic costs the same
  awake time as accepted traffic. (Do not invert it to check-then-count: that
  reintroduces a read-then-write race, and rejected attempts must be counted or the limit
  is trivially evaded.) The table is an **abuse** control — credential stuffing, address
  probing, unbounded demo-token minting — and it is worth having for that.
  **Awake-time protection for unauthenticated endpoints has to sit at the edge**, where
  the request never reaches the function: a Vercel WAF rule on `/api/auth/*`.
- **The 400-hour ceiling, and the arithmetic nobody had written down.** 100 CU-hr/month
  at the 0.25 CU floor is **400 awake-hours** against a 730-hour month, and **autosuspend
  is fixed at 5 minutes and is NOT configurable on the Free plan** (paid plans can only
  *disable* it, never shorten it — verified against Neon's scale-to-zero docs,
  2026-08-13). Each training session wakes the compute for roughly one 5-minute window
  per burst of activity, so 400 hours works out to **~260 sessions/month**, i.e. **about
  20 users training 3×/week** before the free tier is exceeded. Per-user cost is already
  close to the floor by design — batched Tier-2 writes, the CDN-cached library endpoint,
  and stateless token verification mean an authenticated request usually touches nothing.
  **Growth past ~20 users is solved by Neon's paid plan, not by restricting users.** Do
  not respond to this number by adding quotas, trimming features or shortening token
  lifetimes; the correct lever is $19/month.
- **⚠️ The demo endpoint's rate limit lives OUTSIDE this repository.** It is a **Vercel
  WAF rule on `/api/auth/*` — 20 requests / 10 minutes / IP** (10 minutes is the Hobby
  maximum window, and Hobby allows exactly one rate-limit rule per project).
  **Deleting that WAF rule silently removes the only rate limit on demo-token minting,
  and nothing in the codebase will hint that it is gone.** There is deliberately no
  `DEMO` rule in `server/auth/ratelimit.py` — it was removed 2026-08-13 because
  enforcing it was itself a Postgres write, so a rejected request cost the same awake
  time as an accepted one. A bot at **one request per minute** keeps the compute awake
  100% of the time (~182 CU-hr/month) while sitting inside any limit that table could
  express.
  - **The remaining exposure, honestly:** `POST /api/auth/demo` now issues **zero SQL**
    (no `Session` in its signature), so unlimited demo-token minting costs Vercel
    invocations (1M/month free) and CPU, and **zero Neon time**. That is the whole point
    of the change, and it is why unlimited minting is an acceptable worst case: the
    resource that is actually scarce is untouched.
  - **`x-forwarded-for` is NOT client-spoofable on Vercel — resolved 2026-08-13.** An
    earlier draft of this file claimed a header-rotating attacker could get a fresh
    bucket per request. That was wrong. Vercel's request-headers reference states: *"If
    you are trying to use Vercel behind a proxy, we currently overwrite the
    `X-Forwarded-For` header and do not forward external IPs. This restriction is in
    place to prevent IP spoofing."* The platform sets the header to the real client IP
    and there is exactly **one** entry, so leftmost and rightmost are the same string;
    `x-real-ip` and `x-vercel-forwarded-for` are documented as identical to it. Verified
    against <https://vercel.com/docs/headers/request-headers>, 2026-08-13. Two residual
    facts, neither a change to make: a proxy *this project* puts in front of Vercel could
    overwrite the header afterwards (`x-vercel-forwarded-for` is the documented escape
    hatch, and there is no such proxy), and **locally** under bare `uvicorn` the header
    is whatever the client sends, so the limiter is trivially bypassable in development.
- `GET /api/library?v=<buildId>` is user-independent and immutable per deploy — serve
  `public, s-maxage=31536000, immutable` with `staleTime: Infinity`. Zero DB time and
  zero invocations after the first request per deploy.
- **Two connection strings**: the pooled `-pooler` endpoint for the app
  (`DATABASE_URL`), the **direct** endpoint for Alembic (`DATABASE_URL_UNPOOLED`) —
  DDL and `CREATE TYPE` need a real session, and a migration through the pooler tends
  to **hang rather than error**.

### Engine config — the omissions are the point (revised 2026-08-12)

`server/db.py` is the authority; its module docstring carries the full reasoning. In
short, and superseding the earlier `pool_pre_ping` / `pool_recycle=300` / `pool_size=2`
line that appeared in the original plan:

- **`NullPool`.** A serverless invocation is frozen between requests, so a live pool is
  just idle connections nobody can use — and Neon's pooled endpoint already pools.
- **No `pool_pre_ping`** (it is a `SELECT 1`, i.e. a query that restarts the 5-minute
  awake window), **no `pool_recycle`** (a timer that can fire on its own), **no
  keepalive or warm-up traffic of any kind**, and **no connect at import** — the engine
  is built lazily on first use. `/api/health` deliberately does **not** touch the DB.
- **Prepared statements stay ENABLED.** The folklore that PgBouncer transaction mode
  breaks them is out of date: SQL-level `PREPARE`/`EXECUTE` are unsupported, but
  **protocol-level** prepared statements — what psycopg3 actually uses — are supported
  (PgBouncer ≥ 1.22; Neon runs `max_prepared_statements=1000`). **So there is no
  `prepare_threshold=None`, deliberately.** Verified against
  <https://neon.com/docs/connect/connection-pooling>, 2026-08-12. Do not "restore" it
  from an older draft of the plan.
- Other transaction-mode pooler limits, for later PRs: session-level `SET`/`RESET`,
  `LISTEN`/`NOTIFY`, `WITH HOLD` cursors and session-level advisory locks do not work
  pooled. Transaction-scoped **`SET LOCAL` does** — which is what the demo path's
  `SET LOCAL transaction_read_only` relies on. Keep it `SET LOCAL`, never a bare `SET`.
- **`TIMESTAMPTZ`, never naive.** `Base.type_annotation_map` pins `datetime` to
  `TIMESTAMP(timezone=True)` repo-wide, so every future `Mapped[datetime]` gets it
  without anyone remembering. Store aware, convert at the edge.

### Migrations run out-of-band

- Alembic runs via a **manual `workflow_dispatch`** job with `environment: production`
  (approval required), against the **direct** URL. **Never automatic on push** — a
  migration must never race a deploy, and deploys here are automatic while migrations
  are not.
- **Expand → deploy → contract**, always, for the same reason.
- In FastAPI's `lifespan`, only **READ** `alembic_version` and **warn** on mismatch.
  Never migrate at startup.
- Seeding reference data is `uv run python -m server.seed`, run **after** a migration.
  `server/seed.py` is the **single** seed module — CI, local work and production all
  call it, because a test fixture with hand-written rows tests a table production never
  has. It **upserts and never deletes**: user rows reference `grade.id`, so retiring a
  grade is a deliberate migration, not a side effect of editing a tuple. It also seeds
  the **demo account** (`demo@climb-trainer.example`, `password_hash = NULL`), which is
  deployment fixture data, not user data.
- **`DEMO_USER_ID` is pinned at 1 and is part of the data contract** — demo tokens carry
  it as `sub` so `POST /api/auth/demo` needs no lookup. Changing it is a migration. The
  seed inserts that id explicitly and therefore **repairs `app_user_id_seq`** afterwards
  (monotonic `setval`); without that the first real registration collides on the primary
  key and surfaces as a baffling 409 on someone's first sign-up.

#### How to actually run one: `.github/workflows/migrate.yml`

Actions → **Migrate** → *Run workflow*. Three inputs:

- **`environment`** — `dev` or `production`. This selects the GitHub **environment**, so
  `production`'s protection rules (approval) apply and each environment carries its own
  connection secrets. A `dev` run therefore cannot reach production's database.
- **`action`** — **`current` is the default, and it is read-only**: it prints the applied
  revision and stops. `upgrade` runs `alembic upgrade head` and prints `current` both
  before and after, so the job log is the audit trail. `history` lists the revisions.
- **`seed`** — off by default; when on, runs `python -m server.seed` after a successful
  upgrade.

**Prerequisite:** the two GitHub environments (`dev`, `production`) must exist, each
with **`DATABASE_URL_UNPOOLED`** (the *direct* endpoint — Alembic uses this) and
**`DATABASE_URL`** (the *pooled* endpoint — the seed step uses this) as environment
secrets. Without them the job starts and fails on the first Alembic step.

The workflow is `workflow_dispatch`-only and never prints a connection string; keep both
properties if you edit it.

##### ⚠️ Two traps that cost a debugging session on 2026-08-13, the day it first ran

**1. A `workflow_dispatch` workflow only registers if the file exists on the DEFAULT
branch.** `migrate.yml` shipped on `dev` in PR #2 and was therefore *completely inert*:
`gh workflow run` returned `HTTP 404: workflow migrate.yml not found on the default
branch`, and it did not appear in the Actions UI at all — so there was nothing to click
either. The GitHub environments and their secrets were correct the whole time and it made
no difference. PR #3 fixed it by putting the file on `main` on its own, as a deliberate
exception to the "`main` receives only promotion PRs" rule.

> **Keep `main`'s copy BYTE-IDENTICAL to `dev`'s.** The branches' merge base predates the
> file, so any difference is an **add/add conflict** at the first promotion. Identical
> content merges silently. A change to this workflow therefore takes **two** PRs — one to
> `dev`, one to `main` — and the same rule applies to every future
> `workflow_dispatch` workflow. Notes about the workflow go in *this* file, on `dev`, not
> in a comment that would have to be duplicated.

**2. `environment` chooses the DATABASE; the REF chooses the MIGRATIONS.** Registration
comes from the default branch, but GitHub takes both the job definition and the checkout
from the ref you select in the dialog. They are independent inputs and confusing them is
how production gets a revision nobody reviewed. Until the first `dev`→`main` promotion,
`main` has no `migrations/` directory and no alembic dependency, so a run must select
`dev`:

```bash
gh workflow run migrate.yml --ref dev -f environment=dev -f action=current
```

**And a third, smaller one: `alembic current --verbose` prints the connection URL.** It
emits a `Current revision(s) for <url>:` header. Alembic hides the password and GitHub
masks the secret, but the **Neon endpoint hostname, region and database name reach the
public log** — breaking the workflow's own no-connection-string rule via a flag rather
than an `echo`. The steps use bare `alembic current` for that reason; `alembic history
--verbose` is fine because it never opens a connection. Verified 2026-08-13 that nothing
else on the path logs a URL: `sqlalchemy.engine` is pinned to `WARNING` in `alembic.ini`
and `migrations/env.py` never prints one. **The lesson generalises — in a public repo,
audit what a tool prints at its chosen verbosity, not just what the workflow echoes.**

### SQLite is disqualified for tests

The schema uses native Postgres enums, `text[]`, `GENERATED … STORED`, GIN indexes and
window functions. Tests run against **real Postgres** (GitHub Actions `services:`
container, pinned to Neon's major): once per session `alembic upgrade head` — so **CI
tests the migrations** — plus seeding from the same module production uses; per test
`begin_nested()` + rollback. `alembic check` catches model drift. Do not "simplify" any
of this to SQLite.

Also: keep the plan tree **fully relational** (a row per prescribed set). It is the
showcase, and denormalising to `jsonb` saves nothing that matters — a 24-week plan is
~290 KB against 0.5 GB.

And: **never store a grade as a display string alone.** `grade` is
`(system_id, label, ordinal)` where `ordinal` is a shared integer ladder, so V5 / 7A /
6c+ are directly comparable. This is the single most expensive thing to retrofit.

---

## Security rules (set by Kilian, 2026-08-12)

Non-negotiable. The realistic threat is bulk data extraction, not defacement.

- **Deny-by-default auth.** Authentication is required unless a route appears on an
  **explicitly enumerated public-route list**. A test **walks every registered route**
  and asserts each one is either on that list or protected — so a new endpoint cannot
  be added unprotected by omission.
- **Every query is scoped by `user_id` taken from the token**, never from a
  client-supplied id, path param, or body field. **IDOR is the real extraction risk**
  here: one unscoped `WHERE id = :id` hands over every user's training history.
- **Demo mode is public by design, but read-only.** `POST /api/auth/demo` issues a
  short-lived token for a **seeded fake-data** demo user. Enforced two ways:
  `SET LOCAL transaction_read_only` on the demo path, **and** deny-by-default
  middleware rejecting every mutating method for demo tokens. A route-enumeration test
  asserts **every** mutating route 403s for a demo token. No real user data is ever
  seeded into demo. **Its rate limit is a Vercel WAF rule, not a Postgres row** — see the
  warning in the compute-budget section, and note the endpoint deliberately issues zero
  SQL so that unlimited minting cannot cost Neon time.
- **`/docs` and `/openapi.json` are OFF in production** — an OpenAPI schema is a map of
  the attack surface. See `_docs_enabled` in `server/app.py`.
- **CORS is an allowlist, never `"*"`**, with a **startup assertion** that rejects `*`
  (`server/settings.py`). Origins are echoed per-request from the allowlist with
  `Vary: Origin`; unknown origins get no `Access-Control-Allow-Origin`.
- **Auth design**: httpOnly `SameSite=Lax; Secure`, **host-only** (no `Domain`, so it
  can't leak to the apex) refresh cookie + access token **in memory only**. argon2id
  hashing, refresh rotation with reuse detection. **No tokens in `localStorage`,
  anywhere.** This works on both mounts because `climb.kilianmc.com` and `kilianmc.com`
  share the registrable domain and are therefore **same-site** — confirmed in S0 on
  WebKit, Gecko and Blink.
  - **The custom subdomain is load-bearing, not cosmetic.** `*.vercel.app` is on the
    Public Suffix List, so a preview URL is genuinely **cross-site** and the cookie
    cannot work there. Previews fall back to demo mode.

### Security response headers (v1.3.0)

Two delivery points, because their coverage differs: `vercel.json` `headers` for what the
**CDN** serves (SPA document, JS, CSS), and `server/security_headers.py` for **`/api/*`
JSON** — in-process, so it also applies under bare `uvicorn` and is assertable in CI. The
overlap is deliberate: a header set stops being sent without anything failing.

| Header | Document (`vercel.json`) | `/api/*` (middleware) |
| --- | --- | --- |
| `Strict-Transport-Security` | **not ours** — Vercel sends `max-age=63072000` | same |
| `X-Content-Type-Options` | `nosniff` | `nosniff` |
| `Referrer-Policy` | `no-referrer` | `no-referrer` |
| `X-Frame-Options` | `DENY` | `DENY` |
| `Cross-Origin-Opener-Policy` | `same-origin` | `same-origin` |
| `Permissions-Policy` | deny list below | same |
| `Content-Security-Policy` | document policy below | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` |
| `Cross-Origin-Resource-Policy` / `-Embedder-Policy` | **never set** | **never set** |

Document CSP, enforcing (not Report-Only):

```text
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none';
form-action 'none'; frame-src 'none'; frame-ancestors 'none';
upgrade-insecure-requests
```

- **No `unsafe-*` anywhere, `style-src` included.** React's `style={{…}}` writes through
  **CSSOM, which CSP does not govern**; only literal `style=` attributes in served markup
  need `'unsafe-inline'`, and SCSS compiles to external files. If something ever does need
  it, `vite preview` fails loudly — re-add one token then, with a reason. An `unsafe-*` kept
  "just in case" is how a CSP stays permanently weak.
- **`img-src data:`** — Vite inlines assets under 4 KB as `data:` URLs.
- **We do not set HSTS.** Vercel already sends `max-age=63072000` (verified `curl -sI`,
  2026-08-14), and duplicate STS fields are **not merged** — RFC 6797 §8.1 processes only
  the first. Cost: it is the one header we do not own, hence item 9.
- **⚠️ Never set `Cross-Origin-Resource-Policy`.** `same-origin` would stop kilianmc.com
  loading `/remoteEntry.js` and `/assets/*`. **This, not `frame-ancestors`, is the header
  that breaks the federated mount.** `cross-origin` is a no-op, and on `/api/*` a
  restrictive value sits in the path of the federated app's credentialed `fetch()` for no
  gain over CORS + Bearer. No `Cross-Origin-Embedder-Policy` either — `require-corp` blocks
  every cross-origin subresource and nothing needs `SharedArrayBuffer`. No `sandbox` in the
  API CSP: without `allow-downloads` it would break a future export endpoint.
- **`Permissions-Policy` lists only what we restrict; unlisted keeps the browser default.**
  `camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(),
  midi=(), display-capture=(), idle-detection=()`. ⚠️ **`screen-wake-lock`, `fullscreen`
  and `autoplay` must stay absent** — the session player needs all three. Tested, because
  "deny everything unused" is the change that would add them.
- **The `/api/docs` CSP exemption is derived from `app.docs_url` / `app.openapi_url`, never
  hardcoded** — both are `None` in production, so the exempt set is empty there. Swagger UI
  loads its assets from a CDN that `default-src 'none'` would block. Tested.
- **Middleware ordering:** `add_middleware` prepends, so the last added is outermost. The
  headers middleware is added last, outside CORS, and writes only its own header names —
  never `Access-Control-*` or `Vary`. Wrapping `send` is what covers the 401 / 403 / 404 /
  422 no endpoint produced. The two layers' coverage is not identical; hence both.
- **`vercel.json`'s `/(.*)` block intentionally overlaps `/api/*`.** Whether Vercel
  overwrites or appends on function responses is **unverified** — item 9 must `curl -sI` an
  `/api/*` path on the real deploy and check no header appears twice.
- **`vite dev` deliberately gets no CSP** — its inline client and HMR websocket would need a
  laxer policy than production, proving less. `vite preview` serves the real build with the
  real headers, read out of `vercel.json` by `web/vite.config.ts` so the two cannot drift.
- **For PR #5:** the *shell's* CSP governs the federated mount, not ours. `portfolio-shell`
  has none today; if it gains one it needs `script-src`, `connect-src` **and `style-src`**
  for `https://climb.kilianmc.com`.
- **⚠️ `Access-Control-Allow-Origin` on `/remoteEntry.js` alone is NOT enough — two
  independent reasons, both proved by deleting the rule (2026-08-14):**
  1. `remoteEntry.js` is a two-line stub that **statically imports**
     `/assets/virtual_mf-REMOTE_ENTRY_ID….js`. Without the header on `/assets/*` the very
     first `import()` rejects with `TypeError: Failed to fetch dynamically imported
     module`, before any CSS is involved.
  2. The exposed `./App` chunk also references its own stylesheet (`app.scss`), which MF
     loads as a cross-origin `<link>`; with the header on everything except the emitted
     `.css`, `get('./App')` rejects with `Unable to preload CSS`. This is the `style-src`
     half above.

  So dropping the stylesheet would **not** make the `/assets/*` rule unnecessary. Both
  rules are asserted by `web/src/mf-contract.test.ts`, which also asserts the wildcard is
  on those two sources and nowhere else — deleting either one otherwise kills the federated
  mount on the live portfolio, from this repo, with a fully green gate.

### Auth implementation (PR #3) — where each piece lives

`server/auth/` — `passwords.py`, `tokens.py`, `refresh.py`, `cookies.py`,
`ratelimit.py`, `deps.py`, `routes.py`. Each module's docstring carries its reasoning;
this is the map, not a substitute for reading them.

**Two token shapes, and they are deliberately different things:**

- **Access token** — HS256 JWT, claims `sub` / `scope` / `typ` / `iss` / `iat` / `exp`.
  **3 h** for `user`, **1 h** for `demo`. Verified with `algorithms=["HS256"]` and an
  explicit `require=[…]`, and **verification never touches the database** — that is what
  keeps an authenticated request from waking Neon. Held **in memory** by the client.
- **Refresh token** — opaque, 32 random bytes, stored only as a **sha256 hex digest**,
  30-day lifetime, in an httpOnly `SameSite=Lax` host-only cookie scoped to
  `path=/api/auth`. Rotated on every use, in a **family**; presenting an
  already-rotated or revoked token **revokes the whole family** (`refresh.rotate`).
  sha256 rather than argon2 because the token is already 256 bits of entropy.
  `rotate()` reads its row **`FOR UPDATE`** — without the lock two simultaneous
  presentations of the same token both pass the reuse check and reuse goes undetected,
  which is the exact case the family mechanism exists for.

**The public-route list is `PUBLIC_ROUTES` in `server/auth/deps.py`.** `enforce_auth`
is registered **once, application-wide** (`FastAPI(dependencies=[…])`), never per
router — opt-in fails open when someone forgets. Adding an endpoint protects it by
default; making it public is a visible line in that frozenset.
`tests/test_auth_routes_enumerated.py` walks every registered route and fails if one is
neither listed nor 401-ing.

**Demo read-only is enforced twice**, per the rule above: `enforce_auth` 403s a
`demo`-scope token on every `POST/PUT/PATCH/DELETE` (sole exception:
`POST /api/auth/demo`, enumerated in `DEMO_WRITE_EXEMPT_ROUTES`), **and**
`get_request_session` issues `SET LOCAL transaction_read_only = on` for a demo
principal. A consequence for the auth UI: a client in demo mode must **drop its demo
token before calling login or register**, or those calls 403.

`AUTH_SECRET` (≥32 chars) is read lazily via `server/settings.py::auth_secret()`, never
at import time, and must be set in Vercel for every scope.

Rate limiting lives in the `rate_limit` table, keyed by an **HMAC of the subject** — the
raw IP or email is never stored. Three IP-keyed rules (`login` 10/15 min, `register`
3/hour, `refresh` 30/hour) plus **`login_account`, keyed on the attempted email**, because
a per-IP limit does nothing against an attacker spread across many addresses. There is
**no `demo` rule** — that one is a Vercel WAF rule instead (see the compute-budget
warning). `login` and `refresh` are generous on purpose and lowering them buys nothing:
each attempt is one write, so the Neon cost is identical at 3 or 30, and a tighter limit
only inconveniences someone mistyping a password. Login checks both of its buckets **in a
single `INSERT … ON CONFLICT` statement** (`enforce_all`), so the second dimension costs
no extra round trip and no extra Neon wake-up. `login_account` is 30/hour: an attacker
can deliberately hold a real user at 429, which is accepted — it self-heals within the
hour and is a **rate limit, never an account lockout** (no state disables an account).
The 429 is identical whichever bucket tripped, and the email counter increments for
addresses that do not exist, so it is not an account-existence oracle. It is an **abuse**
control only; see the correction in the compute-budget section for why it does not
protect awake time.

### 🔒 TODO — the end-to-end security verification pass (Kilian's call, 2026-08-13)

**Not yet done. Do not tick any of it off from memory.** Every rule in this file was
written because of a real risk, and a rule that was implemented once and never verified
against the running system is indistinguishable from a rule that quietly stopped working.
Two of the controls listed below **do not live in this repository at all**, so no test in
CI can ever notice their absence.

**When:** once the product is feature-complete on `climb.kilianmc.com` — realistically
after PR #7 — and **before** the project is shown to anyone as a portfolio piece. Run it
against the **production deploy**, not a preview: previews are cross-site
(`*.vercel.app` is on the Public Suffix List) and behave differently on purpose.

**Scope it honestly — three tiers, and only two of them need a human:**

- **Already proven by CI on every push. Do NOT re-test by hand:** the route-enumeration
  auth/demo tests, the routing contract, the version wiring, refresh rotation and reuse
  detection under a real row lock, the rate-limiter's single-statement upsert, `alembic
  upgrade head` + `alembic check` on a fresh Postgres, gitleaks over full history.
  Re-checking these manually is how a verification pass becomes theatre.
- **Only verifiable against the real deployment**, because the Vercel rewrite, the CDN
  and the browser are the parts CI does not have:
  1. **Routing** — `/api/health` → JSON, `/api/nope` → FastAPI's **JSON** 404 (not the
     SPA shell), `/` and `/deep/link` → `text/html`. The dangerous failure is a
     `200 text/html` from an `/api/*` path.
  2. **`/api/docs` and `/api/openapi.json` → 404 in production.**
  3. **CORS** — an allowed origin is echoed with `Vary: Origin`; an **unknown origin gets
     no `Access-Control-Allow-Origin` header at all**; there is no `*` anywhere on
     `/api/*`. Test with a real preflight, not just a GET.
  4. **Cookies** (browser devtools — ask Kilian) — the refresh cookie is `HttpOnly`,
     `Secure`, `SameSite=Lax`, `Path=/api/auth`, and has **no `Domain` attribute**.
     And **nothing token-shaped in `localStorage` or `sessionStorage` in either mount** —
     check the federated mount too, where the storage is kilianmc.com's.
  5. **Deny-by-default through the rewrite** — hit a protected endpoint anonymously on
     the deploy. The enumerated test proves this in-process; this proves the rewrite
     doesn't route around it.
  6. **IDOR, with two real accounts** — as user A, request user B's plan / session /
     ascent / diary entry by id. Expect 404 or 403 and **never** a row. This is the
     single highest-value check in the list: it is the actual extraction risk.
  7. **Demo mode against a live mutating endpoint** — a demo token must 403, and the
     `SET LOCAL transaction_read_only` layer must reject a write if the first layer is
     ever bypassed.
  8. **Login rate limit** — it trips; the 429 is byte-identical for a real and a
     non-existent address; it self-heals within the window and no account is ever
     disabled.
  9. **Security response headers** — landed in v1.3.0; see the baseline section above. On
     the real deploy check that the `vercel.json` layer reaches **`/api/*`** and that no
     header (notably `Strict-Transport-Security`) appears **twice**, and that the document
     CSP logs no console violations on a real page load.
     - **CORRECTED 2026-08-14:** the original wording predicted `frame-ancestors` would
       break the federated mount. It cannot. The shell mounts us as a **script**
       (`React.lazy(() => import('climbTrainer/App'))`), never in an iframe — verified in
       `portfolio-shell/src/components/ProjectViewer.tsx`, whose `<iframe>` branch is the
       *other* pattern (`kind: 'embedded'`). **`Cross-Origin-Resource-Policy` is the header
       that would break it**; verify it is still set nowhere.
  10. **No secret in the client bundle** — grep the built `web/dist` for any value of a
      non-`VITE_` env var, and for anything resembling `AUTH_SECRET`.
- **Infra, outside the repo — these are the ones nothing else can catch:**
  11. **The Vercel WAF rule on `/api/auth/*` still exists and actually fires** (20 req /
      10 min / IP). Confirm the denials appear in the Firewall traffic view. **This is
      the only rate limit on demo-token minting** — see the ⚠️ in the compute-budget
      section.
  12. **Vercel project settings** — `framework` is still `null` (re-check after any
      `vercel link`), and `ssoProtection` is still **ON** for this project's previews.
  13. **Zero open Dependabot alerts**, or each remaining one triaged with a written
      reason it does not apply. On 2026-08-13 there were 6 (starlette + pytest) and none
      were exploitable here, but "not exploitable" needs re-deciding per alert, not once.
      v1.3.0 raises `starlette` to 1.6.0 and `pytest` to 9.1.1 without changing that
      reasoning — still no `request.form()`, no `StaticFiles`, no `HTTPEndpoint`, and
      nothing reading `request.url.path` or the Host header (`server/security_headers.py`
      matches `scope["path"]`, the ASGI request target, by exact equality). **Alerts are
      raised against the default branch, so they clear at the first promotion to `main`,
      not on merge to `dev`.** Also confirm the Dependabot config is actually opening PRs.
  14. **2FA still enabled on GitHub, Vercel, Neon and Cloudflare.**
  15. **Neon CU-hours for the month match the model** in the compute-budget section. A
      figure well above it means something is waking the database — that is the signal.

**Script what is scriptable** (1, 2, 3, 5, 6, 7, 8, 10 are all `curl`/CLI), and **ask
Kilian for the browser-only ones** (4, 9, 11) rather than burning turns on them.
**Write the outcome down** — in the PR that does the pass, with the date — so the next
person verifies rather than re-verifies.

---

## Injection defence and input minimisation (OWASP)

**This is the portfolio's first project with a database, so treat this section as
first-class, not boilerplate.** Injection is still OWASP A03, and it is the one class
of bug where a single careless line hands over the entire dataset. Two halves: never
build SQL from strings, and give the attacker as little free-form input as possible in
the first place.

### Bound parameters only — never string-built SQL

- **Use SQLAlchemy 2 constructs with bound parameters, always.** `select(Ascent).where(
  Ascent.user_id == user_id)` compiles to a parameterised statement; the value never
  touches the SQL text.
- **Never build SQL with an f-string, `%` formatting, `.format()`, or `+`.** Not even
  "just for a quick debug query", because quick debug queries get committed.
- **Never pass interpolated text to `text()`.** `text(f"... {value}")` is exactly as
  dangerous as raw string concatenation and is the usual way an ORM project gets
  injected anyway. If raw SQL is genuinely needed — and it will be, for the diary's
  `UNION ALL` timeline and the send-pyramid window functions — write
  `text("... WHERE user_id = :user_id AND entry_date < :before")` and pass the values
  as bound parameters.
- Same rule for `LIKE`/full-text search: bind the pattern as a parameter and escape the
  user's `%` and `_` yourself; don't assemble the pattern into the SQL string.

### Identifiers cannot be parameterised — use an allowlist

Bound parameters only work for **values**. Table names, column names, sort keys and
sort directions are **identifiers**, and there is no placeholder for them. So:

- **Map every dynamic identifier through an explicit allowlist** — a `dict[str,
  InstrumentedAttribute]` of permitted sort columns, keyed by the literal strings the
  API accepts. Anything not in the dict is a 422, not a fallback.
- **No dynamic `order_by`, `GROUP BY`, or column list built from raw client input**,
  ever. `order_by(text(request.sort))` is a straight injection.
- Same for the sort direction: accept `Literal["asc", "desc"]` and branch on it; don't
  interpolate the string.

### Prefer CLOSED inputs over free text

The cheapest injection defence is having nothing to inject into. This app is unusually
well suited to it — almost everything the user tells us is a choice from a known set:

- **Enums / `Literal` unions** for discipline, ascent style, protocol kind, phase,
  session status.
- **Selects, sliders and steppers** for sessions-per-week, aspect self-ratings, RPE,
  attempts, board angle, load and reps — bounded numerics, not text boxes.
- **Grade pickers sourced from the seeded `grade` ladder**, submitted as a `grade_id`
  that must resolve against the reference table. Never accept a free-typed grade
  string, and never accept a client-supplied `ordinal`.
- **Equipment and injury flags** as ids from the seeded lookup tables.

**The only genuinely free-text fields in the whole product are the diary notes** —
`logged_session.notes`, `logged_set.note`, `ascent.notes`, `journal_entry.body` — plus
email and password at registration. That is a very small, very well-known surface.
Keep it that way: if a new feature seems to want a free-text field, check first whether
it is really a closed set.

### Validate at the edge with Pydantic

Every request body and query string is a Pydantic model. Untyped `dict` bodies and
hand-rolled parsing are not acceptable.

- **Typed and bounded**: `Annotated[int, Field(ge=1, le=7)]`, `conint`/`confloat`-style
  bounds on RPE, load, reps, seconds, attempts, board angle.
- **`Literal` for closed vocabularies**, so an unknown value is a 422 before any query
  runs.
- **Max lengths on every string** — notes included. An unbounded text field is a
  storage-exhaustion vector against a 0.5 GB database, and it defeats the sizing
  assumptions in the compute-budget section.
- **Paginate every list endpoint** — a bounded `limit` (with a hard server-side
  maximum) plus a keyset cursor. "Return everything" is the injection-adjacent risk:
  resource exhaustion, and it also wakes Neon for longer than it needs to be awake.
- Reject unknown fields (`model_config = ConfigDict(extra="forbid")`) so a typo'd or
  probing field never silently reaches the ORM. Never build an ORM object by splatting
  a client dict (`Model(**payload)`) — assign fields explicitly, or mass assignment
  becomes a way to set `user_id`.

### Notes are untrusted on OUTPUT too

Storing user text safely is only half the job — stored XSS is the other half.

- **React escapes interpolated content by default. Rely on that.**
- **NEVER use `dangerouslySetInnerHTML` on user content.** Not for notes, not for
  "just a bit of markdown" in a diary entry, not for a search-result highlight. If
  highlighting is wanted, split the string and render `<mark>` elements as React
  nodes — never assemble an HTML string.
- Same for `innerHTML`, `document.write`, and injecting user text into a `style` or
  `href`/`src` attribute (`javascript:` URLs).
- The API returns JSON only, so there is no server-side template escaping to get wrong
  — keep it that way.

---

## Versioning

The **root `package.json` is the sole source of truth.** Baseline production `1.0.0`;
`npm run version:dev` bumps the **minor**, `npm run version:release` bumps the
**major** and resets the minor. **`web/package.json` and `pyproject.toml` stay at
`0.0.0`** — two version numbers that can disagree are worse than one.

The API's version follows automatically: `server/settings.py` exposes `app_version()`,
which reads the root `package.json` at import time (with a `0.0.0+unknown` fallback, so
a missing file can never take the function down over a cosmetic string), and
`server/app.py` passes it to `FastAPI(version=…)`. **Never hardcode a version literal
in Python** — that was a fourth version string that would have drifted on the first
`version:dev`, and the OpenAPI schema would then lie about which build is live.
`tests/test_version.py` asserts the wiring, including that no literal has crept back in.

## Branch model

Two long-lived branches: **`dev`** (integration) and **`main`** (production,
`climb.kilianmc.com`). **All feature PRs target `dev`.** `main` receives only
`dev`→`main` promotion PRs, merged by Kilian after he has tested the dev deploy.
Conventional Commits (`feat:`, `fix:`, `chore:`, `test:`, `docs:`); branches mirror
the type (`feat/…`, `chore/…`).

> **⚠️ `main` is the GitHub DEFAULT branch, not `dev`** (verified 2026-08-14,
> `gh repo view --json defaultBranchRef`). GitHub reads several things **only** from the
> default branch, so anything in that class needs a two-sided `dev` + `main` copy: so far
> `.github/workflows/*.yml` (`workflow_dispatch` registration), `.github/dependabot.yml`,
> and Dependabot **alerts**. This is the confusion behind the `migrate.yml` trap above.

---

## 🧹 TODO — comment and docs deep clean (its own PR, AFTER PR #19)

**Kilian's call, 2026-08-14: verbosity is FINE during development — do not spend review
turns trimming prose while the project is still being built.** The clean-up is a single
deliberate pass **once the project is done**, and it needs its own review, so it is not
folded into the 1.0.0 promotion. Two goals, in this order:

1. **Trim everything to the minimum.** Source comments: delete what restates the code and
   all historical narrative; keep one-line constraints. **Convert "don't change this or X
   breaks" into a test or a lint rule** rather than deleting it. `CLAUDE.md` / `README`:
   trim narrative, **keep every trap and hard rule**.
2. **Move the important stuff into a PRIVATE file so it is protected.** Design reasoning may
   stay public; the **security control map, thresholds and infra topology go private**.
   ⚠️ A public repo has **no per-file access control** and git history is permanent, so
   anything moved **was already public** and must be re-thought or rotated, not just deleted
   — which is the reason this is a real task and not a `git mv`.

- **The dev journal stays public** — design and product decisions only, never where the
  controls live or what their limits are.

## Dependency policy (set by Kilian, 2026-08-14)

**Pin every dependency to the latest stable version verified against the registry at pin
time — never one recalled from memory.** Check PyPI / npm in the same turn you write the pin.
This repo was scaffolded with `fastapi` 6 months, `starlette` 7 and `pytest` 9 months stale,
which produced 6 Dependabot alerts and turned a day-one patch bump into a 0.x→1.x migration.

Two exceptions: **runtimes track LTS** (Node 24, Python 3.13), and **`@types/*` match the
runtime major, not the newest** — `@types/node` is held at 24 via an `ignore` entry, because
type-checking against a runtime we do not run is a defect TypeScript accepts silently. The
TypeScript 6.x hold in the frontend rules is a capability decision, not a staleness one.

**Four upgrade traps, each already paid for:**

- **`uv lock` will not move a transitive pin.** Bumping `fastapi` reported success and left
  `starlette` at the vulnerable version. Needs `uv lock --upgrade-package starlette`, and
  verify with `uv pip list`, not the `uv lock` output. `starlette` stays un-pinned in
  `pyproject.toml`: it is FastAPI's dependency and a second pin could contradict its range.
- **Since FastAPI 0.137, walk routes with `fastapi.routing.iter_route_contexts`, never
  `app.routes`.** `include_router` stores a tree node, so direct iteration hides every
  router-mounted endpoint — which made the deny-by-default walk in
  `tests/test_auth_routes_enumerated.py` vacuous **while it still passed**. A canary test
  now asserts a protected included route is in the walk; if it fails, fix the walk.
- **`strict_content_type` is on by default since FastAPI 0.132**: a POST without
  `content-type: application/json` is a 422. **PR #6 must send it** — `apiFetch` sets only
  `accept`.
- **`httpx2` replaces the `httpx` + `starlette.testclient` pairing** before Starlette 2.0,
  where today's deprecation warning becomes an error. A package swap, not a version bump.

### `.github/dependabot.yml`

**Alerts alone open no pull requests** — which is why 6 stale-dependency alerts sat
unnoticed with alerting fully enabled.

- **⚠️ The file is read from the DEFAULT branch only**, i.e. `main`: *"The `dependabot.yml`
  file must be present on the **default branch** … regardless of which branch you specify as
  the target."* **A copy on `dev` alone is inert**, the same failure as `migrate.yml`. So it
  needs the **byte-identical twin** treatment: two PRs, and **no comments in the YAML** (any
  byte difference is an add/add conflict at the first promotion), which is why its reasoning
  lives here.
- **⚠️ Dependabot ALERTS are also raised against the default branch.** `main` still carries
  the vulnerable `starlette`, so merging to `dev` does not clear the 6 open alerts — they
  clear at the first promotion to `main`.
- **`target-branch` and security updates conflict and cannot both be satisfied.**
  `target-branch: dev` is set, because version-update PRs must not land on `main`. The docs:
  *"Pull requests for security updates still target the default branch"*, and *"you should
  not specify a `target-branch`"* for security updates. So security PRs ignore this config's
  grouping and `ignore` rules and target `main`. **Currently theoretical —
  `automated-security-fixes` is disabled on the repo**; enabling it is what makes this bite.
  The alternative shape (a second block with no `target-branch` and
  `open-pull-requests-limit: 0`) is unshipped because the docs do not say whether two blocks
  may share an ecosystem + directory.

Covered: `uv` at `/`, `npm` at `/web`, `github-actions` at `/`; weekly, grouped per ecosystem.

**Two `ignore` entries, for different reasons.** `@types/node` is held at the runtime major
(staleness is the *correct* state). `typescript` majors are held because of the 6.x capability
hold above — and the entry matters more than it looks: the `web` group is `patterns: ["*"]`,
so with TS 7 in scope **every** grouped web PR inherits its blocked peer range. PR #11 arrived
carrying nothing but TypeScript and could not be merged; without the ignore, that recurs weekly
and takes real updates hostage.

### ⚠️ Pinned actions Dependabot can never bump (2026-08-14)

**`astral-sh/setup-uv` stopped publishing major and minor tags at v8.0.0**, deliberately, as a
supply-chain measure after the tj-actions compromise. There is no `v8`/`v9`/`v10` tag, so a
reference to `@v7` has nowhere to move and **Dependabot goes silent rather than failing** — it
sat 3 majors behind while the actions group reported itself up to date. Both workflows now pin
the exact **`@v10.0.1`**, which Dependabot can bump, and which is as safe as a SHA because v8+
are immutable releases whose tags cannot be repointed.

Generalise: **an action pinned to a floating major is only watched while that major tag keeps
being published.** When an action moves to exact-tag-only releases, our pin silently freezes.
Neither a green gate nor an empty Dependabot queue distinguishes "current" from "abandoned" —
so when an actions-group PR omits an action, check the action's tag list before assuming it is
already current.

Neither v9 nor v10's breaking changes affect us: v9 changed the `prune-cache` default and v10
disables caching for `pull_request_target` / `workflow_run` / `release` under
`enable-cache: auto`. Both workflows set `enable-cache: true` explicitly and neither uses those
events.

**Deadline already met, worth knowing why:** `gitleaks/gitleaks-action@v3` is *only* a Node
20→24 runtime bump, no input or behaviour change. It is not optional — GitHub removes Node 20
from hosted runners on **2026-09-16**, after which `@v2` stops working regardless of any
opt-out flag.

## Local development

Two processes. The API on 8000, the SPA on 5173 with Vite proxying `/api` to it:

```bash
# terminal 1 — API
uv run uvicorn server.app:app --port 8000 --reload

# terminal 2 — SPA (Vite proxies /api -> 127.0.0.1:8000)
npm --prefix web run dev
```

### `.env` is loaded for you — but only outside Vercel

`cp .env.example .env`, fill it in, done. **`server/settings.py` loads it at import time
via python-dotenv**, and every entrypoint imports that module, so the API, `alembic`,
`pytest` and `python -m server.seed` all see it with **no `--env-file` flag and no
shell-sourcing**. Four properties worth knowing, all in `_load_local_dotenv()`:

- **An exported environment variable always beats the file** (`override=False`). Vercel
  and GitHub Actions inject the real values and must win.
- **Skipped entirely when `VERCEL` / `VERCEL_ENV` is set**, so a stray `.env` inside a
  deployment can never shadow production config, and cold starts pay no file probe.
- **Silent no-op if `.env` is absent** — CI has none and stays green.
- **An explicit repo-root path**, not `find_dotenv()`, which walks *up* from the cwd and
  would pick up an unrelated `.env` from the shared `Projects/` tree.

> This was a real bug, found on 2026-08-12: the docs and the error messages both said
> "copy `.env.example` to `.env`" while **nothing in the repo actually loaded it**, so
> following the documented steps produced `RuntimeError: No database URL` telling you to
> do what you had just done. If you ever change the loading, change these docs and the
> two error messages (`server/db.py`, `migrations/env.py`) in the same edit.

Quote any value containing `&` in `.env` — Neon appends `&channel_binding=require`, and
while python-dotenv handles it bare, `set -a; . ./.env` does not.

`CORS_ORIGINS` must be set for the server (see `.env.example`); with the proxy in play
requests are same-origin from the browser's point of view, so CORS mostly doesn't fire
locally — which is itself a reason to be careful:

> **⚠️ The Vite dev proxy is NOT Vercel's rewrite.** They are two different mechanisms
> that happen to produce a similar result. The proxy forwards anything under `/api`
> unconditionally; Vercel's rewrite depends on `framework: null`, the project-level
> framework setting, path preservation, and the negative-lookahead SPA fallback.
> **A routing change that works locally proves nothing about production.** Any change
> to `vercel.json`, the rewrites, `api/index.py`, or the API base **must be re-verified
> on an actual deploy**: `/api/health` → JSON, `/api/nope` → FastAPI's JSON 404, `/` →
> `text/html`, `/deep/link` → `text/html`.

## Quality gate

**One command, and it is the same nine checks CI runs:**

```bash
npm run check          # == check:web && check:server
```

Or the halves / individual checks:

```bash
npm run check:web      # format:check -> lint -> typecheck -> test -> build
npm run check:server   # ruff check -> ruff format --check -> mypy -> pytest

npm --prefix web run format:check   # Prettier
npm --prefix web run lint           # ESLint (type-aware — see the TS 6.x note)
npm --prefix web run typecheck      # tsc -b (strict)
npm --prefix web run test           # Vitest once
npm --prefix web run build
uv run ruff check .
uv run ruff format --check .
uv run mypy                         # strict; files come from pyproject.toml
CORS_ORIGINS=http://localhost:5173 uv run pytest -q
```

**The local gate passes with no database, on purpose.** There is no local Postgres and
no Docker on the dev machine, so `tests/conftest.py` **skips** the DB-backed tests when
`DATABASE_URL` is unset. Never make the local gate depend on a database, and never
substitute SQLite to avoid the skip — a skip is visible, a false pass is not. CI is
where the migrations and the seed are actually executed.

**Batch your edits and run `npm run check` once at the end**, not once per file.

**CI has three required jobs: `web`, `server`, and `secrets`** (gitleaks over full
history). Kilian's call: **require all three** rather than collapsing them into a single
`lint-build` gate as the other repos do — three named checks say *what* broke on the PR
page, and a leaked-secret failure should never be indistinguishable from a lint failure.
If you read "one required check named `lint-build`" in the original plan, that wording
is superseded.

`npm run check` covers `web` + `server`. The `secrets` job is CI-only (gitleaks isn't a
project dependency) — so the local gate is 9 checks and CI is 12: gitleaks, plus
`alembic upgrade head` and `alembic check` against the `postgres:17-alpine` service
container, which only exist in CI. Don't try to fake those locally; just never commit a
secret, and let CI prove the migrations.

**The job names `web`, `server` and `secrets` are required status checks in a GitHub
ruleset. Renaming one silently breaks the merge gate** — the rule waits forever for a
check that will never report. Add steps to a job freely; never rename a job.

`web/src/test/setup.ts` is where jsdom stubs for the device APIs go as they arrive
(`navigator.wakeLock`, `AudioContext`, `navigator.vibrate`, `navigator.onLine`),
mirroring the `matchMedia` convention in `portfolio-shell/src/test/setup.ts`. The
clock tests need fake timers plus a `performance.now` shim.

## Testing policy — deliberately not "test everything"

**Kilian's standing rule across all his projects.** Coverage is not the target; a test
suite is an asset only where it buys confidence, and a liability everywhere else. A test
that merely restates the implementation is **maintenance cost with no safety value** —
it breaks on every refactor and catches nothing.

**WRITE tests for:**

- **Critical business logic and domain rules** — the grade **ordinal ladder** and its
  monotonicity, plan generation (phase spans, deloads, taper, volume allocation,
  equipment/injury filtering), scoring like sRPE / ACWR, and **date and timezone maths**.
- **Core user paths** — auth (register, login, refresh rotation, logout, demo), anything
  that **saves or submits**, and above all **anything that can lose user data**: the
  outbox flush, idempotent replay by `client_uuid`, the bulk plan insert's
  all-or-nothing transaction.
- **Complex transforms, parsers and state machines** — the protocol compiler, the
  session-player clock (especially the background-gap / missed-cue behaviour), the
  diary's merged timeline query.
- **Any bug just fixed.** A regression test is the one test that has proven its value
  before it is written.
- Project-wide invariants that silently rot — the routing contract
  (`tests/test_routing.py`), the version wiring (`tests/test_version.py`), the
  route-enumeration auth and demo-mode tests.

**SKIP tests for:**

- **Simple static or presentational UI** — a card that renders the props it was given.
- **Trivial getters/setters and pass-through wrappers** — testing these tests the
  language.
- **Plain config objects** and constant tables.
- **Throwaway prototypes and spikes** (S0 shipped no tests, correctly).
- **Anything the type system or a lint rule already guarantees.** TS strict +
  `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes` + type-aware ESLint already
  prove a lot; a runtime test asserting a typed field exists is dead weight.

**When you are unsure, ASK — do not default to writing a test.** "I added tests to be
safe" is how a suite becomes slow and brittle. Justify each new test file by which
bullet above it satisfies; if it fits none of them, say so in the PR instead of writing
it anyway.

Note this policy governs *what* to test, not *how well*: the tests that do exist should
be real — no snapshot-everything, no asserting on mock call counts as a proxy for
behaviour, and integration over unit where the integration is the risky part (which is
why the backend tests run against real Postgres, not SQLite).

## UI design direction (drives PR #7 — intended direction, NOT implemented yet)

Recorded now so PR #7's design system is built to it, and so nothing lands before then
that contradicts it. **Do not implement any of this ahead of PR #7** — `global.scss`
today is a deliberate minimum.

**The look**: modern, blending simplicity with **tactile** elements — functional
**bento-box** card layouts, generous touch-friendly targets, honest depth. Calm by
default; the app should feel like a tool, not a dashboard.

Guiding principle, in Kilian's words: **"we prefer useful than looking pretty."** When
a visual flourish and legibility disagree, legibility wins without discussion.

### Glassmorphism: considered and REJECTED (2026-08-12)

**Do not use `backdrop-filter`. Do not reintroduce translucent "glass" surfaces
anywhere, including as a subtle accent on chrome or cards.** This was explicitly
evaluated and rejected by Kilian on 2026-08-12 — it is a closed decision, not an
oversight for a future agent to helpfully improve.

Why: `backdrop-filter` forces a separate compositing layer and a blur pass every frame,
which is **GPU- and battery-expensive on a phone that is awake and in use partway
through a training session**. And translucency is straightforwardly *worse* at the one
thing that matters most here — being readable at arm's length, with sweaty or chalky
hands, in bad gym lighting.

**Tactility comes from OPAQUE ELEVATED SURFACES instead:**

- **Solid backgrounds.** Every surface is opaque. Elevation is expressed with a distinct
  surface colour, not by letting content show through.
- **Subtle borders** (a hairline in a slightly contrasting tone) to separate surfaces,
  which reads more crisply than a blur ever does.
- **Real press / active states** — a visible change on `:active` and on
  `:focus-visible`, so a tap is unambiguously acknowledged. This is the single biggest
  contributor to an app feeling tactile, and it costs nothing to render.
- **Honest depth** — a restrained, consistent shadow scale that says which surface is
  above which. No decorative shadows that imply an elevation that isn't real.

### Accessibility is part of the design, not a later pass

- **Respect `prefers-reduced-motion`** — no transitions on the tactile affordances, and
  the player's cues fall back to instant state changes (the cue itself must still fire;
  reduced motion is not reduced information).
- **WCAG AA 4.5:1** for text, which on opaque surfaces is a straightforward
  token-vs-token check per surface — one of the practical benefits of dropping
  translucency: contrast becomes decidable from the tokens instead of depending on
  whatever happens to be scrolling underneath.
- **Touch targets ≥ 44px** (44×44 CSS px minimum), with adequate spacing — this is a
  one-handed, mid-workout, possibly-chalky-fingers app.
- **Primary actions bottom-anchored** for one-handed thumb reach, using the
  **safe-area insets already established in `web/src/styles/global.scss`**
  (`env(safe-area-inset-*)` with `max()` floors, and `viewport-fit=cover` is already set
  in `index.html`). Never put a primary action in a top corner.

### Bento layouts must reflow between the two mounts

- **CSS grid with named areas** for the bento arrangement, plus **container queries** on
  the cards themselves.
- The reason is structural: the same card component renders in the **full-width
  standalone app** and in the **smaller federated mount** inside the shell's
  `ProjectViewer`. A media query asks about the *viewport*, which is wrong in the
  federated case — the viewport is kilianmc.com's, not the card's. **Container queries
  ask about the space the card actually has**, so one component serves both mounts with
  no mount-specific branching.
- Design tokens (surface colours, border tones, the shadow scale) go on the
  **`.ct-app` root**, not `:root` — see the federated-mount rules above.

## Session player invariants (PR #15a onward)

Recorded here because each is a specific bug that a naive implementation ships:

- `requestAnimationFrame` drives the display; **never `setInterval` counting**.
- `performance.now()` for elapsed math (monotonic, NTP-proof); `Date.now()` only for
  persistence.
- Advance **while** overdue, not once — a backgrounded phone can skip several phases of
  a 60 s repeater set.
- **Suppress missed cues**: if more than one phase elapsed while hidden, fire only the
  cue for the phase landed on and offer a resync. Four beeps at once is the classic bug.
- A `setTimeout` armed to the next boundary as a backup for throttled rAF.
- **Visual is the primary cue channel** (full-viewport colour + huge countdown) — a
  muted phone across the room still has to work. Audio is synthesized
  `OscillatorNode`s, `AudioContext` created **inside** the Start click and `resume()`d
  on `visibilitychange`. The **iOS hardware silent switch mutes Web Audio with no
  workaround**, hence a "Test sound" button before the session starts.
- The plan generator (`server/app/domain/planner/`) is a **pure module with no DB
  access** — no clock, no RNG, no I/O; dates are passed in. Enforced by a ruff
  banned-import rule. That purity is what makes `POST /api/plans/preview` (blueprint
  without writing) possible, which is what makes the demo mount interactive.

### Screen Wake Lock — a user-owned TOGGLE, and a progressive enhancement

Kilian did not ask for this as an automatic behaviour and pushed back on it, so keep it
in its place. **The only honest justification: it saves unlocking a phone with chalky
hands between sets.** Nice-to-have, nothing more. A typical session is roughly **45–90
minutes**; do not design around a "keep the screen on for hours" premise.

**It is exposed as a visible "Keep screen on" toggle in the session player, and is
NEVER acquired silently.** Kilian's reasoning, worth keeping verbatim because it is the
part that gets optimised away: *"as a user you like to be in control, or feel like you
are given the choice."*

Requirements for PR #15a:

- **A visible switch in the session player that the user owns.** Label it plainly —
  "Keep screen on". Acquisition is **conditional on that toggle**; there is no
  "acquire on session start" behaviour.
- **HIDE the toggle entirely when `navigator.wakeLock` is unavailable** — notably
  **Firefox on Android, which is Kilian's own browser**. Not disabled-but-visible: a
  control that promises something impossible is worse than no control. **No error, no
  warning toast, no "unsupported browser" message** either — the app must simply work
  with the OS screen timeout. **Verify, don't assume**: check the real behaviour on the
  real browser rather than trusting a support table.
- **Persist the choice in `localStorage`** under the **`ct:`** namespace (e.g.
  `ct:keepScreenOn`) — remember that in the federated mount that IS the shell's origin
  storage.
- **THE TOGGLE MUST REFLECT REAL STATE, NOT INTENT.** The browser/OS **silently releases
  a wake lock when the tab is backgrounded**. So: **re-acquire on `visibilitychange`
  while the switch is on**, and **drive the UI from the sentinel's actual `released`
  state**, not from the boolean the user clicked. A switch reading "on" over a released
  lock is a lie the user only discovers when the screen dies mid-set.
- **Release on session finish, on abort, and on unmount.** Never leak a lock past the
  run, and never hold one while the user is merely browsing the app.
- `request()` can reject (low battery, OS policy) and the OS can release the sentinel at
  any time. Handle both as normal, expected outcomes — reflect them in the toggle's
  state, don't treat them as errors.
- **Never load-bearing.** The clock derives from **wall-clock time** and **resyncs on
  `visibilitychange`** whether or not a lock was ever acquired — because mobile JS timers
  throttle when backgrounded, full stop. **That correctness work is required with or
  without a wake lock**, so the lock can be absent, refused, toggled off, or silently
  released and the session is still correct. Never let a timing behaviour depend on
  holding one.
- **Also broken in installed PWAs until iOS 18.4** — detect standalone-mode iOS < 18.4
  and treat it as unavailable (so the toggle hides there too). A hidden muted looping
  `<video>` is an acceptable fallback *only* if it proves worth the battery cost;
  defaulting to no wake lock is fine.
