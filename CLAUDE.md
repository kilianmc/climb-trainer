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
api/index.py          thin Vercel entrypoint: sys.path.insert + `from server.app import app`
server/               the FastAPI application actually lives here
web/                  the Vite SPA, built to web/dist
tests/                pytest (backend)
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

### Never register a service worker from `remote.tsx`

A service worker registered from the federated entry would be **scoped to
kilianmc.com** and start intercepting the production portfolio's requests. Low
likelihood, severe blast radius. **SW registration lives in `main.tsx` only** —
PR #7 (PWA) must keep it there.

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
`react-dom/client` resolve from the one instance, modern `build.target` (MF needs
top-level `await`), and `Access-Control-Allow-Origin: *` on `/remoteEntry.js` +
`/assets/*` only.

`VITE_TRAINER_REMOTE_URL` in the shell must point at a **stable alias** (git-branch
alias or custom domain), never a deployment-specific URL — Hobby prunes deployments
after 30 days.

### TypeScript stays on 6.x

`typescript-eslint`'s peer range is **`>=4.8.4 <6.1.0`**. Upgrading to TypeScript 7
would silently drop **type-aware linting**, and with it
`@typescript-eslint/no-floating-promises` and `no-misused-promises` — the two rules an
app built on optimistic writes and a background outbox needs most. The loss is silent:
the lint still passes, it just stops checking.

**Decision taken 2026-08-12: stay on TS 6.x. Not planned to change.** Revisit only
when `typescript-eslint` widens its peer range, and re-verify both rules still fire.

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
- `GET /api/library?v=<buildId>` is user-independent and immutable per deploy — serve
  `public, s-maxage=31536000, immutable` with `staleTime: Infinity`. Zero DB time and
  zero invocations after the first request per deploy.
- Pool config: `pool_pre_ping=True`, `pool_recycle=300` (matches the 5-min
  autosuspend), `pool_size=2`, and psycopg3 with
  `connect_args={"prepare_threshold": None}` — server-side prepares are what break
  intermittently behind a transaction-mode pooler.
- **Two connection strings**: the pooled `-pooler` endpoint for the app, the **direct**
  endpoint for Alembic (DDL and `CREATE TYPE` need a real session).

### Migrations run out-of-band

- Alembic runs via a **manual `workflow_dispatch`** job with `environment: production`
  (approval required), against the **direct** URL. **Never automatic on push** — a
  migration must never race a deploy, and deploys here are automatic while migrations
  are not.
- **Expand → deploy → contract**, always, for the same reason.
- In FastAPI's `lifespan`, only **READ** `alembic_version` and **warn** on mismatch.
  Never migrate at startup.

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
  middleware rejecting every mutating method for demo tokens. Hard **rate-limited**
  (rate limiting lives in a Postgres `rate_limit` table — there are no background
  workers). A route-enumeration test asserts **every** mutating route 403s for a demo
  token. No real user data is ever seeded into demo.
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

Two long-lived branches: **`dev`** (integration, the default branch) and **`main`**
(production, `climb.kilianmc.com`). **All feature PRs target `dev`.** `main` receives
only `dev`→`main` promotion PRs, merged by Kilian after he has tested the dev deploy.
Conventional Commits (`feat:`, `fix:`, `chore:`, `test:`, `docs:`); branches mirror
the type (`feat/…`, `chore/…`).

---

## Local development

Two processes. The API on 8000, the SPA on 5173 with Vite proxying `/api` to it:

```bash
# terminal 1 — API
uv run uvicorn server.app:app --port 8000 --reload

# terminal 2 — SPA (Vite proxies /api -> 127.0.0.1:8000)
npm --prefix web run dev
```

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

**One command, and it is the same eight checks CI runs:**

```bash
npm run check          # == check:web && check:server
```

Or the halves / individual checks:

```bash
npm run check:web      # format:check -> lint -> typecheck -> test -> build
npm run check:server   # ruff check -> ruff format --check -> pytest

npm --prefix web run format:check   # Prettier
npm --prefix web run lint           # ESLint (type-aware — see the TS 6.x note)
npm --prefix web run typecheck      # tsc -b (strict)
npm --prefix web run test           # Vitest once
npm --prefix web run build
uv run ruff check .
uv run ruff format --check .
CORS_ORIGINS=http://localhost:5173 uv run pytest -q
```

**Batch your edits and run `npm run check` once at the end**, not once per file.

**CI has three required jobs: `web`, `server`, and `secrets`** (gitleaks over full
history). Kilian's call: **require all three** rather than collapsing them into a single
`lint-build` gate as the other repos do — three named checks say *what* broke on the PR
page, and a leaked-secret failure should never be indistinguishable from a lint failure.
If you read "one required check named `lint-build`" in the original plan, that wording
is superseded.

`npm run check` covers `web` + `server`. The `secrets` job is CI-only (gitleaks isn't a
project dependency) — so the local gate is 8 checks and CI is 9. Don't try to fake the
third locally; just never commit a secret.

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
