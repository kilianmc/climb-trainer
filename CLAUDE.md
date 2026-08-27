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

## Index — find the rule before you write the code

**Pure pointers: a trigger, then the headings to read** — anchored by heading text, never by
line number, and read back both ways by `tests/test_claude_md_claims.py`: a quote must resolve to
a real heading, and a section nothing points at is a section nobody finds. Two conventions:

- **An env var is explained in exactly ONE place; every other mention is a bare reference or a
  command, with no explanation attached.** `CT_TEST_DATABASE_URL` → "Local Postgres for the test
  suite"; `DATABASE_URL` and `DATABASE_URL_UNPOOLED` → "Database and compute budget"; the rest
  → `.env.example`.
- **If a claim can be executed, it must not be prose** → "⚠️ Prose is capped, and an executable
  claim must not be prose".

**Adding or running a migration, or anything that could destroy production user rows** —
"Migrations run out-of-band" · "How to actually run one" · "⚠️ Three traps, all paid for on the
day it first ran" · "⚠️ Production data durability — real accounts, no undo" · "SQLite is
disqualified for tests" · "Branch model".

**Touching auth, tokens or the route guard** — "Security rules" · "Auth implementation — where
each piece lives" · "Auth UI — the client half of the contract" · "Registration is
invite-gated" · "⚠️ Minting an invite is a LOCAL command, and must never become a workflow" ·
"Local accounts, and the two things that are NOT `server/seed.py`" · "🔒 TODO — the end-to-end
security verification pass", whose private-file half is now issue #71.

**Changing the federated mount, the router or the two entries** — "Routing: one tree, two
histories" · "Module Federation shared singletons — the silent one" · "In the federated mount,
`localStorage` is the SHELL's storage" · "Never register a service worker from `remote.tsx`" ·
"API base: resolve from `import.meta.url` + guard the content-type".

**Touching `vercel.json`, rewrites, headers or the API client** — "Deployment traps" ·
"Security response headers" · "API base: resolve from `import.meta.url` + guard the
content-type" · "`.env` is loaded for you — but only outside Vercel".

**Moving a file, or adding a `server/` subpackage** — "Repo layout — do not rearrange it".

**Writing to the database, or adding or changing an endpoint** — "Neon bills AWAKE TIME, not
writes" · "Two write tiers" · "The other compute rules" · "Engine config — the omissions are the
point" · "Injection defence and input minimisation (OWASP)" · "OpenAPI codegen — the generated
types are COMMITTED" · "Validate at the edge with Pydantic".

**⚠️ Touching `GET /api/library`, or adding ANY field to it** — "⚠️ `/api/library` is
USER-INDEPENDENT, permanently" · "The other compute rules".

**Touching the domain schema, body metrics, or anything the plan generator says to the user** —
"⚠️ The app never recommends losing weight" · "The domain schema — the shapes worth knowing
before you query it" · "⚠️ The free-text inventory — ELEVEN fields, and three of them get
forgotten".

**Onboarding, the profile, the completion bar, a MUTATION or the query cache** — "Onboarding
and the profile".

**Dependencies, versions and CI** — "Dependency policy" · "TypeScript stays on 6.x" · "ESLint
10 rests on a forced jsx-a11y peer" · "`.github/dependabot.yml`" · "⚠️ Pinned actions
Dependabot can never bump" · "Quality gate" · "Versioning".

**Styling, the landing page or anything visual** — "UI design direction" · "Glassmorphism:
considered and REJECTED" · "Accessibility is part of the design, not a later pass" · "The
reading measure is a GRID COLUMN" · "Landing imagery — self-hosted, generated out-of-band, and
URL-resolved at runtime" · "Container queries, not media queries" · "⚠️ The nav's thresholds
are MEASUREMENTS, not breakpoints" · "Light and dark: the `data-theme` override" · "PWA — only
the decisions a reader would otherwise reverse".

**Running the app locally, or a blank page that is not your code** — "Local development" ·
"Local Postgres for the test suite" · "⚠️ A dev server and the gate at the same time can blank
every route" · "`.env` is loaded for you — but only outside Vercel".

**Writing a test, or prose, or a comment — or closing a PR** — "Testing policy" · "⚠️ A guard
test must be SHOWN to fail before it is trusted" · "⚠️ A class name in markup with no CSS fails
SILENTLY" · "⚠️ Prose is capped, and an executable claim must not be prose".

**The plan generator, `POST /api/plans/preview`, persisting a plan or `GET /api/plans/active`** —
"The plan generator" · "Persisting a plan".

**Building the session player** — "Session player invariants" · "Screen Wake Lock — a
user-owned TOGGLE, and a progressive enhancement".

### What lives outside this file — the master map

**`CLAUDE.md` owns WHY and the rule; `README.md` owns WHAT and the outcome.** Where both would
say the same thing this file wins and README links to it, because this is the file an agent is
told to read before editing.

- **`README.md`**, by section: *What it does* · *Stack* (the version list, and its only home) ·
  *Design direction* (the visual pitch — bento, opaque surfaces, why not glassmorphism) · *Repo
  layout* (a short orienting tree; the load-bearing one is here) · *Getting started* (clone to
  running, commands only) · *Tests and quality gate* (the three commands and the codegen step) ·
  *Signing in* · *Dual mount* · *Deployment*.
- **Module docstrings, which carry their own reasoning in more detail than this file does** —
  `server/db.py` (engine and session wiring), `server/auth/*.py` (one per auth concern),
  `server/domain/grades.py` (the ordinal ladder), `web/src/styles/_layout.scss` (the reading
  measure as a grid column). `web/src/profile/api.ts` and `server/plans/routes.py` carry the
  library-source citations their claims rest on.
- **Kilian's private notes** (local only, never in this repo) — the approved delivery plan and
  the unshipped schema/generator design; a per-project memory covering live infrastructure,
  deployment history and process lessons; plus topic notes on the signup-gating decision and the
  landing redesign. Ask him if you need the plan for an unshipped PR; nothing in them is required
  to work inside this repo.
- **Issue #71** — moving the security control map, the thresholds and the infra topology into a
  private file. Anything moved was **already public**, so it must be rotated, not merely moved.
- **Registers that are files rather than prose** — `tests/comment_budget_allowlist.toml` (every
  over-cap comment and the reason its length buys) and `.github/pull_request_template.md` (the
  post-PR freshness receipt). Both are explained in "⚠️ Prose is capped, and an executable claim
  must not be prose".

## Repo layout — do not rearrange it

Spike S0 verified this exact layout end-to-end on a real deployment. It is load-bearing.
**The tree itself lives in [`README.md`](README.md), *Repo layout* — one copy, there.** What
follows is only the part that is a rule rather than a description.

`server/` being importable from `api/index.py` was genuinely uncertain before S0 — it
works because `api/index.py` inserts the deployment root onto `sys.path`. Don't move
the app into `api/`; don't delete that `sys.path` line.

⚠️ **A new `server/` subpackage must be added to `[tool.setuptools] packages` in
`pyproject.toml` in the same commit.** That list is written out — there is no autodiscovery
and no `[build-system]` table to supply one — so an omitted subpackage is absent from the
installed distribution while still importing perfectly from the repo root. `server/library/`
is the newest entry.

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

⚠️ **The one build-time value this repo injects is deliberately NOT a `VITE_*` var.**
`__BUILD_ID__` — the `define` in `web/vite.config.ts`, read through `web/src/buildId.ts` —
keys `GET /api/library?v=…`. It goes through `define` precisely so that **nothing has to be
configured in the Vercel project** for a deploy to bust that cache: a build id that depends on
somebody remembering to set an env var is a build id that eventually stops changing, and a
year-long `immutable` then pins a stale exercise library. The value is a public deploy
identifier **by design** — it ships to every visitor and that is fine, which is why the
`VITE_*` rule above does not apply to it. **Locally it is a fresh timestamp, not the git SHA**:
a SHA does not move when the working tree does, so an uncommitted content edit would be served
out of a cache that believes it is immutable — the one case that actually bites in development.

### 5. Function region and Neon region must match

S0's function ran in `iad1` (US East) while serving Barcelona. **Neon's region is
fixed at project creation** — pick the EU region and pin the function region to match.

### 6. Never reflect raw request headers

Vercel injects `x-vercel-oidc-token` on **every** request. It is a real, short-lived
credential. Any diagnostic endpoint must use an **allowlist** of header names. S0 hit
this while dumping `x-vercel-*` for debugging.

### 7. `functions."api/index.py".maxDuration` is pinned, and it is a CORRECTNESS setting

```jsonc
"functions": { "api/index.py": { "maxDuration": 20 } }
```

**Not a cost control — it is what makes the client's 30 s auth abort an *outer* bound.** Left
unpinned this is Vercel's default, and under **Fluid compute (default for new projects since
2025) that is 300 s**. The refresh endpoint is a sync `def` that commits its rotation *before*
it answers, so a client abort landing inside the server's window leaves the successor refresh
token live on the server and held by nobody — see "⚠️ TWO deadlines on the auth path" under
"Auth UI — the client half of the contract" for the full mechanism. 20 s is always accepted;
Hobby's configurable maximum is 60 s even without Fluid.

**Deleting or raising this block re-opens that hole silently** — green gate, no symptom, until a
cold path runs long. It bounds the `/api/*` function only: migrations and the seed run
out-of-band in Actions, never in this function, so nothing about them is affected.

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

### Routing: one tree, two histories

`src/router.tsx` builds the router from a passed-in history and is the only place router
or Query defaults live. `main.tsx` gives it `createBrowserHistory`, `remote.tsx`
`createRemoteHistory()`. The history is the *only* difference between the mounts.

- **The federated mount renders ABSOLUTE hrefs (decided for PR #5, issue #16).**
  `createMemoryHistory`'s `createHref` is the identity function, so `<Link to="/plan">`
  emitted `href="/plan"`, which the browser resolves against the **host** document —
  cmd-click, middle-click and "copy link address" left the viewer for `kilianmc.com/plan`,
  a 404 on the portfolio. `src/remoteHistory.ts` therefore overrides `createHref` with
  `STANDALONE_ORIGIN` (`https://climb.kilianmc.com`), the single place in runtime code that
  origin is written — deliberately a **constant**, not `import.meta.url` as the API base
  is: a link the user opens outside the shell must land on the canonical public app, not on
  whichever ephemeral deployment served the chunk. Note the consequence — a cmd-click from
  a *dev* federated mount opens *production*, with production data once auth lands (PR #6).
  Only `<Link>` reads `createHref`, so left-clicks are still intercepted and
  navigate in place. **The standalone entry is unchanged — relative hrefs there**; both
  arms are asserted (`remote.guard.test.tsx`, `router.test.tsx`). `createMemoryHistory`
  accepts no `createHref` option, hence the assignment; never *spread* a history object,
  whose `location`/`length` getters a copy would freeze.

- **`src/routeTree.gen.ts` is COMMITTED, and must stay committed.** `web/vitest.config.ts`
  **replaces** `web/vite.config.ts` rather than merging it, so the router plugin never
  runs under Vitest and cannot regenerate the tree. Verified by deleting it and watching
  `vitest` fail with no regeneration. It is excluded from ESLint (`ignores`) and Prettier
  (`.prettierignore`) — it ships without semicolons, so `format:check` fails on it
  otherwise. Never hand-edit it. **CI asserts the file exists (`git ls-files
  --error-unmatch`) and then runs `git diff --exit-code -- src/routeTree.gen.ts` after the
  build**, so a stale committed tree fails the `web` job instead of being silently rewritten
  (regeneration is byte-identical). The existence step is not decoration: `git diff
  --exit-code` exits **0** on a pathspec matching nothing, so a rename would leave the check
  green forever. It is **CI-only on purpose** — see the Quality gate section.
- **⚠️ A lazy leaf must be named `<route>.lazy.tsx`.** `createLazyFileRoute` inside a
  plain `plan.tsx` **still builds, emits no warning, and is bundled EAGERLY** — no separate
  chunk appears. Only the `.lazy.tsx` filename makes the generator emit
  `.lazy(() => import(…))`. Renaming one of those files deletes its code-splitting, and
  `format:check`, `lint`, `typecheck` and `build` all stay green — the build even **rewrites
  the source**, swapping `createLazyFileRoute` for `createFileRoute` to match the new
  filename, so afterwards nothing in the file hints it was ever lazy. What catches it is
  `test`, now that the gate builds first: against a freshly generated tree the assertion
  below fails with `expected [Function Plan] to be undefined`. Against a *stale* committed
  tree the same rename fails loudly for a different reason — the tree still holds
  `import('./routes/_authed/plan.lazy')`, which Vite cannot resolve — 14 transform errors,
  loud but pointing at the wrong thing. (The other valid shape is `autoCodeSplitting: true`
  with plain `createFileRoute`; the two must not be mixed.)
  **`web/src/routeTree.lazy.test.ts` asserts it** via router state — an unloaded
  `options.component` — rather than by reading `dist/`, because `vitest` also runs on its
  own (a watch run, a clean checkout with no `dist/`) and a `dist`-reading test would skip
  itself there, i.e. be vacuous in the one situation it is most likely to be run. Note
  `routeTree` is a module singleton whose route objects `.lazy()` mutates in place, so that
  file needs `resetModules` + a dynamic import to stay order-independent.
- **`defaultPreloadStaleTime: 0`** because Query is the single source of staleness truth.
  Raising it gives the router a second cache with its own expiry and the two disagree.
- **No query-cache `localStorage` persistence.** In the federated mount that storage is
  the SHELL's, so persisted server responses outlive both the session and the user — see
  §"In the federated mount, `localStorage` is the SHELL's storage". Auth landing did not
  change this. It does **not** constrain the outbox, which holds only the current user's
  unsent writes and drains on flush. Do not leave a persister half-built.
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
  document reset, which must never reach the shell), and `styles/update-bar.scss` only from
  `ui/UpdateBar.tsx`, which only `main.tsx` imports. **Since PR #7 this is asserted on the BUILT
  stylesheet the shell loads, by `src/distContract.test.ts`** — not on the sources. The
  distinction is the whole point and was measured: a per-source-file scan with per-file
  exemptions stayed green while one added line, `@use 'global';` in `app.scss`, emitted
  `:root{…}` and `body{…}` straight into the remote's CSS. The rule is about *which bundle a
  declaration lands in*, and `@use` is what decides that. `styles/designGuard.test.ts` is the
  weaker complement, kept for the reach the bundle check cannot have: a `backdrop-filter` in a
  partial nothing `@use`s yet, and an inline `position: 'fixed'` in a component, which never
  becomes CSS at all.

### Never register a service worker from `remote.tsx`

A service worker registered from the federated entry would be **scoped to
kilianmc.com** and start intercepting the production portfolio's requests. Low
likelihood, severe blast radius. **SW registration lives in `main.tsx` only.**

It constrains *component placement*, not just entry files: `pwa/updatePrompt.ts` calls
`registerSW` at module scope, so **anything that imports it — `ui/UpdateBar.tsx` included —
may be rendered from `main.tsx` and from nowhere in the route tree**, which `remote.tsx`
shares. Putting the update bar in `__root.tsx` is the realistic mistake; it looks like
chrome, and chrome lives in the root route.

Three tests hold the line, and they need each other:

- `remote.guard.test.tsx` is the negative arm. Its service-worker assertion passes on an empty
  set, so it also carries a positive control that imports **`virtual:pwa-register` itself** and
  proves the spy sees the registration.
- `virtual:pwa-register` only exists while `vite-plugin-pwa` is running, and `vitest.config.ts`
  **replaces** `vite.config.ts`, so tests resolve it through a `resolve.alias` to
  `src/test/pwaRegisterStub.ts`. **The stub copies upstream's deferral condition verbatim**
  (`workbox-window/src/Workbox.ts:113`: `if (!immediate && document.readyState !== 'complete')
  await load`) — keep it a copy of the condition, not a summary. An unconditional stub made two
  "positive controls" assert a deferral production does not have.
- `main.pwa.test.tsx` is the positive arm: without it, deleting the PWA wiring entirely leaves
  the negative guard green. It can only assert *that* a registration happened — the URL the stub
  reports is the stub's, so the plugin options and the emitted `sw.js` are asserted by
  `pwaContract.test.ts` and `distContract.test.ts` instead.

`web/src/remote.guard.test.tsx` enforces this plus the `localStorage` rules below. It shipped
**vacuous** and had to be hardened; four jsdom facts caused that, and all four will catch the
next person out too:

- **`document.readyState` is already `'complete'` when a test runs**, so a listener added
  during `render()` never fires — and upstream's condition above means the *real* registration
  is therefore **synchronous** under jsdom and never takes the `load` path at all. The test
  dispatches `load` itself anyway, for a different risk: a **hand-rolled**
  `window.addEventListener('load', … register …)` in a module both entries import, which is
  still plausible and still invisible without the dispatch. Keep the dispatch.
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
- **Persist no query cache** — in either scope, and for this same reason.

Also scope the remote's CSS under a single **`.ct-app`** root, with design tokens as
custom properties **on that element** — not on `:root`/`body`. **A root-level error,
not-found or pending render replaces the layout and takes that element with it**, so all
three status renders in `ui/status.tsx` re-establish `.ct-app` themselves — and skip it when
`RootLayout`'s `CtAppScope` says they are already inside one, because nesting that element
insets the layout twice (issue #15; `rootStatusScope.test.tsx` asserts both directions).
Wrapping only `errorComponent` was the half fix: the pending path escapes too, via the
ROOT route's `pendingComponent ?? defaultPendingComponent`, which the router also uses for
its two root-level Suspense fallbacks. `fund-dashboard` gets
away with a global reset because it lives inside a full-viewport overlay; a
full-screen session player will fight the shell's `ProjectViewer` chrome.

### Module Federation shared singletons — the silent one

With `singleton: true` and no explicit `strictVersion`, MF defaults to
`strictVersion: false` (confirmed in `@module-federation/runtime-core@2.7.0`,
`dist/utils/share.js` — the shareConfig defaults set `strictVersion: false`, and the
mismatch branch is `if (shareConfig.strictVersion) error(msg); else warn(msg)`). A React
version mismatch is therefore **only a console warning** — then MF **silently hoists the
highest React** and hands it to code compiled against the other version. Failures surface
later and look completely unrelated.

**Enforcement follows bootstrap order, not host vs. remote** (verified by experiment): the
container that boots **first, with an empty shared-module cache**, throws on a range it
cannot satisfy, and the throw rejects the entry wrapper so the app entry never imports —
blank page. A container initialising **after** the cache is seeded only logs
`Failed to bridge external shared module`, one line per shared key, and **mounts anyway**.
Our exposure is therefore **standalone**: served on our own origin we boot first, so a
range our installed React cannot satisfy blanks our own deployment. Federated into the
shell, the shell boots first, so the same mistake only logs. Note `strictVersion` is
**inert without `singleton: true`**. Widen the range *before* any React major or canary
bump, then re-narrow.

The portfolio contract is `^19.0.0` + `strictVersion: true`, and `web/vite.config.ts`
matches it on all four shares.

**A working mount proves nothing — the console is the only signal that the contract holds.**
Check it at **initial page LOAD**, not on card open: a production build logs bridge failures
during eager remote init. Two rules for doing that honestly:

- **Prove the detector non-vacuous first.** Forcing our `requiredVersion` to `^18.0.0`
  against a production build of the shell logs `Failed to bridge external shared module`
  **while the remote still mounts and looks correct**. That control forces an unsatisfiable
  *range* while both sides run the same React, so the console is the only place it can show
  — which is also why **"React instances: 1" is a vacuous metric**: a failed remote never
  creates a renderer, so it reads 1 in the broken arm too.
- **Grep for the string; never assert a count** — the count is arm-dependent, and that
  caused a three-way disagreement once. Against a **production** build the control is four
  lines, one per shared key (`react`, `react/jsx-runtime`, `react-dom`,
  `react-dom/client`), all at initial load. Against the shell's **dev server** the same
  control splits into two at load (wrapped in a `#RUNTIME-015` container-init error) plus
  four at first card open, because the dev server materializes a share on first import
  rather than at bootstrap.

Preview URLs stay SSO-gated, so **production is the only arm** there is for a cross-origin
console or header check against a real deployment.

Remote contract (mirrors `ai-portfolio-project1/vite.config.js`):
`filename: 'remoteEntry.js'`, `dts: false`, react/react-dom singletons at `^19.0.0`
with `strictVersion: true` to match the host, **plus scoped `'react/'` and
`'react-dom/'` shares** so `react/jsx-runtime` and `react-dom/client` resolve from the
one instance, and `Access-Control-Allow-Origin: *` on
`/remoteEntry.js` + `/assets/*` only — see the two reasons in the CSP section.

**No explicit `build.target` — corrected 2026-08-14.** Earlier wording here required a
"modern `build.target`" on the grounds that MF needs top-level `await`. **That is false on
Vite 8**, whose default target (`baseline-widely-available`, i.e. chrome111+) already
supports it: removing the option leaves the top-level `await` in the output untouched, with
no warning. `ai-portfolio-project1` pins `chrome89` because it predates that default, so
copying it here would only **lower** our baseline. Do not re-add it "for MF".

**`VITE_CLIMB_REMOTE_URL`** in the shell (PR #5's name for it) must point at a **stable
alias** (git-branch alias or custom domain), never a deployment-specific URL — Hobby
prunes deployments after 30 days.

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

### OpenAPI codegen — the generated types are COMMITTED

`web/src/api/schema.ts` is written by `npm run codegen:api` and **committed**, exactly as
`src/routeTree.gen.ts` is. Deferred from PR #8 (no endpoints existed to generate from) and
landed with PR #9's first two.

```bash
npm run codegen:api   # uv run python -m server.openapi_schema | node web/scripts/gen-api-types.mjs
```

- **Committed, not generated in CI, and the reason is toolchain reach.** The document comes
  from Python and the types from Node; the `web` CI job and Vercel's SPA build have Node and
  **no Python**, so nothing in that half of the build can produce the file. Generating it in
  the `server` job instead would need `web/node_modules`, which that job does not install.
- **Piped, so there is exactly ONE generated artifact.** Writing the OpenAPI JSON to disk
  first would commit a second file that says the same thing and can disagree with it.
- **TWO digests in the header, and one of them alone was not enough.**
  `openapi-sha256` is the digest of the exact bytes `server/openapi_schema.py` printed —
  the **input** — and catches "I added an endpoint and forgot to regenerate".
  `types-sha256` is the digest of the generated body below the header — the **output** —
  and catches a hand-edit. The first shipped alone and was one-sided: changing
  `sessions_per_week: number` to `number | null` inside the committed file left the digest,
  `tsc`, ESLint and the whole gate green while the client believed a nullability the API
  does not have. "Do not edit this file" is a convention; the second digest is the guard.
  Both are recomputed by `tests/test_vocabulary_contract.py`, so both failures land in the
  **local** gate with no Node and no network, and both have been watched to fail. It is
  tamper-EVIDENT, not tamper-proof — an editor who also recomputes the digest gets through,
  exactly as with the committed route tree.
  `info.version` is normalised out of the hashed document, or every `npm run version:dev`
  would invalidate it over a string the types do not contain.
- **⚠️ A FastAPI or Pydantic bump fails this test, and Dependabot CANNOT fix it.** Those
  libraries build `app.openapi()`, so a version bump can change the document (a new
  `openapi` version string, a different `anyOf` shape, a renamed validation-error schema)
  without a line of this repo changing. The fix is `npm run codegen:api`, which needs Python
  **and** `web/node_modules` in one job — which no CI job has, by the same argument that
  makes the types committed. **Expect red dependency PRs on those two packages** and treat
  a regenerate-and-commit as part of reviewing them. Do not "fix" it by loosening the digest.
- **`openapi-typescript` needs a forced `typescript` peer**, same idiom and same scoping as
  the jsx-a11y override: 7.13.0 peers `typescript@^5.x` and this repo is on 6.x, so
  `npm install` fails `ERESOLVE` without it. Verified before forcing it — it uses the
  compiler's factory/printer API, which TS 6 (the last JS release) still exposes in full,
  and it generates, formats, typechecks and lints clean. **Not `--legacy-peer-deps`**, which
  would let unrelated peer conflicts through unnoticed. Delete the override when upstream
  publishes a `^6` peer.
- **The output is Prettier-formatted by the script**, via `resolveConfig` — `format()` does
  **not** read `.prettierrc.json` on its own, and without that the file keeps the
  generator's double quotes and 80-column wrapping and `format:check` fails on a file nobody
  is allowed to edit. That is why it needs no `.prettierignore` entry, unlike the route tree.
- **`web/src/api/vocabularies.ts` is GONE.** It mirrored the six closed vocabularies by hand
  until codegen existed. Its contract test was re-pointed at the generated file rather than
  deleted — see the note on `GET /api/vocabulary`'s `enums` field for what had to be true
  first.

### PWA — only the decisions a reader would otherwise reverse

`vite-plugin-pwa` v1, `generateSW`, configured in `web/vite.config.ts` **after** `federation()`.
The registration lives in `main.tsx` only — see the service-worker rule above for the two tests
that enforce it. What follows is the reasoning that is not visible in the config:

- **`registerType: 'prompt'`, not `autoUpdate`.** `autoUpdate` calls `skipWaiting`, which
  **deletes the outdated precache as the new worker activates** — so a tab left open across a
  deploy then 404s on the next lazily-loaded route chunk, and later it could swap code under a
  session player mid-set. The visitor takes the update, via `ui/UpdateBar.tsx`.
- **`injectRegister: null`.** We register from `main.tsx`, and the alternative is blocked
  anyway: the production document CSP is `script-src 'self'` with no nonce, so the `'inline'`
  strategy's inline `<script>` would never execute. `null` also means the plugin injects nothing
  but `<link rel="manifest">`, which is why `index.html`'s two scheme-scoped
  `<meta name="theme-color">` tags survive the build.
- **`workbox.inlineWorkboxRuntime: true`** — one `sw.js` rather than `sw.js` plus an unhashed
  `workbox-*.js`, so there is one fewer root-level file for the SPA rewrite to mis-serve. Note
  it is a *workbox-build* option; at the plugin's top level it is a type error.
- **`navigateFallbackDenylist: [/^\/api\//]` is not optional.** `navigateFallback` otherwise
  answers an `/api/*` navigation with `index.html`, which is deployment trap 2 recreated inside
  the browser: `apiFetch` gets `200 text/html` and throws `NotJsonError` far from the cause.
- **No `runtimeCaching` for `/api`, ever.** Authenticated JSON in Cache Storage is written to
  disk, is not scoped to a session, and **survives logout** — nothing in the app clears it. The
  service worker precaches the app shell and nothing else.
- **`globPatterns` is explicit and narrower than the default**, because the manifest icons and
  `includeAssets` are added by the plugin with their own revisions; globbing them too offers
  workbox two entries for one URL. `build.sourcemap` is on and `.map` is deliberately excluded.
  The precache covers the app shell plus `remoteEntry.js` and the MF virtual chunks; the build
  prints the current entry count and size, so it is not repeated here. ⚠️ **Those are NOT dead weight and must not be excluded**: `dist/index.html`
  `modulepreload`s every one of them, because the MF plugin routes the *standalone* app's own React
  through the share scope. Precaching them is what makes the standalone app work offline at all.
  (An earlier note here said the standalone app never loads `remoteEntry.js`. It was wrong.)
- **The four decisions above are asserted, not just recorded.** `src/pwaContract.test.ts` reads
  `vite.config.ts` off disk (modelled on `mf-contract.test.ts`) and fails on `autoUpdate`, on a
  non-`null` `injectRegister`, on a missing `/api` denylist, and on the *presence of the token*
  `runtimeCaching` anywhere. Before it existed, adding `runtimeCaching` for `/api` passed the whole
  gate. It strips comments first, because this config explains those rules in prose.
- **Icons are generated on demand and committed.** `npm --prefix web run generate:icons` runs
  **`npx --yes @vite-pwa/assets-generator@1.0.2`** over `web/public/mark.svg` (`minimal-2023`
  preset). It is **not** wired into the Vite build: no image processing on Vercel, and committed
  PNGs are deterministic (verified — a re-run is byte-identical). The manifest's `icons` array is
  hand-written against the filenames actually on disk — check them, do not assume the preset's
  naming.
  - ⚠️ **The generator is deliberately NOT a devDependency**, and `pwa-assets.config.js` is
    deliberately plain JS with a **string** preset name and no imports (so `tsc -b` never has to
    resolve the package). It drags in `sharp <0.35.0` — four high-severity libvips CVEs,
    GHSA-f88m-g3jw-g9cj — and ~200 packages that `npm ci` would install on **every Vercel
    production build**, for a script that runs when the logo changes. Dependabot alerts cover
    devDependencies and this repo is at zero; `npm audit` is 0 with the pinned-`npx` form. Do not
    "fix" the config file by adding the import back.
- **The update prompt must be dismissable, and its Reload needs an explicit fallback.** Both are
  bugs that were shipped and measured, both recorded in `pwa/updatePrompt.ts`: the bar is `fixed`
  at the bottom, so with no dismiss it permanently covered the bottom-anchored primary action; and
  prompt mode's reload is gated on `event.isUpdate`, which is false on an **uncontrolled** client
  (first visit, hard reload), where tapping Reload otherwise activates the worker and does nothing
  visible. `global.scss` reserves the bar's height with `body:has(.ct-update-bar__panel)`.
- **No `orientation` in the manifest.** The app is used in landscape on a bouldering mat as
  often as in portrait.
- **`vite preview` proxies `/api` too**, mirroring `server`. Production serves `/api` from this
  origin, so without the proxy preview 404s every auth call — and preview is the only place the
  real build meets the real production headers.

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
- **`GET /api/library?v=<buildId>` — implemented as prescribed** (`server/library/routes.py`):
  `public, s-maxage=31536000, immutable` with `staleTime: Infinity`, so the whole library
  costs one origin read per deploy and then no DB time and no invocations at all. `?v=` is the
  deploy id from `web/src/buildId.ts`, and the parameter is **accepted and ignored** — a
  response that varied on it would give the cache one body per build ever made. Its only job
  is that a content edit ships a *new URL* rather than waiting out a year of `immutable`.
  **It stays AUTHENTICATED, and that is not theatre now that the body is publicly cacheable.**
  Auth gates who can cause a cache **MISS**, and a miss is an origin read and therefore a Neon
  wake — so an unauthenticated library endpoint would hand a bot exactly the wake that
  `POST /api/auth/demo` was rewritten to remove. It is deliberately not in `PUBLIC_ROUTES`.
  ⚠️ `GET /api/vocabulary` deliberately keeps `private, max-age=3600`. **The two rules differ
  on purpose** — see that endpoint's own bullet under "Onboarding and the profile" for why it
  has no business in a shared cache; do not "harmonise" them.
- **Two connection strings, and this bullet is their one explanation** (every other mention in
  this file is a bare reference or a command). `DATABASE_URL` is the pooled `-pooler` endpoint,
  read by the app; `DATABASE_URL_UNPOOLED` is the **direct** endpoint, read only by Alembic
  (`migrations/env.py`) — DDL and `CREATE TYPE` need a real session, and a migration through the
  pooler tends to **hang rather than error**.
  - **They are not interchangeable**: against Neon the pooled and direct endpoints are genuinely
    *different hosts*, so one value cannot stand for both. `direct_database_url()` falls back to
    the pooled URL when the direct one is unset, which is the documented CI and local-Postgres
    path.
  - ⚠️ **`DATABASE_URL_UNPOOLED` is the variable that leaked out of `.env` and pointed a stray
    `alembic upgrade head` at production's neighbour on 2026-08-18**, which is why `check:server`
    pins it **empty** and `scripts/local-db.sh` sets it only as a prefix on its own `alembic`
    command. Neither belongs in `.env` on a development machine — see "Local Postgres for the
    test suite".

#### ⚠️ `/api/library` is USER-INDEPENDENT, permanently

`/api/library` is served from a **shared** CDN, keyed on the URL alone, with **no
`Vary: Authorization`**. So a per-user field on that response is handed out of one user's
cache entry to a different user, and **no behavioural test can catch it**: the leak happens
between two requests, inside an intermediary this repository does not run, with every test in
the suite green. **Adding a user-scoped field to this response is a SECURITY change, not a
feature change.**

Per-user state *about* exercises — the "I don't have this gear" flag, personal bests, anything
derived from a `user_*` table — goes on a **separate endpoint that is never CDN-cached**. This
is concrete rather than hypothetical: **PR #11's "I don't have this gear" flag is exactly the
field that would spring it**, and it is the obvious thing to bolt onto a payload that already
lists every exercise's equipment requirements.

`tests/test_library_contract.py` pins the field list and the cache header. It needs no
database, so it runs in the local gate, and it goes red on the diff that adds the field — a
pinned list is the only guard shape available when the failure is invisible to behaviour.

### Engine config — the omissions are the point

**Three stack choices this config rests on. They are rules, not version numbers** — the versions
live in `README.md`'s *Stack* section, `package.json` and `pyproject.toml`, which is why this
file no longer carries a `## Stack` heading of its own:

- **Sync SQLAlchemy 2 with `def` endpoints**, which FastAPI runs in anyio's threadpool. Never
  `async def` here: a sync `def` cannot be cancelled by a client disconnect, which is the whole
  mechanism behind deployment trap 7's pinned `maxDuration` and the two auth deadlines.
- **psycopg3, never asyncpg** — the driver has to be sync for the same reason, and psycopg3's
  *protocol-level* prepared statements are what the `prepare_threshold` bullet below relies on.
- **Neon's region must match the function region**, and Neon's is fixed at project creation —
  see deployment trap 5, which is the failure that wrote the rule.

**`server/db.py`'s module docstring is the authority for every engine argument** — the
`NullPool` / no-`pool_pre_ping` / no-`pool_recycle` / no-keepalive set, why prepared
statements stay ENABLED (and must not be given a `prepare_threshold=None` from an older
draft), and which transaction-mode pooler limits bite. It carries the Neon CU-hour
arithmetic that makes those omissions cost decisions rather than style. Read it before
changing an argument; do not restate it here.

- **`TIMESTAMPTZ`, never naive.** `Base.type_annotation_map` pins `datetime` to
  `TIMESTAMP(timezone=True)` repo-wide, so every future `Mapped[datetime]` gets it
  without anyone remembering. Store aware, convert at the edge.

### Migrations run out-of-band

- Alembic runs via a **manual `workflow_dispatch`** job with `environment: production`
  (approval required), against the **direct** URL. **Never automatic on push** — a
  migration must never race a deploy, and deploys here are automatic while migrations
  are not.
- **Expand → deploy → contract**, always, for the same reason.
- **Never migrate at startup.** Note that there is **no startup revision check today** —
  nothing in `server/` reads `alembic_version`, so a schema/code mismatch is not detected
  or warned about at boot. If one is ever added it must only **READ** and **warn**, never
  migrate; weigh it against the Neon wake it would cost on every cold start.
- Seeding is **TWO modules, in this order**, both run **after** a migration:
  `uv run python -m server.seed`, then `uv run python -m server.contentseed`. CI, local work
  and production all call both, because a test fixture with hand-written rows tests a table
  production never has. The split is **derived vocabulary versus authored content**:
  `server/seed.py` holds what comes from a tuple, `server/contentseed.py` holds the exercise
  library, and the second resolves aspect, equipment and injury **keys** to ids — so it cannot
  run first, and it fails loudly rather than quietly if the vocabularies are missing.
  `server/seed.py` **upserts and never deletes**: user rows reference `grade.id`, so retiring
  a grade is a deliberate migration, not a side effect of editing a tuple. **`contentseed.py`
  is the documented exception to that** — see the durability section below. `seed.py` also
  seeds the **demo account** (`demo@climb-trainer.example`, `password_hash = NULL`), which is
  deployment fixture data, not user data.
- **Shipping a content edit to production is `action=upgrade` + `seed=true`.** There is no
  seed-only action and both seed steps hang off that one `seed` input, so a library change
  rides an upgrade run even when the revision it needs is already applied. ⚠️ **And it needs
  the ref**: the job definition *and* the content both come from the ref you select, so a
  dispatch without `--ref dev` runs `main`'s workflow file and seeds `main`'s library — which,
  before a promotion, is the library you were trying to replace. See trap 2 below.
- **An UNCOMMITTED, UNDEPLOYED revision may be AMENDED rather than stacked**, and the check is
  two-part: `git log --all -- migrations/versions/<file>` returns nothing, **and** both
  environments' applied revision is read back. Both, because either alone is a guess — history
  says nobody else can be holding it, the readback says no database has run it. Amending one
  that has run anywhere is how two databases end up with the same revision id over different
  schemas. `0007` qualified on both counts: never committed, and production run
  `32654384094` and dev run `32653834390` each read back `0006 (head)`. Once a revision exists
  on any branch or is applied anywhere it is frozen, and the fix is a new revision.
- **`DEMO_USER_ID` is pinned at 1 and is part of the data contract** — demo tokens carry
  it as `sub` so `POST /api/auth/demo` needs no lookup. Changing it is a migration. The
  seed inserts that id explicitly and therefore **repairs `app_user_id_seq`** afterwards
  (monotonic `setval`); without that the first real registration collides on the primary
  key and surfaces as a baffling 409 on someone's first sign-up.

#### ⚠️ Production data durability — real accounts, no undo

Production holds real user rows. A deploy can be rolled back and a bad row can be repaired,
but a committed `DROP` cannot be undone from anything in this repository. These are hard
rules, not preferences.

- **A migration touching `app_user` must be ADDITIVE.** `0003` was safe because it only added
  a **nullable** column and an empty table — every existing row was untouched, and the old
  code kept working against the new schema. **Forbidden without an explicit, written backfill
  plan reviewed in the PR:** dropping or recreating `app_user`, dropping any of its columns,
  and adding a `NOT NULL` column without either a `server_default` or a backfill step (that
  last one fails outright on a non-empty table, which is the *good* case — the bad case is a
  default that silently writes the wrong value into every existing account).
  `tests/test_migrations_additive.py` fails the gate on a `drop_table`/`drop_column` against
  `app_user` inside any `upgrade()`.
- **Never run `alembic downgrade` against production.** Note the structural protection and
  **keep it**: `migrate.yml`'s `action` input offers `current`, `upgrade` and `history` and
  **deliberately no `downgrade`**, so undoing a migration is not one dropdown click away from
  a production database. That omission is load-bearing — do not "complete" the set. Recovery
  is a Neon branch restore, not a downgrade: a downgrade runs *more* untested DDL against the
  damaged database, while a restore returns to a known-good copy. (Downgrade bodies still
  exist in the migration files, and are still expected to be correct — they are for local and
  CI use.)
- **Snapshot before upgrading: take a Neon branch of production before any production
  `upgrade` run.** A branch is a cheap copy-on-write copy and is the only restore point that
  **does not depend on the migration being well written** — it costs almost nothing, takes
  seconds, and is the difference between a bad migration being an inconvenience and being an
  incident. Delete it once the deploy is verified. Neon's point-in-time-restore retention
  depends on the plan and **must be read from the dashboard rather than assumed** — do not
  rely on a remembered window, and do not treat PITR as a substitute for taking the branch.
- Two protections that already hold and should stay: `server/seed.py` **upserts and never
  deletes**, so re-seeding production cannot remove an account; and `app_user.invite_id` is
  **`ON DELETE RESTRICT`**, so a spent invite cannot be deleted out from under the record of
  who used it.
- **⚠️ `server/contentseed.py` DOES delete `exercise` rows, and it is the one seed that may.**
  Kilian's call: dropping a key from `server/domain/exercises.py` must *really* delete the
  exercise, because a library that only ever grows is a library nobody can curate. What makes
  that safe against a real training diary is a chain of three, and **all three links are
  load-bearing**:
  1. `session_block.exercise_id` and `logged_set.exercise_id` are **`NO ACTION`**, so Postgres
     refuses to delete a referenced exercise rather than cascading into somebody's history.
  2. The seed asks **`EXISTS` first and never catches the foreign-key error.** A failed
     statement aborts the whole Postgres transaction and this module runs inside one
     `session_scope()`, so a caught `IntegrityError` would poison every statement after it and
     the run would report success having written nothing.
  3. A referenced exercise gets **`retired_at`** instead: the row stays, and it disappears from
     `GET /api/library`. A diary that forgets what you did is worse than a library carrying one
     row too many.
  Deletes are scoped twice over — to the exercise ids the module authors, and to child rows
  nothing in the schema can reference — so no user row can be orphaned by one. Vocabulary rows
  are upserted here too and are never deleted.

#### How to actually run one: `.github/workflows/migrate.yml`

> **Claude dispatches this, for BOTH environments** (Kilian's call, 2026-08-21 —
> `Bash(gh workflow run *)` is allowlisted). Work out the invocation (**ref**,
> `environment`, `seed`), dispatch it, and **read the revision back out of the job log** —
> the run's own "after" step for a `dev` upgrade, and a separate `action: current` run for
> production. **The checkpoint that remains is the `Production` GitHub Environment's
> `required_reviewers: kilianmc`**, which pauses a production run until Kilian approves it
> in the GitHub UI. `dev` and `Preview` have no reviewers, so a `dev` run starts
> immediately and nothing appears for anyone to accept — do not tell Kilian to go and
> approve a `dev` migration, because there is nothing there.
>
> Since that single approval click is now the only human gate on a production DDL run,
> **say what you are about to apply before you dispatch it, not after.** And do not go
> looking for the connection string instead: `vercel env pull` returns `[SENSITIVE]` for
> both DB URLs, and the secrets live only in the GitHub environments. **Read this section
> before any PR that adds a migration or promotes.**

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

##### ⚠️ Three traps, all paid for on the day it first ran

**1. A `workflow_dispatch` workflow only registers if the file exists on the DEFAULT
branch.** Shipped on `dev` alone, `migrate.yml` was *completely inert*: `gh workflow run`
returned `HTTP 404: workflow migrate.yml not found on the default branch`, and it did not
appear in the Actions UI at all — so there was nothing to click either. The GitHub
environments and their secrets were correct the whole time and it made no difference. The
fix was a one-file PR putting it on `main` by itself, a deliberate exception to the "`main`
receives only promotion PRs" rule.

> **⚠️ Still live: a change to this workflow that lands on `dev` alone is INERT until the
> next promotion.** GitHub reads `workflow_dispatch` registration only from the default
> branch. That is now a *latency* problem, not a conflict one — the branches' merge base
> includes the file, so edits merge cleanly and no same-day `main`-side twin PR is needed.
> Decide per change whether it can wait. Notes about the workflow go in *this* file, not in
> a comment that would have to be duplicated. Same rule for every future
> `workflow_dispatch` workflow, and for `.github/dependabot.yml`.

**2. `environment` chooses the DATABASE; the REF chooses the MIGRATIONS.** Registration
comes from the default branch, but GitHub takes both the job definition and the checkout
from the ref you select in the dialog. They are independent inputs and confusing them is
how production gets a revision nobody reviewed. **Pick the ref that carries the revisions
you mean to apply** — `main` has carried `migrations/` since the v2.0.0 promotion, so omit
the ref to apply what production has, and pass `--ref dev` when the revision you want exists
only on `dev` and is not promoted yet:

```bash
gh workflow run migrate.yml --ref dev -f environment=dev -f action=current
```

**3. `alembic current --verbose` prints the connection URL.** It emits a
`Current revision(s) for <url>:` header. Alembic hides the password and GitHub masks the
secret, but the **Neon endpoint hostname, region and database name reach the public log** —
breaking the workflow's own no-connection-string rule via a flag rather than an `echo`. The
steps use bare `alembic current` for that reason; `alembic history --verbose` is fine because
it never opens a connection. Nothing else on the path logs a URL: `sqlalchemy.engine` is
pinned to `WARNING` in `alembic.ini` and `migrations/env.py` never prints one. **The lesson
generalises — in a public repo, audit what a tool prints at its chosen verbosity, not just
what the workflow echoes.**
### SQLite is disqualified for tests

The schema uses native Postgres enums, composite foreign keys, `GENERATED … STORED`, GIN
expression indexes and window functions. (It used `text[]` too, until the ascent-tags
reversal on 2026-08-21 — the rest of the list is more than enough on its own.) Tests run against **real Postgres** — GitHub Actions' `services:` container, and locally the
native `postgresql@17` behind `npm run db:up`, both pinned to Neon's major: once per session
`alembic upgrade head` — so **CI
tests the migrations** — plus seeding from the same module production uses; per test
`begin_nested()` + rollback. `alembic check` catches model drift. Do not "simplify" any
of this to SQLite.

Also: keep the plan tree **fully relational** (a row per prescribed set). It is the
showcase, and denormalising to `jsonb` saves nothing that matters — a 24-week plan is
~290 KB against 0.5 GB.

And: **never store a grade as a display string alone** — a `grade` is
`(system_id, label, ordinal)`. This is the single most expensive thing in the schema to
retrofit, and **`server/domain/grades.py`'s module docstring is the authority** for the
ordinal ladder, the per-discipline bands, and why labels are matched exactly. Read it before
touching anything grade-shaped.

### The domain schema — the shapes worth knowing before you query it

`server/models.py` carries the full reasoning per table; migration `0004` is the DDL, plus
`0005` for `user_profile` (three columns lose `NOT NULL` so "unanswered" is expressible,
`injuries_reviewed_at` arrives, and `user_injury` gains a partial unique index on the open
row per area — see "Onboarding and the profile (PR #9)"). Four decisions are the ones a
reader would otherwise try to undo:

- **`activity` is a SUPERTYPE, and `logged_session` is a 1:1 subtype of it.** One row per
  activity of *any* kind (`activity_kind`: `climbing` · `cardio` · `strength` · `mobility` ·
  `other`), carrying user, date, duration, RPE and the idempotency key; `logged_session` adds
  only the climbing-only columns. The alternative — a `logged_session` table and, when
  cardio arrives (issue #38), a second table beside it — means every readiness, rest-day and
  diary query gets written twice and one copy rots. **`other` is the escape hatch** so an
  unanticipated kind is loggable without an `ALTER TYPE` migration.
- **`srpe_load` (`GENERATED ... STORED`, RPE × minutes) lives on `activity`, not on
  `logged_session`.** A generated column can only reference its own table's columns, and
  duration and RPE are supertype columns — and it is the right home anyway, because an easy
  run is real load. NULL RPE gives NULL load, deliberately: no score, not a score of zero.
- **Adherence and load are two queries over one nullable column.** `activity.planned_session_id`
  is the only link to the plan. Adherence = activities that point at a planned slot (a
  non-climbing activity can satisfy one); load and rest-day logic = *all* activities. Neither
  rule is baked into a constraint, because both will be tuned.
- **Three composite foreign keys do real work, and all three look redundant if you skim
  them.** `microcycle (mesocycle_id, plan_id) → mesocycle (id, plan_id)` is what makes
  carrying `plan_id` down the tree safe rather than merely intended (the `(plan_id, week_no)`
  index is the hottest read in the app). `logged_session (activity_id, activity_kind) →
  activity (id, activity_kind)`, plus `CHECK (activity_kind = 'climbing')`, is what stops a
  logged session attaching to a bike ride. `ascent (grade_id, grade_ordinal) → grade (id,
  ordinal)` is what makes the denormalised ordinal safe: the band **is** the discipline, so a
  transposed ordinal files a French 7a rope send in the boulder pyramid with nothing left to
  recover the truth from. Each needs a `UNIQUE (id, …)` on its parent — those are not
  hygiene, they are FK targets. **The technique is the house pattern for a denormalisation:
  if you copy a column down, tie it back.** One place deliberately does not
  (`logged_set.exercise_id` vs its prescription's) — see that model's docstring for the cost
  argument and the write-path obligation it creates instead — **issue #62**, not PR #10,
  which shipped a read-only library and no write path at all.

- **`ascent.tags` is gone.** Tags were `text[]` + a GIN index; they are now the seeded
  `ascent_tag` lookup plus the `ascent_tag_link` join (Kilian, 2026-08-21 — reasoning in
  "Prefer CLOSED inputs over free text" above and in
  `server/domain/vocabulary.py::ASCENT_TAGS`). This is recorded in three places on purpose,
  because the array version reads as the more flexible design and will otherwise be
  "restored" by the next agent who sees a join table where an array would do.
- **Every `ON DELETE SET NULL` or `CASCADE` foreign key has an index whose LEADING column
  is the first FK column.** Postgres does not create these for you and it has to find those
  rows to null or delete them, so without one, abandoning a 24-week plan cascades to ~1000
  `prescribed_set` rows and each one sequentially scans `logged_set`, the largest table in
  the app. **No test and no CI run would ever show this**; it appears only as Neon awake
  time, which is the resource this project is actually short of.
  - Most get it free from a composite primary key or a unique constraint that happens to
    lead with the right column. **Six do not, and are declared explicitly:**
    `activity.planned_session_id`, `logged_set.prescribed_set_id`,
    `ascent.logged_session_id`, `journal_entry.logged_session_id`,
    `microcycle (mesocycle_id, plan_id)` — whose unique constraints lead with `plan_id` and
    `id`, so the FK's own leading column has nothing — plus
    `exercise_equipment (equipment_id)` and `exercise_contraindication (injury_area_id)`,
    where the composite PK covers the other side only. The last three were missed by the
    PR that wrote this rule, which is the ordinary way to get this wrong: a composite
    constraint *looks* like coverage.
  - ⚠️ **Every remaining foreign key is `NO ACTION`/`RESTRICT` and is deliberately
    unindexed** — a different argument, not an oversight. Those parents are reference rows
    nothing deletes (`grade`, `equipment`, `climbing_aspect`, `injury_area`, `ascent_tag`)
    or, for `app_user.invite_id`, a row RESTRICT exists to make undeletable. No delete means
    no referencing-side scan and nothing for an index to save.
    ⚠️ **`exercise` is no longer one of those, and the decision is unchanged.**
    `server/contentseed.py` deletes unauthored exercises, so the `EXISTS` that decides
    delete-versus-retire really does seq-scan `session_block`. **Still no index**, on a
    different argument: that scan runs only on a **seed dispatch** — a rare, manual,
    out-of-band admin operation — and only for keys the content has *dropped*, so on virtually
    every run there are none and the query is skipped outright; and `session_block` is small
    (~30 blocks per generated plan). An index would buy write amplification and storage on
    every plan generated, forever, to save milliseconds on an operation nobody performs in the
    request path. (`logged_set.exercise_id` is already indexed for unrelated reasons, so that
    half is free.)
    **Do not "complete the set"** — that is a dozen indexes bought with write cost and
    storage against a 0.5 GB budget, for a lookup nothing performs.
- **`activity.srpe_load` casts: `rpe::integer * duration_minutes`.** Both operands are
  `SMALLINT`, so the uncast product resolves as `int2 * int2` and raises `smallint out of
  range` *before* widening into the `INTEGER` column — and on the outbox path a payload that
  raises retries forever and can never succeed. `duration_minutes` is `CHECK (BETWEEN 1 AND
  1440)` for the same reason, and PR #9 owes it the matching Pydantic bound so that a unit
  error is a 422 rather than a retry loop.

Also: the tsvector search indexes are **expression** indexes (`to_tsvector('simple', …)`),
which Alembic skips on both sides of an autogenerate comparison — so they cost nothing in
`alembic check` and nothing is excluded by hand. `simple`, not `english`: no stemming and no
stopword list is right for short notes full of proper nouns. And the `(user_id, date)`
indexes are plain ascending btrees, **not** `DESC` — Postgres scans them backwards at the
same cost, and a `DESC` element would make them expression indexes for no gain.

### ⚠️ The app never recommends losing weight (Kilian's rule, 2026-08-21)

**Hard rule. It binds the plan generator (planned PR #11), every coaching string, and the
schema itself.** Strength-to-weight is the most useful number in climbing and the app shows
it — but the *advice* attached to it only ever runs in one direction:

> **Low strength-to-weight means "get stronger". It never means "get lighter".**

No copy, tip, insight, badge, chart annotation or generated recommendation may suggest
losing weight, a weight range, a "climbing weight", or that a body-composition change would
improve performance. Not as a nudge, not as a neutral-sounding observation, not behind a
setting.

**Why, so nobody re-derives it as a feature request.** Climbing has a documented
disordered-eating problem — it is the sport's best-known health failure, not a hypothetical
— and this project's governing principle is **user health first**, ahead of completeness and
ahead of what a fitness app is "expected" to do. A training app that tells a climber to lose
weight is not a neutral tool; for some fraction of its users it is actively harmful, and
there is no version of that advice that is safe to ship to a stranger. Getting stronger is
the same ratio arithmetic with none of the risk.

The schema is built so the feature cannot arrive by accident:

- **No goal-weight, target-weight or BMI column exists anywhere**, and
  `tests/test_schema_no_weight_targets.py` fails the gate if one appears — with a positive
  control, so the detector is known to work. A schema with nowhere to put a goal weight is
  a schema where this cannot be built without a visible fight.
- **`journal_entry.body_weight_kg` stays**, because a weigh-in is legitimate data. The
  **trend is smoothed / rolling only** — a raw day-to-day line is hydration noise rendered
  as progress or failure.
- **%BW is snapshotted onto the performance** (`logged_set.body_weight_kg`, nullable,
  copied from the most recent weigh-in within ~7 days) rather than joined live, so
  historical figures never silently shift when somebody steps on a scale again.
- **`user_profile.show_body_metrics` (default TRUE) turns the whole thing off** — no weight
  trend, no %BW anywhere, and nothing prompts for a weigh-in.
- **Diet, if it ever ships, is habits-only.** No calorie logging, no food diary, no nutrient
  columns. See issue #38.

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

### Security response headers

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
- **The *shell's* CSP governs the federated mount, not ours.** `portfolio-shell` has none
  today; if it gains one it needs `script-src`, `connect-src` **and `style-src`** for
  `https://climb.kilianmc.com`.
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

### Auth implementation — where each piece lives

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
  already-rotated or revoked token **revokes the whole family** (`refresh.rotate`) —
  **except** for an unrevoked row rotated less than `REPLAY_GRACE` (10 s) ago, which is a
  lost race between the two mounts sharing one cookie and answers **409, writing nothing**.
  See the grace-window section of `server/auth/refresh.py` for the reasoning and for the
  narrowing it accepts.
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
token before every `POST /api/auth/*`** — see the Auth UI section below, which corrects the
narrower "login or register" wording this line used to carry.

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

### Registration is invite-gated

`POST /api/auth/register` requires a valid, unexpired, unrevoked, not-exhausted invite code.
`EmailStr` validates *syntax*, so before this anyone could create an account on
climb.kilianmc.com; email verification would not have fixed it (it proves an inbox exists,
not that its owner is someone Kilian knows) and is deliberately still deferred.

`server/auth/invites.py` carries the reasoning. The parts a reader would otherwise reverse:

- **Per-person codes in a table, never a shared env secret.** `invite` holds a **sha256
  digest, never the code** (same reasoning as `auth_session.token_hash`; sha256 rather than
  argon2 because a code is 128 bits of CSPRNG output), plus a human `label`, `max_uses`,
  `uses`, `expires_at` and `revoked_at`. One person's code can be revoked without touching
  anyone else's, and the count makes a use attributable.
- **One failure for four causes.** Unknown, expired, revoked and exhausted are all
  `InviteRejectedError` and all one **400** with one message. Never split them: "expired"
  confirms a code exists. The shape matches too — one indexed statement either way, nothing
  committed on any rejection path, and no fast path for "no such code". Two residues are
  written down in the module and are **not** worth changing behaviour for: `FOR UPDATE` stamps
  `xmax`, so a found code is write-free in round trips but not in storage; and two
  *concurrent* presentations of one guess distinguish "row exists" from "no row" because only
  the former blocks. Both are noise at 128 bits behind 3/hour.
- **400, not 403.** 403 already means "demo mode is read-only" on every auth route, so
  reusing it would leave the client unable to write correct copy for either.
- **⚠️ The message names a way out, and that half is not decoration.** The commonest cause of
  a rejection is not an attacker: it is someone re-entering the single-use code they already
  registered with, or retrying after a lost response. `REGISTER` is 3/hour, so they get few
  goes at working it out. `_INVITE_REJECTED` therefore ends "If you already have an account,
  log in instead" — true for all four causes, distinguishing none of them, and the only thing
  that stops a returning invitee asking for a code they do not need. **`web/src/auth/messages.ts`
  has no `case 400` on purpose**: the server's sentence is already right, and `authMessage` is
  shared with `/login`, which has no invite field.
- **Attribution is a column, not just a counter.** `app_user.invite_id` is a nullable FK set
  from the row `consume()` locked (never from the request). `ondelete=RESTRICT`, so a spent
  invite cannot be deleted out from under the record of who used it — revoking is the supported
  way to retire one. Nullable because the demo account and every pre-gate account have none.
- **`consume()` takes the row `FOR UPDATE` and never commits.** The lock is what stops two
  concurrent registrations both spending the last use; sharing the handler's transaction is
  what stops a *failed* registration burning one. `ck_invite_uses_within_max` is the
  database's own backstop. `tests/test_auth_invites.py` proves both, the second with two real
  connections.
- **⚠️ `web/src/registerSubmit.test.tsx` is a core-user-path test, not a render test of
  presentational UI** — do not delete it under the `CredentialsForm` policy exclusion. It exists
  because the glue mapping the form's `inviteCode` onto the request's `invite_code` was the one
  part of the path nothing covered, and `invite_code: ''` shipped green while making sign-up
  impossible for every invitee (an empty code gets the same 400 as a wrong one). It is the only
  render test of that form, deliberately.
- **Minting is a CLI, because the plaintext exists only in the generating process** —
  `python -m server.admin create-invite --label "..."`, printed once. Revoking needs no
  secret and therefore no command: `UPDATE invite SET revoked_at = now() WHERE id = ...`.
- **Migration `0003` creates an empty table** and adds a nullable `app_user.invite_id`, so
  after it and before the gated deploy, registration still works as it did and no existing row
  changes. Expand → deploy → contract, as usual.

#### ⚠️ Minting an invite is a LOCAL command, and must never become a workflow

**Production invites are minted from a developer's terminal against the production direct
URL** — the same flow as dev: mint the code, hand it to the person, they register with it.
There is no second step and no UI.

**Do NOT add a `create-invite` action to `migrate.yml`, or a workflow of any kind that mints
one.** This will look like an obvious convenience — it is the one admin task that currently
needs a laptop — and it is the one place the invite design breaks:

- `create-invite` **prints the plaintext code to stdout**, and only `code_hash` is stored
  precisely so that a database dump is not a set of working invites. A workflow's stdout is an
  **Actions log**, which on this public repo is **world-readable**. Uploading it instead makes
  it a public-repo artifact, downloadable by anyone.
- **Masking is not the fix**, because it defeats the purpose: a masked code is hidden from
  Kilian too, and the code has exactly one consumer — the human who has to be told it.
- The 3/hour `REGISTER` limit and the 128 bits of entropy assume the code is secret in transit.
  A published code makes the gate decorative while every other control still reports healthy.

If minting from a laptop ever becomes genuinely impractical, the answer is an authenticated
admin endpoint that returns the code to *one* caller — not a job whose output is a log.

### Local accounts, and the two things that are NOT `server/seed.py`

`server/seed.py` is called by CI, local development **and production** —
`.github/workflows/migrate.yml` runs `python -m server.seed` whenever its `seed` input is
on. So neither of these may ever move into it:

- **`server/devseed.py`** — ten accounts (`<name>@dev.climb-trainer.example`) whose passwords
  are `<name>` + digits + one special character, randomised per user and **padded to
  `MIN_PASSWORD_LENGTH`** because a shorter one would be an account `/api/auth/register` and
  every future reset would refuse. It prints the credentials **once, to the terminal**, and
  nothing automated invokes it.
  **Three guards, because they answer three different questions**, and the CI check alone was
  not enough: `CI`, `GITHUB_ACTIONS`, `VERCEL` and `VERCEL_ENV` are checked for **presence, not
  truthiness** (`CI=` is still CI, and this repo's Actions logs are public);
  `CLIMB_DEV_SEED` must be set, because "not CI" is not the claim "this is a throwaway
  database" and `.env` is loaded on import, so the shell you just minted a production invite
  from reaches production from here too; and `main()` prints the target **host** (never the URL
  or a credential) and will not write until you type it back. Guards 1 and 2 are on
  `seed_dev_users()` as well as `main()`. `CLIMB_DEV_SEED` is deliberately **not** in
  `.env.example` — in `.env` it becomes standing permission.
- **`server/admin.py`** — `set-password` (argon2id means there is no cell in Neon a
  plaintext can be typed into; the password is read with `getpass`, never from `argv`) and
  `create-invite`. It refuses to set a password on the demo account, whose NULL
  `password_hash` is what makes it unloggable.

### Auth UI — the client half of the contract

`web/src/auth/` — `session.ts` (the in-memory token store), `authClient.ts` (the five
credential calls), `refresh.ts` (single-flight silent refresh), `AuthProvider.tsx`
(composition + `bootstrap()` + `useAuth()`), `redirectTarget.ts`, `messages.ts`. The guard is
the pathless layout route `web/src/routes/_authed.tsx`; everything under `routes/_authed/` is
protected by living there.

**The rules below are each a failure the obvious implementation ships** (the list is no longer
five long; a count in the heading drifted every time one was added):

- **⚠️ Drop the token before EVERY `POST /api/auth/*`, not just login and register.**
  `enforce_auth` applies the demo write-ban **before** its public-route check, so a `demo`
  bearer 403s on `register`, `login`, `logout` **and** `refresh` alike — every mutating auth
  route except `POST /api/auth/demo`, the sole entry in `DEMO_WRITE_EXEMPT_ROUTES`. The
  earlier wording of this rule said "login or register" and was too narrow.
  `authedFetch`'s `send()` also refuses to attach a bearer to any `CREDENTIAL_PATHS` entry, so
  the rule holds **structurally** and not only by call-site discipline — that set used to
  suppress the retry-on-401 but not the header, which is precisely the footgun the rule exists
  to prevent. `/api/auth/me` is deliberately outside the set: a GET keeps its bearer.
- **Demo scope RE-MINTS; it cannot refresh.** `POST /api/auth/demo` takes no `Response` and
  sets no cookie, so a demo session has no family to rotate, and sending its 1 h token to
  `/api/auth/refresh` hits the write-ban and 403s — a failure that looks nothing like an
  expiry. `refresh.ts` branches on scope for that reason.
- **Serialising the refresh is a correctness requirement, not a request-count optimisation —
  and it takes THREE mechanisms, one per realm.** `refresh.rotate` reads `FOR UPDATE` and
  treats a second presentation of an already-rotated token as theft, revoking the whole
  family. Note what the row lock does: it **serialises** two presentations, it does not
  deduplicate them, so the loser is *guaranteed* to re-read the row after the winner commits
  and see `rotated_at` set. Before the grace window below, that revoked the family — killing
  the winner's brand-new token too, leaving both callers unable to refresh.
  - **Within a mount:** `inFlight` in `createAuthedFetch`, so N concurrent 401s share one
    attempt. `reauthenticate` joins it **before** comparing tokens — `mint` clears the store
    synchronously before it awaits, so the comparison-first ordering made a second waiter
    conclude someone else had already finished and give up. That ordering is the whole bug.
  - **⚠️ Across tabs of ONE origin:** the **Web Locks API**, `climb-trainer:auth-refresh`.
    `inFlight` is a closure local, so two tabs have two of them, while the refresh cookie is
    scoped to the **browser profile**. An earlier draft of this file stated the single-flight
    guarantee unqualified, which was wrong and is the wording to avoid restoring: per-mount
    dedupe covers strictly less ground than the failure it prevents.
  - **⚠️ Three realms are in play and they do not line up** — `inFlight` is per **mount**, a Web
    Lock is per **origin** (partitioned by storage key), the refresh cookie is per **site**. So
    the lock does **not** cover mounts: standalone is `climb.kilianmc.com`, the federated mount is
    `kilianmc.com`, they get two different lock managers, and they share one cookie *because*
    they are same-site — which is the entire reason auth works federated at all. **Never describe
    the lock as covering "tabs and mounts".**
  - **⚠️ Across the two ORIGINS — NARROWED, not eliminated: a
    SERVER-side grace window, and nothing the client can do.** A standalone tab plus the
    climb-trainer card open on the portfolio is the arm no lock reaches, so both mounts present
    the same pre-rotation cookie. `rotate()` now answers the loser with **409 and no write at
    all**, and `refresh.ts` retries the POST **exactly once** — the browser attaches the token
    the winner rotated into the shared jar, so the retry is an ordinary legitimate rotation.
    Realm-independent because the server sees presentations, not origins. **No migration was
    needed**: `rotated_at` already existed, and the successor's plaintext is never stored, so
    "hand back the same replacement token" (what the issue originally proposed) was not
    implementable and was not implemented.
    - **Three bounds, and they must stay written down.** (1) The winner leads the loser by
      about one database round trip — its response goes out after the `commit()` that releases
      the row lock, and the loser then pays its own commit — which is a **margin, not an
      ordering guarantee**; if the 409 is processed first, the retry re-presents the same token,
      gets a second 409, and that mount stops refreshing until the page reloads. (2) One retry
      converges **exactly two** realms; a third same-site origin (or an unusable lock making
      two tabs behave as separate realms) leaves the second loser with no retry left. Revisit
      the count if a third origin ever mounts this app. (3) **A loser slower than the grace
      window — stalled radio, queued cold start — still trips reuse detection and still revokes
      the family. Do not widen the window to hide that.**
    - **The trade, which is a real loss and must not be written up as a free win:** inside the
      window a replayed token no longer revokes its family, so a genuine theft landing there
      goes **undetected**. The replayer gains no token — the 409 carries none and the successor
      is only reachable by whoever already holds the shared cookie jar. Accepted because the
      alternative is that our own two-origin configuration logs real users out. `revoked_at`
      rows are **never** graced, at any age.
    - The Web Lock is **kept** and is now an optimisation rather than the correctness
      mechanism: it saves the extra POST — and therefore a Postgres write and another
      five-minute Neon window — that the 409-plus-retry costs a losing same-origin tab.
    - `crossTabRefresh.test.ts` still cannot model two origins in jsdom, so it varies the
      **lock realm** instead: no lock manager behaves exactly as two independent ones do.
  - The cross-tab fix is narrower than it looks. The race only breaks because both tabs read
    the same **pre-rotation** cookie, so serialising is sufficient by itself: the waiting tab
    wakes, sends the *already-rotated* cookie and performs a legitimate rotation of its own.
    Valid token, reuse never tripped, **no server change**. Cost is one extra Postgres write
    per additional tab, which is correct behaviour rather than a bug.
  - **Tokens are deliberately NOT shared between tabs.** `BroadcastChannel` would save that
    write and is rejected: in the federated mount the origin is kilianmc.com, so the channel is
    shared with the shell and every other remote, and an access token on it would give away the
    property the design holds — token in no storage, no URL, no `postMessage`, no React prop.
  - The lock is held across the **full** round trip, `res.json()` included, because `Set-Cookie`
    only reaches the jar on receipt; releasing earlier reintroduces the exact race. Only the
    refresh path takes it — `POST /api/auth/demo` presents no cookie and cannot race.
  - **Where the lock is unavailable** it degrades to the per-mount dedupe and the same-origin
    guarantee is simply unavailable — never to something worse, and never a throw.
    `auth/crossTabRefresh.test.ts` asserts both arms; the no-locks arm is the permanent record of
    that boundary and is what keeps the locked arm honest. **Presence is not usability and cannot
    be made into it**: in an opaque or sandboxed origin the property exists, looks right, and
    `request()` rejects. `withRefreshLock` therefore tells the cases apart by whether its callback
    was entered, and a refusal falls back to running unlocked.
  - **`exhausted` latches only when the API itself answered.** A dropped connection or an HTML
    shell from a bad rewrite never reached FastAPI's rate limiter, so there is no Postgres write
    to protect against — and latching would disable refresh for the rest of the page load over a
    blip, while reporting an infrastructure fault to the user as a logged-out session.
- **One failure memo, shared by `bootstrap()` and `request()`.** `bootstrap()` used to carry its
  own `attempted` cap while `request()` carried none, so once the store was anonymous `stale`
  and `current` were both `null`, the early-out never fired, and **every** subsequent 401 minted
  another refresh. `refresh_tokens` checks the cookie before the rate limiter, so a cookie-less
  visitor is free — but a cookie that is present and *invalid* (the state after a revoked
  family) reaches a `ratelimit.enforce` upsert: one Postgres write and one restarted five-minute
  Neon window per 401, until the 30/hour bucket 429s. `exhausted` lives in `createAuthedFetch`
  and is cleared the moment a token arrives by another route, so a login is never a dead end.
  Two memos with overlapping meaning is how one of them ends up missing.
- **⚠️ A refresh that resolves after a deliberate session change must not write into it.**
  `SessionStore.generation()` counts every `set` and `clear`; `mint` captures it after its own
  clear and re-checks before writing. Without that, a logout landing mid-refresh is silently
  undone — the nav shows a signed-in user holding a token whose family the server already
  revoked, and the refresh's `Set-Cookie` lands after logout cleared the jar. The same check
  makes a login or an "explore the demo" click that lands mid-refresh **win**, and `mint`
  reports whether the app now holds a usable token rather than whether its own attempt won.
- **`bootstrap()` is called from `_authed`'s `beforeLoad` and nowhere else.** A refresh is a
  Postgres write, so doing it at mount would wake Neon for every anonymous visitor who merely
  reads the landing page. `routes/index.tsx` checks only the in-memory token. **Accepted
  consequence: a signed-in user opening `/` cold sees the public landing page**, and is signed
  back in when they enter the app.
- **No pre-emptive refresh timer off `expires_in`.** Lazy, on 401 only. A timer is a periodic
  database write for the length of a whole training session, which is the largest avoidable
  consumer of the compute budget.
- **⚠️ TWO deadlines on the auth path — one stops AWAITING, one aborts the SOCKET — and merging
  them re-creates a worse bug than the one they fix.** Issue #28. Read this before touching either
  number.
  - **The symptom.** A `fetch` that *hangs* produces no rejection, so everything above it is
    inert: `bootstrap()` is awaited in `_authed`'s `beforeLoad`, so guarded routes sat on the
    **pending component** forever, and the Web Lock — deliberately held across the full round
    trip — kept every other tab on the origin queued behind the stalled holder.
  - **⚠️ Why the obvious fix (one `AbortSignal.timeout(8_000)` on the POST) is WORSE.**
    `POST /api/auth/refresh` is a **sync `def`**, so it runs in anyio's threadpool and a client
    disconnect **cannot cancel it** — and `refresh_tokens` **commits the rotation before the
    response exists**. Abort at 8 s on a slow cold path and the server still rotates at 9 s. The
    successor is stored only as a sha256 and its plaintext is never repeated, so **nobody holds
    the live refresh token**: a retry inside `REPLAY_GRACE` gets a second 409 and gives up, and a
    retry after it trips reuse detection and `revoke_family()` hard-logs the user out. An 8 s
    abort *manufactures* that on requests that were about to succeed. For scale: `/api/health`
    (zero SQL) measured **2.03 s cold vs 0.28 s warm** on the live deploy — that is Python boot
    before any database work — and 8 s is also below `REPLAY_GRACE` (10 s) and below the pinned
    function ceiling.
  - **So: `UI_DEADLINE_MS` = 8 s stops awaiting and aborts nothing** (a `setTimeout` racing the
    *await*). The route leaves the pending component; the POST runs on, commits, and its
    `Set-Cookie` reaches the jar, so **no orphan is created**. **`HARD_ABORT_MS` = 30 s is the
    real abort** — its only job is to stop a wedged socket leaking a request slot and the origin's
    Web Lock. **The gap between the two numbers IS the fix.**
  - **⚠️ 30 s is the OUTER bound only because `vercel.json` pins
    `functions."api/index.py".maxDuration` to 20 s, and that pin is load-bearing.** Unpinned it is
    Vercel's default, and under **Fluid compute — the default for new projects since 2025 — that
    is 300 s**, which would put the client abort back *inside* the server's window and leave the
    orphaned-rotation mechanism fully intact, merely rarer. 20 s is always accepted (Hobby's
    configurable maximum is 60 s even without Fluid). **Deleting that block silently re-opens the
    hole**, with a green gate and no symptom until a cold path runs long. It bounds the `/api/*`
    function only; migrations and the seed run out-of-band in Actions and are unaffected.
  - **`inFlight` must survive a UI-tier give-up.** That is what makes the design pay: a retry (or
    a later guarded navigation) **re-joins the same attempt** and succeeds when it lands, instead
    of presenting the pre-rotation cookie again. The give-up path must never clear `inFlight`.
    `mint`'s own `session.clear()` runs *before* the POST — the "drop the token before every
    `POST /api/auth/*`" rule, unavoidable — and its catch-path clear cannot fire on a give-up
    because `mint` is still in the air, so a give-up clears nothing new.
  - **The UI tier does NOT release the Web Lock, deliberately.** The holder's rotation may be
    mid-commit; letting the next tab present the same cookie is the collision the lock exists to
    prevent. A waiting tab pays latency, and its bound is `HARD_ABORT_MS` **doubled — up to 60 s,
    not 30 s**: `rotateRefreshCookie` builds a fresh deadline for its 409 retry and both POSTs run
    inside one `withRefreshLock` callback.
  - **The visible cost of that, and it is real.** `mint` clears the store *synchronously* before it
    queues, so a waiting tab flips to the **anonymous nav** the moment it starts waiting and stays
    there until the holder releases. The mechanism predates the two tiers; what changed is the
    window, from ≤8 s to up to 60 s. Accepted against the alternative — a second presentation of a
    cookie that may be mid-rotation — but if it ever needs improving, the fix is a "checking your
    session" nav state, **not** releasing the lock early.
  - **General rule, beyond auth: a client deadline on a request with SERVER-SIDE WRITE EFFECTS
    must be the OUTER bound, never the inner one.** Giving up on an answer is cheap and
    reversible; cancelling a write you cannot cancel is neither.
  - **An unanswered refresh is not "signed out".** A 401 (or any 4xx) means the visitor genuinely
    has no usable cookie — `false`, and `/login` is right. A timeout, a dropped connection or a
    **5xx** means the question was never answered, so `mint` throws `SessionUnavailableError`,
    `beforeLoad` lets it out, and the error boundary says the server did not respond. Collapsing
    the two put an infrastructure fault in front of the visitor as a login form they could not get
    past.
  - **⚠️ `unavailable()` tests `status >= 500` BEFORE its `NotJsonError` exclusion, and the order
    is load-bearing.** Reversed — as it shipped first — every HTML 5xx returned "answered" and
    redirected to `/login`, and **HTML is exactly what a platform 5xx is**: Vercel serves
    `FUNCTION_INVOCATION_TIMEOUT` (504) and its mid-deploy 502 as error *pages*. The branch worked
    for the 5xx we can barely produce and failed for the one the platform actually generates. A
    `NotJsonError` **below** 500 is still an answer, which is the case the exclusion exists for —
    a rewrite serving the SPA shell does it with a **200**. `refresh.test.ts` carries the HTML-504
    fixture whose absence let this through.
  - **Two attempts per MOUNT on the unanswered path** (`MAX_UNANSWERED_ATTEMPTS`), then the
    recorded fault is replayed. Two, because the retry above depends on there being one; not
    more, because an unanswered attempt latches nothing, so without a counter every subsequent
    guarded navigation starts a fresh POST — one `ratelimit.enforce` upsert and one restarted
    five-minute Neon window each — turning one write per mount into one per navigation.
    **Running out of attempts still reports the fault, never `false`.** This is a *counter* and
    `exhausted` is a *latch*; they are two memos on purpose, because "the API answered no" and
    "the API did not answer" are not the same fact.
    - **Per MOUNT, not per page load.** `web/src/remote.tsx` builds `createAuth()` per mount
      instance by design, so in the federated mount navigating away from the project and back
      re-arms the budget with no page load. Write "page load" here and the next reader sizes the
      cap against the wrong lifetime.
    - **⚠️ It counts only faults that actually REACHED the server** (an `ApiError`, or an abort). A
      `TypeError: Failed to fetch` never opened a connection, so it cost **zero** writes — the same
      reasoning `exhausted` already applies — and counting it made the retry button a **permanent
      no-op**: on a dead radio `fetch` rejects instantly, so two clicks inside a second spend both
      attempts, and because the counter is only reset when a token arrives, the signal coming back
      does not re-arm it. Nothing short of a fresh mount recovered. Tested with a run of offline
      failures followed by a success.
  - **The existing 5xx residue, still unfixed on purpose:** a 5xx both throws *and* latches
    `exhausted` (it reached FastAPI, so the rate-limit write may have happened), so a *second*
    guarded navigation in the same page load reports "no session" and redirects. That is what a
    5xx already did before any of this, and un-latching it is a change to the write cap rather
    than to the timeout — Kilian's call, not a drive-by.
  - **`RouteError` carries a retry, and it is `router.invalidate()`.** Invalidating re-runs
    `beforeLoad` → `bootstrap()` → `reauthenticate`, which re-joins the in-flight refresh: no
    extra POST, no extra Postgres write. A "retry" that fired a fresh refresh would present the
    pre-rotation cookie a second time. It reads the router with `useRouter({ warn: false })`
    because the same component renders outside any provider (`rootStatusScope.test.tsx`, and the
    root-level Suspense fallbacks) — and note that hook returns the context **default, `null`**,
    not `undefined`, so both must be checked or the retry crashes the error boundary from inside.
  - **`SessionUnavailableError` is the FIRST case in the query retry predicate** (`router.tsx`).
    It is not an `ApiError`, so it fell through to the generic "retry twice" arm — three refresh
    POSTs and three writes for one query, on top of the cap above. The auth layer owns the refresh
    retry policy; Query must not add a second one. **📌 Consequence for the data layer, not
    reachable yet:** because it is `false`, a query that hits an 8 s give-up stays errored even
    though the refresh usually lands seconds later. Retrying in Query is the wrong fix; the right
    one is a refetch driven by the session store's next non-null token.
  - **Deliberately NOT a default in `apiFetch`.** Weighed and turned down: a deadline there is
    inherited by every present and future caller off the back of one auth bug, and the right
    duration is a property of the call. `web/src/api/client.test.ts` asserts the client adds **no** signal
    of its own, so re-adding one is a red test rather than a silent policy change. There is also
    no `AbortSignal.any` composition any more: all three call sites pass a literal
    `{ method: 'POST' }`, so an earlier revision advertised a capability it did not have. Add it
    back with the first real caller signal, and check support (`AbortSignal.any` is Safari 17.4+).
  - **Accepted residual risk, filed separately:** the orphaned-rotation window still exists for
    anything that genuinely severs the connection (the 30 s abort, a closed tab, a dead radio).
    Closing it needs *server-side* work — deliver-or-rollback, or making a re-presentation inside
    the grace window recoverable — in `server/auth/`, which this fix deliberately does not touch.
  - **Nothing in `portfolio-shell`.** A hanging remote still blanks kilianmc.com; that is shell
    issue #48 and a separate decision.

**The route guard must not assume a mount.** It never reads `window.location` (in the
federated mount that is kilianmc.com's) and never builds a URL: `location.href` in
`beforeLoad` is TanStack's own path + search string, and `redirect()` does not go through
`createHref`, so no origin can leak. `?redirect=` is re-validated by `internalPath` on the way
in *and* out — an open redirect here would fire from the portfolio's own address bar. `/login`
navigates the successful case with `router.history.push`, not `navigate({ to })`, because the
target is a validated runtime string and `to` is typed to the tree's literal paths.

**`web/src/publicRoutes.test.ts` is the client mirror of
`tests/test_auth_routes_enumerated.py`**, and exists for the same reason: the directory
convention protects a leaf by where its file sits, so the failure mode is **omission** — a
route created next to `login.tsx` instead of inside `_authed/` is silently public and nothing
else in the gate notices. Every route must be in `PUBLIC_ROUTE_IDS` or under `_authed`.

**It checks the union of the generated tree and the ids the route FILES declare.**
`routeTree.gen.ts` is only regenerated by a build, and when this guard was written `check:web`
ran `test` **before** `build` — so a tree-only check was blind on the exact change it exists to
catch: adding `routes/settings.tsx` left it green until a build had run, and the first CI failure
was the post-build stale-file check, naming a stale file rather than an unguarded route. Issue
#26 has since put `build` first, but the union stays: `vitest` is run on its own constantly, and
a security guard must not depend on the order of two npm scripts. The
declared id is the literal the author passed to `createFileRoute`, which the router plugin
already validates against the file's path, so this reads an authored fact rather than
re-deriving the generator's naming rules.

**`GET /api/auth/me` stays SQL-free.** It reads the token's claims and issues **zero** SQL,
which is what lets a session bootstrap not wake Neon. Adding `email` to `MeResponse` would
need a row read per call, so the nav shows the *scope* ("Demo — read only") and never an
address. Do not "improve" it by returning the user's email.

**`apiFetch` changed shape in this PR**: `headers` is a plain `Record<string, string>`, never a
`Headers` instance (it is spread into an object literal, and spreading a `Headers` yields `{}`,
silently dropping `accept` and `authorization`); `json` sets the `content-type` FastAPI's
`strict_content_type` requires; and a 422's **array-shaped** `detail` is joined rather than
stringified, which used to put `[object Object]` in front of the user on every validation
failure.

**The landing page and the auth screens have a FROZEN structure** — hero, positioning line,
three value sections, an "explore the demo" section, the three calls to action, and the image
slots. `router.test.tsx`, `routeGuard.test.tsx`, `publicRoutes.test.ts` and
`remote.guard.test.tsx` assert the link lists, headings and DOM order, so a restyle can only
change classes and wrappers. **One landing page serves BOTH mounts, unbranched** — Kilian's
call.

### 🔒 TODO — the end-to-end security verification pass (Kilian's call)

**Do not tick any of it off from memory.** Every rule in this file was written because of a
real risk, and a rule that was implemented once and never verified against the running system
is indistinguishable from a rule that quietly stopped working. Two of the controls listed
below **do not live in this repository at all**, so no test in CI can ever notice their
absence.

**When:** once the product is feature-complete on `climb.kilianmc.com`, and **before** the
project is shown to anyone as a portfolio piece. Run it against the **production deploy**,
not a preview: previews are cross-site (`*.vercel.app` is on the Public Suffix List) and
behave differently on purpose.

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
  9. **Security response headers** — see the baseline section above. On the real deploy check
     that the `vercel.json` layer reaches **`/api/*`** and that no header (notably
     `Strict-Transport-Security`) appears **twice**, and that the document CSP logs no
     console violations on a real page load. Also confirm
     **`Cross-Origin-Resource-Policy` is still set nowhere** — that, not `frame-ancestors`,
     is the header that would break the federated mount (see the headers section).
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
      reason it does not apply. "Not exploitable" needs re-deciding per alert, not once.
      **Alerts are raised against the default branch, so they clear at a promotion to
      `main`, not on merge to `dev`.** Also confirm the Dependabot config is actually
      opening PRs.
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
- **Ascent tags** as ids from the seeded `ascent_tag` table — **changed 2026-08-21, Kilian's
  call.** They were `ascent.tags text[]` with a GIN index, i.e. free text. A free-typed tag
  list is the one input in this product that grows without limit, and it fragments the
  moment it ships ('crimp' / 'crimps' / 'crimpy' / 'Crimpy'), so the aggregate it exists to
  serve — "what do I actually send on?" — returns four rows for one fact. It is a **lookup
  table plus a join** (`ascent_tag` + `ascent_tag_link`), not a native enum, because a tag
  carries a label and a picker grouping: that is CLAUDE.md's own "attributes or user-facing
  content" test, and it means adding a tag is a seed insert rather than an `ALTER TYPE`
  migration. Do not restore the array as "simpler"; see
  `server/domain/vocabulary.py::ASCENT_TAGS`.

#### ⚠️ The free-text inventory — ELEVEN fields, and three of them get forgotten

An earlier version of this section said "the only genuinely free-text fields are the diary
notes" and listed four. **That was wrong, and it was not a harmless undercount**: this list
is what binds "Notes are untrusted on OUTPUT too" below, and the PR #9/#10 request models
that need a `max_length` on every one of them. The two that were missing —
`logged_session.location` and `user_injury.note` — are exactly the two a reader would not
think of as "notes", and therefore the two most likely to reach a template unescaped or a
column unbounded.

| Field | What it is |
| --- | --- |
| `logged_session.notes` | how the session felt |
| `logged_session.location` | gym or crag name |
| `logged_set.note` | per-set ("felt easy, add 2 kg") |
| `ascent.name` | route or problem name |
| `ascent.notes` | beta, conditions |
| `journal_entry.body` | the free-standing diary entry |
| `user_injury.note` | what the injury is |
| `plan.name` | user-editable plan title |
| `planned_session.title` | user-editable session title |
| `invite.label` | who the invite is for ("Bob, from the gym") |
| `user_profile.display_name` | what to call the account holder on screen |

Plus **email and password** at registration. `invite.label` is the tenth and was missed by
the rewrite that fixed the count from four to nine — which is worth recording, because it
is the same undercount twice: it is written by an *operator* rather than by the account
holder, through `python -m server.admin create-invite`, so it does not feel like user input.
It is 64 characters of free text that reaches an API response and a rendered list, and both
halves of the rule bind it. **When you add a free-text column, add the row here in the same
PR** — this table has now been wrong three times, and each time the reason was that the new
field did not look like "a note".

`user_profile.display_name` is the eleventh, added by `0006` (issue #54), and it is the
counter-example that proves the rule is worth following: it is 64 characters
(`DISPLAY_NAME_MAX`, mirrored by `server/fields.py::DisplayName`), it is chosen by the
account holder, and it will end up rendered beside their training data on every screen that
greets them. Its bound strips whitespace and refuses an empty string, so "no name" has one
representation (NULL) rather than two — which also means **`PATCH` cannot clear it**: `null`
is "no change" on that endpoint, and `POST /api/profile/reset` deliberately does not touch it
either, because a display name is not one of the four onboarding steps.

That is the whole surface, and it is still small and well-known — keep it that way: if a new feature seems to want a free-text field,
check first whether it is really a closed set. Note that `exercise.name`,
`exercise.instructions` and `exercise.media_url` are **not** on this list: they are authored
reference content, written by the seed and never by a user. `ascent.name` deliberately
**stays** free text (Kilian, 2026-08-21) — a climb log without route names is not a climb
log — bounded at 120 characters and escaped on output like the rest.

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
- **⚠️ A 422 must never echo the request back**, and FastAPI's default handler does.
  `RequestValidationError.errors()` carries `input` for every error, so a too-short password is
  returned as its own error's `input`, and a **missing** field — a `register` call with no
  `invite_code` — has `input` set to the *whole body*, password included. It reaches the
  network panel, every proxy, and anything that logs a response.
  `server/app.py::validation_error_handler` is an **allowlist** (`type`, `loc`, `msg`) rather
  than a redaction pass, so a future Pydantic key carrying a value cannot leak through it;
  `ctx` is dropped too, because that is where the bounds live and the password policy is not
  something a 422 needs to publish. `tests/test_validation_errors.py` guards it, DB-free, so it
  runs in the local gate. Do not remove the handler to "get better validation messages".
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

> **⚠️ Migrate production BEFORE promoting, never after.** A promotion deploys code and runs
> no migration. Promote first and the new code runs against the old schema — one new mapped
> column breaks **every login**, not just its own feature. Order: dispatch `migrate.yml` at
> the ref that carries the revisions, confirm the applied revision, *then* merge the
> promotion PR. The gap in between is safe by design (expand → deploy → contract).
>
> **A promotion is not complete until the applied revision has been read back** — a separate
> `action: current` run against `production` — **and matches what the promoted code expects.**
> The upgrade run's own output is not that check: it reports what it believed it did, before
> the code shipped. Reading it back afterwards is what catches an upgrade dispatched at the
> wrong ref, a run that was approved but never finished, and a promotion that raced it.

Conventional Commits (`feat:`, `fix:`, `chore:`, `test:`, `docs:`); branches mirror
the type (`feat/…`, `chore/…`).

> **⚠️ `main` is the GitHub DEFAULT branch, not `dev`** (verified 2026-08-14,
> `gh repo view --json defaultBranchRef`). GitHub reads several things **only** from the
> default branch, so anything in that class needs a two-sided `dev` + `main` copy: so far
> `.github/workflows/*.yml` (`workflow_dispatch` registration), `.github/dependabot.yml`,
> and Dependabot **alerts**. This is the confusion behind the `migrate.yml` trap above.

---

## Dependency policy (set by Kilian, 2026-08-14)

**Pin every dependency to the latest stable version verified against the registry at pin
time — never one recalled from memory.** Check PyPI / npm in the same turn you write the pin.
This repo was scaffolded with `fastapi` 6 months, `starlette` 7 and `pytest` 9 months stale,
which produced 6 Dependabot alerts and turned a day-one patch bump into a 0.x→1.x migration.

Two exceptions: **runtimes track LTS** (Node 24, Python 3.13), and **`@types/*` match the
runtime major, not the newest** — `@types/node` is held at 24 via an `ignore` entry, because
type-checking against a runtime we do not run is a defect TypeScript accepts silently. The
TypeScript 6.x hold in the frontend rules is a capability decision, not a staleness one.

**A third exception, added by PR #7: a build-time-only tool with a vulnerable transitive dep does
not have to enter the install tree at all.** `@vite-pwa/assets-generator` regenerates the PWA
icons, which happens when the logo changes — roughly never. It depends on `sharp <0.35.0`, i.e.
four high-severity libvips CVEs (GHSA-f88m-g3jw-g9cj), and pulls ~200 packages that `npm ci` would
install on **every Vercel production build**. As a devDependency that is three permanent Dependabot
alerts (they cover devDependencies) against a repo currently at zero, bought for nothing. So the
npm script invokes it through a **version-pinned `npx --yes @vite-pwa/assets-generator@1.0.2`**,
and `web/pwa-assets.config.js` is plain JS with a string preset name so nothing has to resolve the
package's types. Reproducibility is kept by the exact pin plus the committed output (a re-run is
byte-identical). `npm audit`: **0 vulnerabilities**.

Generalise: **pin, but ask first whether a tool that runs by hand needs to be installed at all.**
The test is whether anything in `build`, `lint`, `typecheck` or `test` imports it.

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
  `content-type: application/json` is a 422. `apiFetch`'s `json` option sets it; a hand-rolled
  POST that sets only `accept` will 422 for reasons that look nothing like a header problem.
- **`httpx2` replaces the `httpx` + `starlette.testclient` pairing** before Starlette 2.0,
  where today's deprecation warning becomes an error. A package swap, not a version bump.

### `.github/dependabot.yml`

**Alerts alone open no pull requests** — which is why six stale-dependency alerts once sat
unnoticed with alerting fully enabled.

- **⚠️ The file is read from the DEFAULT branch only**, i.e. `main`: *"The `dependabot.yml`
  file must be present on the **default branch** … regardless of which branch you specify as
  the target."* **A copy on `dev` alone is inert**, the same failure as `migrate.yml` — see
  the default-branch rule under "Branch model". It carries **no comments** so the two copies
  cannot drift, which is why its reasoning lives here.
- **⚠️ Dependabot ALERTS are also raised against the default branch**, so a fix merged to
  `dev` does not clear an alert; it clears at the next promotion to `main`. Do not re-raise a
  still-open alert as if the fix had failed.
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

### ⚠️ Pinned actions Dependabot can never bump

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

Two processes — the API on 8000, the SPA on 5173 with Vite proxying `/api` to it.
**The commands live in [`README.md`](README.md), *Getting started*.** The rules are here.

**`dev:api` is what makes "local" mean local, and it is not optional.** `.env`'s
`DATABASE_URL` is **dev Neon**, so a bare `uv run uvicorn server.app:app` serves *dev* data
out of a local process — which is backwards (Kilian's rule: local runs against local, dev
against dev, production against production). The script therefore prefixes uvicorn with
`DATABASE_URL="${CT_TEST_DATABASE_URL:-}" DATABASE_URL_UNPOOLED=""`, exactly the trick
`check:server` already uses for pytest. Run the bare uvicorn command only when you *mean* to
target dev — and remember a seed added in a feature branch does not exist on dev until the
branch merges and a seed is dispatched, which is why #11a's demo mount showed a refusal at
sign-off while local Postgres had the row and every test was green.

Three facts make the prefix work, all in `server/settings.py::_load_local_dotenv()`: **only
`.env` is read** — `.env.local` is a Vite convention and the API never looks at it — **an
exported variable beats the file** (`override=False`), and the port must be **8000** because
`web/vite.config.ts` hardcodes the proxy target.

⚠️ **A local database means LOCAL ACCOUNTS ONLY.** Your dev-Neon account does not exist there
and registration is invite-gated, so a first login needs an invite minted against the local
URL — `DATABASE_URL="$CT_TEST_DATABASE_URL" uv run python -m server.admin create-invite
--label local` — or `server/devseed.py`'s ten accounts.

### Local Postgres for the test suite

**This section is `CT_TEST_DATABASE_URL`'s only explanation** — its value, its home in
`~/.zshrc`, the never-in-`.env` rule and `conftest.py`'s refusal of a non-local host. Every
other mention of it in this file is a command or a bare reference.

Native Homebrew **`postgresql@17`** — no Docker. It is **keg-only**, so its binaries live in
`/opt/homebrew/opt/postgresql@17/bin` and are **not on PATH**; `scripts/local-db.sh` addresses
them absolutely and so should anything else.

```bash
# ~/.zshrc — the one line that makes the DB-backed tests runnable
export CT_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/climb_trainer_test

npm run db:up      # start the server if down, create the DB if missing, `alembic upgrade head` — idempotent
npm run db:reset   # dropdb --force, createdb, upgrade to head
npm run check:server   # now RUNS the DB-backed tests instead of skipping them
```

⚠️ **The dev database and the test database are the SAME database**, because `npm run dev:api`
reads `CT_TEST_DATABASE_URL` too. So an account you register to click the app through leaves rows
behind, and the ~15 tests that assert a **global** row count then fail naming *profile
validation* — a red that points at the code rather than at the database. `tests/conftest.py`'s
`_refuse_a_polluted_database` now fails first with the real reason; the fix is `npm run db:reset`
plus `uv run alembic upgrade head`. CI never sees this: its Postgres is per-run and empty.

⚠️ **That export lives in `~/.zshrc`, which a NON-INTERACTIVE shell does not read.** Run the
gate from a script, a tool call or an agent's shell and the variable is unset, the Postgres
suite **silently skips**, and the gate is green for the wrong reason. Prefix it —
`eval "$(grep -h '^export CT_TEST_DATABASE_URL=' ~/.zshrc)"; export CT_TEST_DATABASE_URL` —
and then **confirm the skip count is 0**, because a bare "N passed" does not distinguish the
two outcomes.

The `postgres` role and database name deliberately match CI's `postgres:17-alpine` service, so
the same URL string is valid in both places and there is nothing to translate. The role is
created once, by hand; `db:up`/`db:reset` own everything after that.

**The URL lives in `CT_TEST_DATABASE_URL` and nowhere else — never put a database URL in
`.env`.** `.env` on this machine holds the *production* Neon URL and `server/settings.py` loads
it for every entrypoint, which is how a stray `alembic upgrade head` reached production's
neighbour on 2026-08-18 (see "Two connection strings"). So `scripts/local-db.sh` sets
`DATABASE_URL_UNPOOLED` **only** as a prefix on its own `alembic` command, with
`DATABASE_URL=""` beside it to stop python-dotenv (`override=False`) filling that one in from
`.env` — the same trick, inverted, that `check:server` uses.

**Both `scripts/local-db.sh` and `tests/conftest.py` refuse a non-local host, with no
override.** The check reuses
`server.db.is_local_host` so it cannot drift from `LOCAL_DB_HOSTS`, and it is handed the
**host**, never the URL: a URL bound to an argument or left as a frame local gets rendered in
a traceback, password included (see `server/db.py::host_of` — that cost 51 printed passwords
once). `require_migration_host` is **satisfied**, not bypassed — the host is genuinely local,
and `CT_ALLOW_REMOTE_MIGRATION` is never set outside `.github/workflows/migrate.yml`.

**The behind-head canary in `tests/conftest.py` is TWO lists, and a column-only revision needs
an entry.** It *skips* rather than fails when the database is reachable but behind head, because
migrations here are out-of-band behind an approval gate — being told to upgrade is useful, a
wall of red is not. `_REQUIRED_TABLES` cannot see a revision that adds no table: `0007` adds two
`exercise` columns and nothing else, the session-scoped `seeded` fixture writes one of them, so
against a database still at `0006` the table check passed and every DB-backed test **errored out
of a session-scoped fixture** instead of skipping. `_REQUIRED_COLUMNS` is the fix, on the same
discipline as the table list: **one canary per revision that adds only columns, and only for a
column a FIXTURE or a shared helper writes.** A column a single test reads stays out — that test
fails on its own and reads clearly.
⚠️ **Recorded honestly: this skip path has never executed in either environment.** It needs a
reachable database sitting at an older revision, and neither place can produce one — the local
gate pins `DATABASE_URL` empty so nothing connects at all, and CI runs `alembic upgrade head`
before pytest and then *fails the build* on any skip. The branch is reasoned, not observed;
treat a change to it as untested code and construct the state by hand if you need to trust it.

**Three Postgres majors move as one: local `postgresql@17` = CI's `postgres:17-alpine` =
Neon's major.** Bump one, bump all three in the same PR. A local pass on a different major
proves nothing about CI, and CI proves nothing about Neon.

### ⚠️ A dev server and the gate at the same time can blank every route — trigger UNCONFIRMED

**The symptom, the tells and the fix below are real and were hit on 2026-08-20. The mechanism
this section used to give is not.** It claimed `npm run check` → `npm run build` →
`npm --prefix web ci`, reinstalling `web/node_modules` under a running dev server. That chain
does not exist: `check` → `check:web` + `check:server`, and `check:web`'s `build` step is the
**web** package's own `tsc -b && vite build`. **Nothing in `check` runs `npm ci`.** Only the
**root** `build` script is `npm --prefix web ci && npm --prefix web run build`, and `check`
never calls it. Verified against both `package.json` files, 2026-08-26.

So what actually invalidated the dev server's optimized deps is **not established**. The two
candidates, neither confirmed: a `vite build` sharing `web/node_modules/.vite` with a running
dev server, or a separate `npm ci`/`npm install` (the root `build`, or a Vercel-style build run
by hand) around the same time. **Do not substitute a fresh guess for the old one** — if you
reproduce it, record what you actually ran.

The symptom: the next page load dies in `node_modules/.vite/deps/…?v=<hash>` with
`TypeError: Cannot read properties of undefined (reading 'd')` at `createRoot`, and **every**
route renders blank — including unguarded ones — while the HTML still serves **200** with
`#root` present.

Fix: **stop the dev server, `rm -rf web/node_modules/.vite`, restart it, hard-reload.**

**The diagnostic is worth more than the fix, because this looks exactly like a bug in whatever
you just wrote.** Two tells, both cheap:

- **A blank *landing* page.** Feature code almost never blanks an unguarded route; a broken
  dependency graph blanks all of them at once.
- **Matching `react` / `react-dom` versions plus a `web/package-lock.json` older than your
  branch.** Then nothing about your changes can explain it, and the stack frame pointing into
  `.vite/deps` with a `?v=` hash is the confirmation.

Hit on 2026-08-20, once. Treat "the gate and a dev server running together" as the risk
surface and stop the dev server before a full gate — that costs nothing and needs no confirmed
mechanism.

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

**One command, and it is the nine checks CI runs on the code:**

```bash
npm run check          # == check:web && check:server
```

Or the halves / individual checks:

```bash
npm run check:web      # format:check -> lint -> typecheck -> build -> test
npm run check:server   # ruff check -> ruff format --check -> mypy -> pytest

npm --prefix web run format:check   # Prettier
npm --prefix web run lint           # ESLint (type-aware — see the TS 6.x note)
npm --prefix web run typecheck      # tsc -b (strict)
npm --prefix web run build
npm --prefix web run test           # Vitest once — AFTER the build, see below
uv run ruff check .
uv run ruff format --check .
uv run mypy                         # strict; files come from pyproject.toml
CORS_ORIGINS=http://localhost:5173 uv run pytest -q
```

**`build` runs BEFORE `test`, in both the local gate and CI (issue #26).** `vite build`
regenerates `src/routeTree.gen.ts` and several tests assert against that tree, so tests
should read a freshly generated one rather than whatever happens to be committed. **In CI
the route-tree freshness check still runs after the build**; only `test` and `build` swapped.

**What the swap does NOT do is turn a silent green red — measured.** A renamed lazy leaf
fails under *both* orders; the gain is purely diagnostic (see the lazy-leaf rule under
"Routing: one tree, two histories" for the two failure shapes), plus the ordering dependency
`web/src/publicRoutes.test.ts` had to work around is gone. If you are looking for a case
that was silently green before and is red now, there isn't one in today's suite; do not
claim otherwise.

Cost: nothing on a green run, since `npm run build` already runs `tsc -b`. On a **red** run
every test failure now waits out a full build first, locally as well as in CI.

**The local gate passes with no database, and `check:server` now ENFORCES that rather than
hoping for it.** `tests/conftest.py` skipping the DB-backed tests when `DATABASE_URL` is unset
is not the same as the gate being database-free: `.env` is loaded for every entrypoint, so on a
machine with real Neon credentials in it the "local" gate quietly ran the 102 DB-backed tests
**against the live dev database** — ~37 s of woken Neon compute per run. So `check:server`
overrides both URLs, and the two are **deliberately not symmetrical**:

```jsonc
DATABASE_URL="${CT_TEST_DATABASE_URL:-}" DATABASE_URL_UNPOOLED=""
```

- **Locally** both are empty and nothing connects — a skip is visible, a silent connection to
  someone's real database is not. Opting in means exporting `CT_TEST_DATABASE_URL` and running
  `npm run db:up` once; see "Local Postgres for the test suite" for both variables' rules and
  "Two connection strings" for why the direct URL has no opt-in.
- **CI** runs `uv run pytest -q` directly against its `postgres:17-alpine` service, so it never
  goes through this script and always runs the full set. **Never weaken a DB-backed test on the
  assumption that nothing runs it, and never make the gate *require* a database** — and never
  substitute SQLite to dodge the skip. CI is where the migrations and the seed are executed.

**Batch your edits and run `npm run check` once at the end**, not once per file.

**⚠️ `.gitleaks.toml` exists, and `useDefault = true` is the only line in it that matters.**
The generated `web/src/api/schema.ts` header carries two SHA-256 digests, and gitleaks'
`generic-api-key` rule reads `openapi-sha256: <64 hex>` as a credential ("openapi" contains
its `api` keyword; measured entropy 3.675) — a false positive that failed the `secrets` job on
PR #53. The config allowlists **that line shape**, by content: a `paths` entry would allowlist
the whole generated file, because `gitleaks-action@v3` runs **8.24.3**, whose allowlist struct
has no condition field and therefore ORs its criteria. **A config without `[extend] useDefault
= true` REPLACES the default ruleset** — every rule gone, scanner green on everything, which
is why `tests/test_gitleaks_config.py` asserts both properties and why the config was verified
by planting an `AKIA…` key inside `schema.ts` and confirming it was still reported. Never
weaken the digest header to satisfy a scanner; it is the codegen freshness guard.

**CI has three required jobs: `web`, `server`, and `secrets`** (gitleaks over full
history). Kilian's call: **require all three** rather than collapsing them into a single
`lint-build` gate as the other repos do — three named checks say *what* broke on the PR
page, and a leaked-secret failure should never be indistinguishable from a lint failure.
If you read "one required check named `lint-build`" in the original plan, that wording
is superseded.

`npm run check` covers `web` + `server`. **The local gate is 9 checks and CI is 14** — the
same 9, plus five that only make sense there: gitleaks (not a project dependency),
`alembic upgrade head` and `alembic check` against the `postgres:17-alpine` service
container, and the two-step `src/routeTree.gen.ts` freshness check. Don't try to fake the
Alembic ones locally; just never commit a secret, and let CI prove the migrations.

**Why the route-tree check is CI-only, deliberately.** It compares the worktree with the
index, which in CI equals the commit — so it means "the committed tree was stale". Locally
it would mean "the regenerated tree differs from what you have staged", which is the normal,
correct state of any branch that adds or removes a route file and, per the standing
convention, leaves its changes unstaged for review. Adding it to `check:web` would therefore
turn the local gate red on ordinary route work, which trains people to ignore it. **The
residue is real and worth knowing: `npm run check` still rewrites `src/routeTree.gen.ts` in
place and says nothing** — so after a route change, look at the file in source control
rather than trusting a green local gate.

**The job names `web`, `server` and `secrets` are required status checks in a GitHub
ruleset. Renaming one silently breaks the merge gate** — the rule waits forever for a
check that will never report. Add steps to a job freely; never rename a job.

`web/src/test/setup.ts` is where jsdom stubs for the device APIs go as they arrive
(`navigator.wakeLock`, `AudioContext`, `navigator.vibrate`, `navigator.onLine`),
mirroring the `matchMedia` convention in `portfolio-shell/src/test/setup.ts`. The
clock tests need fake timers plus a `performance.now` shim.

### ⚠️ Prose is capped, and an executable claim must not be prose

**The hierarchy, in order. Only reach the next tier when the one above cannot hold the claim:**

1. **Make the wrong thing impossible** — a constraint, a type, `extra="forbid"`, a `Literal`.
2. **Make it fail loudly** — a guard test, shown to fail before it is trusted.
3. **Only then prose**, for *why* only, in exactly one place, at the point of use.

**Five caps, enforced by `tests/test_comment_budget.py`:** module docstring **10** ·
class/function docstring **2** · inline `#`/`//` run **2** · `/* */` block **2** ·
wire-contract docstring **20** (FastAPI ships those to API consumers, who cannot read the code
instead). Over-cap is allowed **only** with a row in `tests/comment_budget_allowlist.toml`
naming what the length buys; that file is the register of exceptions and its `BASELINE_RATCHET`
may only ever go down.

**After every PR, re-check the `CLAUDE.md` section covering what you touched** — confirm it
still holds, or update it in the same PR. `.github/pull_request_template.md` carries the
receipt, and `tests/test_claude_md_claims.py` catches only the mechanical half (paths, scripts,
revisions, headings, env vars), never a reason that has gone stale.

**What prose is still irreplaceable for, so this does not get over-applied:** *why* a choice
beat a plausible-looking alternative · what was tried and failed · facts about the world outside
this repo (a library's source, a platform's behaviour, a vendor's docs). The canonical case is
the backref-cascade trap under "Persisting a plan": nothing in the code, the schema or 581
passing tests reveals that the nicer-reading form silently drops ~2,400 rows and returns **201**.
**A rule with no reason attached gets simplified away by the next well-meaning change** — that is
the premise of this whole file, and it is the boundary of the rule above, not an exception to it.

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
  route-enumeration auth and demo-mode tests, and **`/api/library`'s pinned field list**
  (`tests/test_library_contract.py`), whose failure mode is invisible to every behavioural
  test *by construction*: a shared-cache leak happens between two requests in an intermediary
  this repo does not run, so a literal list going red on the diff is the only guard available.
  **Two more of the same shape guard the PROSE**, which nothing else in the gate reads:
  `tests/test_comment_budget.py` (no comment outgrows its tier's cap without a registered
  reason) and `tests/test_claude_md_claims.py` (every path, script, revision, heading and env
  var `CLAUDE.md` names still resolves, and the index resolves in both directions). Both are
  named here because a guard nobody lists is a guard the next reader deletes — see "⚠️ Prose is
  capped, and an executable claim must not be prose" for what neither of them can catch.

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

### ⚠️ A guard test must be SHOWN to fail before it is trusted

Not a style note — a requirement, and the reason every guard in this repo carries a positive
control. Break the thing it guards, watch the test go red, restore, watch it go green, and put
the captured failure in the PR. `test_migrations_additive.py`'s own docstring says it plainly: a
detector nobody has seen fail is a detector nobody should trust, and a control assembled from the
constant it tests would cheerfully confirm a typo to itself.

### ⚠️ A class name in markup with no CSS fails SILENTLY — `styles/markupCss.test.ts`

The newest guard, and it earned its place the hard way: **twice** during #54's prototype a
scripted rewrite of `_profile.scss` replaced the span between two comment markers and swallowed
unrelated rules with it. Twelve `ct-app__*` classes were left in the markup with nothing behind
them — the select chevron vanished, the checkboxes rendered as bare native controls, the sliders
lost their row layout, the disclosures lost their panel styling, the grade warning lost its
colour — and **`tsc`, ESLint, `designGuard` and `contrast` were all green the whole time.**
Nothing in the gate could see it, because a missing rule is not a type error, a lint error or an
unscoped selector.

So it asserts both directions: no class used in `web/src/**/*.tsx` is missing from the compiled
stylesheet, and no `ct-app__*` selector in the stylesheet is unused by any markup (dead CSS).
Two notes for whoever touches it:

- **It compiles the Sass in-process** rather than scanning the partials. Source `.scss` uses
  `&__suffix` nesting, so the literal `ct-app__choice` appears nowhere in it; and reading `dist/`
  would need a production build, which the local gate must not require.
- **Interpolated class names are its one blind spot.** `` `ct-app__bento--${area}` `` trips both
  directions at once, so it carries the narrowest possible allowlist with a comment saying why —
  the same discipline as `test_migrations_additive.py`'s arm 6, where a false positive costs a
  developer a minute and a false negative costs production.

## UI design direction

`web/src/styles/` is the design system. `@use`-based partials, no `@import`:

| File | What it owns |
| --- | --- |
| `_tokens.scss` | every token, as a `@mixin declare` — see "why a mixin" below |
| `_mixins.scss` | `tap`, `focus-ring`, `press`, `safe-inset-block-end` |
| `_layout.scss` | the page frame: the reading measure as a grid column, plus the full-bleed escape |
| `_primitives.scss` | button (3 variants), input, field, error, badge, text primitives |
| `_card.scss` | the card surface and its `@container` rules |
| `_bento.scss` | the bento grid's named areas |
| `_chrome.scss` | nav (the brand, the three regimes and their measured thresholds), status renders, bottom-anchored action bar |
| `_landing.scss` | the landing page's photographic bands, detail split and icon rules |
| `app.scss` | the `@use` entry and the `.ct-app` root; imported from `routes/__root.tsx` |
| `global.scss` | the document reset. `main.tsx` only, and the ONLY file allowed `:root` |
| `update-bar.scss` | the PWA update bar. `ui/UpdateBar.tsx` only, i.e. standalone only |

Guiding principle, in Kilian's words, and still the tie-breaker: **"we prefer useful than
looking pretty."** When a visual flourish and legibility disagree, legibility wins without
discussion. The look is bento-box cards, generous targets, honest depth; calm by default —
a tool, not a dashboard.

**Two tests hold the parts a future agent would otherwise "helpfully improve"**, and both
carry positive controls because a silent detector is worse than none:

- `styles/contrast.test.ts` parses the hex out of `_tokens.scss` per scheme and asserts every
  documented text-on-surface pair at **4.5:1** and the control outlines at 3:1. It reads the
  **source text**, because `vitest.config.ts` sets `css: false` and there are no computed
  styles to read. It also asserts the two schemes declare the *same keys* — a token added to
  light only keeps its light value in dark mode, which is how an unreadable surface ships while
  every pair still passes.
- **`distContract.test.ts` is the one that matters for scoping.** It derives the stylesheet the
  federated mount loads by walking the import graph from `dist/remoteEntry.js` (there is no
  `mf-manifest.json` to read — checked) and asserts that **every** selector list in it begins with
  `.ct-app`, with no `:root` and no `position: fixed`. It reads `dist/`, so it needs `build` to have
  run, and it **fails loudly rather than skipping** when it has not. That ordering dependency is
  justified where `publicRoutes.test.ts`'s was not: this invariant is a property of *which bundle a
  declaration lands in*, which no source file states.
- `styles/designGuard.test.ts` scans the sources, recursively, for `backdrop-filter`, `:root`
  outside `global.scss`, `@import`, and an inline `position: 'fixed'` in any `.tsx`. **There is no
  stylelint in this repo**, so this is not a lint rule restated — but it is explicitly *not* the
  scoping guard: a per-file scan cannot see `@use`, and it stayed green while `@use 'global';` in
  `app.scss` pushed `:root` into the remote's CSS. What it adds is reach into files no bundle
  contains yet, and into React style props, which never become CSS. It strips comments first — the
  reasons for these rules are written in the files being scanned, so every detector would otherwise
  fire on its own prose.

### Glassmorphism: considered and REJECTED (2026-08-12)

**Do not use `backdrop-filter`. Do not reintroduce translucent "glass" surfaces anywhere,
including as a subtle accent on chrome or cards.** This was explicitly evaluated and rejected
by Kilian on 2026-08-12 — it is a closed decision, not an oversight for a future agent to
helpfully improve. `designGuard.test.ts` now fails the build on it.

Why: `backdrop-filter` forces a separate compositing layer and a blur pass every frame,
which is **GPU- and battery-expensive on a phone that is awake and in use partway through a
training session**. And translucency is straightforwardly *worse* at the one thing that
matters most here — being readable at arm's length, with sweaty or chalky hands, in bad gym
lighting.

**Tactility comes from OPAQUE ELEVATED SURFACES instead**, which is what shipped:

- **A four-step opaque surface scale** — `--ct-bg`, `--ct-surface-1..3`, plus `--ct-hover`
  and `--ct-pressed`. Elevation is a distinct surface *colour*, never content showing through.
  `--ct-bg` doubles as the **sunken** tone (inputs, image wells): it is the furthest surface
  from a card in both schemes, so one token reads as "inset" in light and in dark.
- **A hairline per surface** (`--ct-border-bg`, `--ct-border-1..3`), because one border tone
  reads as a smudge against white and as nothing at all against the page background. Plus
  `--ct-border-strong` for control outlines, which carries real 3:1 non-text contrast.
- **Real `:active` and `:focus-visible` on every interactive affordance**, via
  `_mixins.scss`'s `press` and `focus-ring`. The single biggest contributor to the app
  feeling tactile, and it costs nothing to render.
- **A three-step shadow scale** (`--ct-shadow-1..3`) and no fourth — card, nav, floating update
  bar. Honest depth: a shadow here means real elevation, and the alphas are **measured**, not
  guessed. Composited over `--ct-bg`, step 1 is **1.22:1** against the bare page; at the 0.06 it
  first shipped with it was 1.13:1, i.e. paint work nobody could see.
- **⚠️ In dark mode all three shadow tokens are `none`, by arithmetic.** `--ct-bg` is `#0d0f12`,
  relative luminance 0.0056, so the *best* contrast any shadow can reach over it is
  **1.09:1** — `(0.0056 + 0.05) / 0.05`, with fully opaque pure black. A blurred shadow at a
  realistic peak alpha lands at 1.04–1.06:1. The first draft of PR #7 shipped a "reduced dark
  scale" that measured 1.05–1.07:1: three GPU-costing steps rendering as nothing. Dark elevation
  therefore rests on the surface scale and the hairlines alone, and the floating update bar carries
  `--ct-border-strong` (4.2:1 non-text) instead. **If you re-add dark shadows, measure them
  first** — and note the only way to make them work is to lift `--ct-bg`, which re-opens every
  dark contrast pair.

### Accessibility is part of the design, not a later pass

- **`prefers-reduced-motion`** guards every transform and transition. `press` puts the colour
  change **outside** the guard and the transform **inside** it, deliberately: reduced motion
  is not reduced information, so the tap is still acknowledged, just instantly. Deleting the
  whole rule under the guard would leave a tap unacknowledged.
- **WCAG AA 4.5:1**, asserted per scheme by `contrast.test.ts`. On opaque surfaces this is
  decidable from the tokens, which is one of the practical benefits of having dropped
  translucency.
- **`--ct-tap: 44px`, applied on BOTH axes** by `_mixins.scss`'s `tap`. A block-size floor
  alone leaves a tall unhittable target — "Plan" is only ~31px wide on its own.
- **Primary actions are never in a top corner**, and `ct-app__actionbar` groups them at the end of
  a form behind a hairline, stretched to full width for the thumb. ⚠️ **It does not anchor
  anything to the bottom of the VIEWPORT.** It shipped as
  `position: sticky; inset-block-end: 0`, which is inert as the last child of a content-sized form
  — measured, the login submit sat ~300px above the fold with no scroll at all — so the sticky and
  the `env()` floor were removed rather than left looking load-bearing. Real anchoring needs
  `position: fixed` or `100dvh`/`100svh`, and **both resolve against kilianmc.com's viewport in the
  federated mount**, because the route tree is shared. It therefore belongs to the session player
  (planned PR #15a), the first genuinely full-height screen, which needs a mount-aware height
  decision anyway. `env(safe-area-inset-*)` under `max()` floors is in use on `.ct-app`'s own
  padding and on the update bar, which may be `fixed` because `main.tsx` alone renders it.
  `viewport-fit=cover` is already set in `index.html`.
- **⚠️ No `position: fixed` and no viewport units anywhere the route tree can reach.** Both mounts
  share that tree, and in the federated mount both resolve against **kilianmc.com's viewport** — a
  `fixed` element would float over the portfolio's own chrome. Both are allowed only in the
  `main.tsx`-only subtree, which is why the PWA update bar may use `fixed` and `_chrome.scss` may
  not. Asserted on the built remote stylesheet by `distContract.test.ts`; inline
  `style={{ position: 'fixed' }}` in a component never becomes CSS, so `designGuard.test.ts` scans
  the `.tsx` sources for that separately.
  ⚠️ **The viewport-unit half of that rule had NO detector at all until PR #9** — three guards
  covered `position: fixed` from two directions and nothing looked for `vh`/`vw`/`dvh`/`svh`.
  `designGuard.test.ts` now greps every stylesheet for them, with **no exemption**: neither
  `main.tsx`-only sheet wants one today, and a dead exemption is worse than none (add one, with a
  control, the day the update bar needs `100dvh`). **The `.tsx` sources are scanned too**, with
  `sizes="…"` stripped first: an inline `style={{ blockSize: '100vh' }}` never becomes CSS and
  would otherwise pass the whole gate, while the two `sizes="100vw"` hints on `<LandingPicture>`
  are resource selection — they can fetch one rung too many in the shell, they can never move a
  box. **The pattern needs a digit next to the unit, so anything COMPUTED slips past** —
  `#{$h}vh` in Sass, `` `${h}vh` `` or `'100' + 'vh'` in a component — and for the `.tsx` half
  there is **no backstop at all**, because an inline style never becomes CSS and
  `distContract.test.ts` scans built CSS for `fixed` and not for units. (An earlier version of
  this paragraph claimed `distContract` covered it. It does not.) What IS greppable and is now
  guarded is the same bug in JavaScript: **`window.innerHeight` / `innerWidth` /
  `visualViewport` in a component**, which is how a "full height" screen gets built in React
  and which measures kilianmc.com's window in the federated mount.

### The reading measure is a GRID COLUMN, not a `max-inline-size` on `.ct-app`

Changed by the landing redesign, and it is the enabling change for it — read `_layout.scss`
before reverting any of it.

`.ct-app` used to carry `padding-inline` + `max-inline-size: 46rem` + `margin-inline: auto`
itself. **Nothing inside a box like that can reach the edge of the screen**, and the landing
page has to: escaping a `max-inline-size` from the inside means knowing the distance to the
edge, and the two ways of expressing that — `margin-inline: calc(50% - 50vw)` and
`position: fixed` — are both banned here for the reason the accessibility section gives.

So `.ct-app` and `.ct-app__main` are both `display: grid` with

```text
[ct-bleed-start] gutter | [ct-measure-start] measure [ct-measure-end] | gutter [ct-bleed-end]
```

children default to `ct-measure`, and `.ct-app__main > .ct-app__bleed` spans `ct-bleed`.
**Nothing in that template refers to anything outside the grid container** — the only relative
unit is `100%`, i.e. the container's own inline size — so it is correct in both mounts with no
branching, and unlike the `50% - 50vw` idiom it cannot produce a horizontal scrollbar.

- **Two levels, because a grid does not reach through a child.** `.ct-app` places the nav in the
  measure and `<main>` in the bleed; `<main>` re-establishes the same grid for a route's own
  children. A landing section is a child of `<main>`, not of `.ct-app`.
- **App screens are unchanged to the pixel.** The measure column is
  `min(--ct-measure, 100%)` **minus both gutters**, which reproduces the old content box exactly:
  704px at a 1440px viewport, 358px at 390px.
- ⚠️ **One real difference: `container: ct-app` now measures the full available width**, not the
  capped 46rem content box, so the `34rem` thresholds in `_card.scss`/`_bento.scss` are crossed
  ~32px of viewport earlier (two-column bento at 544px instead of 576px). Left uncompensated
  deliberately — `ct-app` now means "how much room the app got", which is what those queries
  ask — and it changes nothing in the federated mount, where the cap never bound.
- **`&__prose` is `56ch`, and the number is MEASURED — do not "fix" it up to the usual
  `65ch`.** `ch` is the advance of "0", wider than average prose, so `Nch` always holds more
  than N characters: `68ch` measured **80–90 actual characters** in Chrome, past the upper
  bound. The landing page's problem was diagnosed as *missing content, not missing CSS*: it
  contained zero images. The fix is full-bleed imagery with a ~65–75 character text column,
  **not** a wider `max-inline-size`. Only the landing page breaks out.

### Landing imagery — self-hosted, generated out-of-band, and URL-resolved at runtime

- **`img-src 'self' data:` means every image is bundled and every icon is inline SVG markup.**
  `ui/icons.tsx` — never `<img src="…svg">`, which is both a blocked external fetch and a glyph
  that cannot inherit `currentColor`. Every icon is `aria-hidden` + `focusable="false"` and has a
  text label beside it; icon-only controls are deferred to the session player, per the same
  reasoning as the update bar's "Later" button.
- **`src/publicUrl.ts` is the image half of the `web/src/api/client.ts` bug.** A bare
  `src="/landing/x.avif"` resolves against the DOCUMENT, which in the federated mount is
  kilianmc.com — every photograph 404s there while working perfectly standalone. So the origin
  comes from `import.meta.url`, exactly as `API_BASE` does. Vite-`import`ed assets would be
  content-hashed but emitted as absolute `/assets/…` paths, i.e. the broken form; CSS `url()`
  resolves correctly cross-origin but cannot express a `srcset`. Hence `public/` + a runtime
  origin. **No CORS header is needed** — an `<img>` without `crossorigin` is not a CORS fetch, and
  `mf-contract.test.ts` asserts the ACAO wildcard appears on `/remoteEntry.js` and `/assets/*`
  and nowhere else.
- **`web/scripts/gen-landing-images.mjs` is an authoring tool and must never enter `build`.** The
  originals are 12–22 MB and live outside the repo; the derivatives are committed, because CI and
  Vercel build from a clone with no photo library. `sharp` is a devDependency (0.35.x, i.e. past
  the libvips CVEs that keep `@vite-pwa/assets-generator` out of the tree).
- **The ladder lives in `src/ui/landingImages.ts` and the script imports that same file** (Node 24
  strips the types natively). One source of truth, because a rung listed in one place and emitted
  in the other is a silent 404 on the candidate a wide screen picks — `srcset` is a string and
  `<img>` fails quietly. `src/ui/landingImages.test.ts` asserts the ladder and
  `public/landing/` describe each other in **both** directions (a missing file, and an orphan left
  by a shortened ladder).
- ⚠️ **`rope-detail`'s original is 960x640 and there is no larger one.** Its ladder stops at 960
  and its layout slot is capped at 22rem/16rem so no slot can demand more; the generator throws
  rather than upscale.
- **The one `100vw` on the landing page is in a `sizes` attribute**, which is resource selection,
  not layout. In the federated mount it over-estimates and may fetch one rung more than needed —
  bytes, never geometry.
- ⚠️ **No text over a photograph on this page, and the scrim that made it possible is deleted.**
  The effort band shipped first as white copy over `chimney-effort` behind a scrim. Measured in a
  real browser — scrim off, glyphs transparent, worst pixel in the text's own box — the lightest
  scrim clearing 4.5:1 was **alpha 0.56 at every container width from 420px to 1440px**, and
  `object-position` bought nothing below ~1400px because until then the band is narrower than the
  photograph is wide, so there is no spare frame to move. A 0.56 scrim leaves a photograph nobody
  can see, which defeats the point of adding photographs. **Kilian's call: media above, copy
  below.** The copy now inherits `--ct-fg` on `--ct-bg`, which `contrast.test.ts` already proves in
  both schemes, and there is no contrast question left. Do not reintroduce it.
- **The effort band's frame is deliberately TALL, and `4 / 5` is also the aspect the derivatives
  are CUT to.** A crop taller than the original's ratio makes **height** the binding constraint on
  the ladder (its 1920px rung needs 2400px of source height from 3840), which is why
  `landingImages.ts` declares `sourceSize` per image, the generator asserts that declaration
  against the real file, and the ladder test enforces the no-upscale rule **in both dimensions** —
  in CI, where the originals do not exist. A width-only check was the earlier, weaker version.
- **`landingImages.test.ts` also asserts `public/landing/` holds nothing but derivatives.** The
  credits file lived there once; anything under `public/` ships in the app and is a precache
  candidate, so provenance moved to `web/PHOTO-CREDITS.md` and this keeps it from drifting back.

### Container queries, not media queries — and tokens on `.ct-app`, not `:root`

Both of these are structural, not stylistic. Do not "simplify" either.

- **`@container`, not `@media`,** for anything whose right answer depends on how much room
  the app got. The same card renders in the **full-width standalone app** and in the **much
  narrower federated mount** inside the shell's `ProjectViewer`; a media query asks about the
  *viewport*, which in the federated case is kilianmc.com's, not the card's. So `.ct-app`
  declares `container: ct-app / inline-size` (the bento's arrangement and the cards' padding
  ask it) and each card declares `container: ct-card / inline-size` (its own internals ask
  that). One component, two mounts, no mount-specific branching.
  - **An element cannot query the container it establishes itself.** A card's padding is
    therefore an `@container ct-app` rule, and only its *descendants* may ask `ct-card`.
    Writing `@container ct-card { .ct-app__card { … } }` compiles, matches nothing, and
    silently does nothing.
- **The bento is CSS grid with NAMED AREAS**, not `auto-fit`/`minmax`: the arrangement per
  breakpoint stays reviewable in one place, and it lets visual order change without touching
  DOM order — which matters because DOM order here is frozen by tests.
- **Tokens live on `.ct-app`, never `:root`** — in the federated mount `app.scss` is injected
  into kilianmc.com's document.
  - **Why a Sass mixin rather than a rule:** the PWA update bar is rendered from `main.tsx`
    as a *sibling* of the router (it must be — see the service-worker rule), so it sits
    outside `.ct-app` and inherits nothing. `_tokens.scss` therefore exposes
    `@mixin declare`, included by both `.ct-app` and `.ct-update-bar`. A second `.ct-app`
    element is **not** the fix: that element's padding, max-width and background would apply.

### ⚠️ The nav's thresholds are MEASUREMENTS, not breakpoints

`web/src/styles/_chrome.scss` carries **the table** — five numbers with the content-width
arithmetic behind each — directly above `&__nav`. **Read it there rather than duplicating it
here**; a table in two places is a table that disagrees with itself. What belongs in this file
is why it is shaped that way at all:

- **Every threshold is derived from what the row actually needs**, in px of nav content, and
  then rounded up to the next `rem` **plus slack for the estimate error** (glyph advances here
  are ±5%, which is ±8px on the wordmark and ±25px across five labels). Kilian's rule, in his
  words: "make the buttons appear as soon as they fit, so no 765, if they fit at 600 do it
  there." A conventional 768/1024 pair was explicitly rejected.
- **They are CONTAINER widths, not viewport widths.** `container: ct-app` measures the app, and
  in the federated mount the app is a panel inside kilianmc.com's `ProjectViewer` — so the px in
  brackets is the standalone reading and is approximate by design. That is the whole reason
  these are container queries.
- **The two variants have their own pairs.** The anonymous nav has three destinations and no
  Log out; sharing the authenticated numbers made it wait for ~130px it does not need and show
  its icons ~9rem late. One Sass mixin, two includes — the numbers differ per variant and the
  rules must not.
  ⚠️ Per-variant *thresholds* are not the same thing as the per-variant *centring* that was
  reverted: Kilian did not want the group centred, and both variants stay right-aligned.
- **The tooltip band is derived from the icon threshold**, as `[$icons, $labels − 0.001rem]`.
  Container ranges are INCLUSIVE, so the upper bound has to exclude the label threshold, and
  `and not (…)` is not valid syntax in a container condition (`not` may only lead the whole
  condition). If you move a threshold, the band moves with it — that is why it is computed
  rather than written twice.
- **One query is deliberately INVERTED.** The label is inline by default and becomes a
  hover/focus bubble inside the band, because `_card.scss`'s rule is that a box matching no
  query must get the *safe* outcome — a cramped but labelled nav is fine, six unnamed glyphs are
  not.
- ⚠️ **An icon-only control owes two things** (`ui/icons.tsx` sets them): its own `aria-label`,
  and the 44px `--ct-tap` floor on both axes. `&__button--icon` trims the inline padding for all
  three of them in one declaration — `&__button`'s padding is sized for a word, and on a 24px
  glyph it makes a button visibly wider than it is tall.
- **Touch gets neither hover nor focus**, so on a phone the glyph is the only carrier of meaning
  and the `aria-label` is the only channel for anyone who cannot see it. That is what makes the
  glyph choice load-bearing rather than decorative, and why two of them were redrawn for
  silhouette rather than concept (a landscape week-strip so Plan stops looking like Diary's
  upright rules; a wider gap on the power ring so Log out stops looking like Session's clock).

**`--ct-nav-compress` is a RATIO, and it is local on purpose.** Below the tightest threshold
every reduced value is `calc(<the token it replaces> * var(--ct-nav-compress))`, so the narrow
bar moves as one and nothing drifts off the space scale when that scale is retuned. It lives on
`.ct-app__nav` in `_chrome.scss`, **not** in `_tokens.scss`: that file is the design system's
vocabulary, every entry in it is consumed by many components and `contrast.test.ts` parses its
two scheme mixins key-for-key, whereas this is one component's parameter. It is on `.ct-app__nav`
— inside `.ct-app`, never `:root` — so the brand inherits it as a child. Note the consequence
of "a fraction of the token it replaces": the values it produces are **not all equal** (a
`--ct-space-4` inset becomes 0.4rem, a `--ct-space-3` gap becomes 0.3rem), and that is the
intended reading. Gaps that go to *zero* are written as `0`, not as a ratio — a fraction of
something that becomes nothing is not a fraction.

### Light and dark: the `data-theme` override, and two gaps that are documented rather than fixed

`web/src/theme.ts` is the store; `_tokens.scss` has the mechanism. Two states, sun and moon, no
"System" position — the first visit seeds from `prefers-color-scheme` through `matchMedia`, and
after that it is a plain toggle. The cost is accepted and stated: once a choice is stored,
changing the OS scheme no longer moves the app.

**How the override wins, and why it needs no `!important`:** `_tokens.scss::declare` emits the
light values plus a `@media (prefers-color-scheme: dark)` block. **A media query carries no
specificity**, so an attribute selector on the same element beats both blocks whatever the source
order — which is the entire mechanism. `overrides` is therefore a *separate* mixin from `declare`
and is included by `.ct-app` only, never by `.ct-update-bar`: nothing sets the attribute on the
update bar, which is rendered from `main.tsx` outside the router. The attribute goes on `.ct-app`
and nowhere else — not `<html>`, not `<body>`, which belong to kilianmc.com in the federated
mount. `global.scss` bridges the standalone document canvas with `body:has(.ct-app[data-theme…])`,
which is legal *there* because that file never ships to the shell.

⚠️ **Two known gaps. Kilian's call: documented, not fixed.** Neither is a correctness bug, and
both are recorded in `theme.ts` for the next person:

1. **`index.html`'s two `theme-color` metas follow the OS, not the override**, because they select
   with `media="(prefers-color-scheme: …)"`. Closing it needs JS (a meta tag cannot read a
   `data-` attribute) and that JS must be standalone-only, since in the federated mount the
   document head belongs to the portfolio. Not worth that machinery for a strip of browser UI.
2. **The choice cannot be applied before first paint.** The usual fix is a blocking inline
   `<script>`, and CSP here is `script-src 'self'` with no `unsafe-inline` — the right response to
   which is not to weaken the policy for a flash. One light frame before React mounts, and what
   flashes is the document canvas rather than any app surface.

Also worth knowing: **`.ct-app` carries `isolation: isolate`**. The nav needs a `z-index` for its
sticky bar, its burger panel and its label bubbles; that one declaration means no index inside the
app can ever escape into the shell's stacking context.

⚠️ **`position: sticky` is not forbidden the way `fixed` is, but it resolves against the nearest
SCROLLING ANCESTOR** — and this stylesheet ships to two of them. Verified in the shell's own
source rather than assumed: `portfolio-shell/src/components/ProjectViewer.scss` sets
`.viewer__frame { flex: 1; overflow: auto; }`, so in the federated mount the nav sticks to the top
of that panel, which is where it should stick; standalone, nothing scrolls above it, so it is the
document. Both are right. Note the difference from the inert `sticky` that was removed from
`&__actionbar`: **a sticky element's range is its containing block**, which for the nav is the
whole page and for that action bar was a content-sized form (range ≈ 0).

## Onboarding and the profile (PR #9, redesigned by #54)

Four steps, one decision each, in a fixed order; the same field groups serve the wizard
(`/onboarding`) and the editor (`/profile`). `web/src/profile/` is the client half and
`server/profile/routes.py` the server half, and both carry their reasoning. What follows is
what a reader would otherwise undo.

⚠️ **Issue #54 rebuilt this after Kilian walked PR #53.** It was five steps; what changed, and
why, is recorded in the bullets below rather than in a changelog — but the headlines are: the
endowed floor is **20%** and is now explicitly step 0 (the account), the **equipment step is
gone entirely**, eight self-rating sliders became **one current grade plus one strength and one
weakness**, the editor became sections rather than a second wizard, and there is a real
**`POST /api/profile/reset`**. Revision `0006` carries the four new columns.

- **`PATCH /api/profile` takes a PARTIAL profile and upserts, and that is load-bearing.**
  Each step persists as it completes, so an abandoned onboarding **resumes** rather than
  restarting — which means the row is created on step 1, not step 4. `None` means "not in
  this request" for every field; the two collection fields (`aspect_ratings`, `injuries`)
  **replace** the set they name, so `[]` is a real answer.
  ⚠️ **That `null` contract is load-bearing in a second way now.** #54 needed a way to
  un-answer the steps, and teaching `null` to mean "clear" here was **considered and rejected**
  (Kilian's call): it would give every omission a destructive second meaning, one typo from a
  wiped answer, in the one flow whose whole premise is not losing people mid-way. The named
  endpoint does that job instead — see the reset bullet below.
- **`primary_discipline` is DERIVED from the target grade and is not accepted from a
  client.** The ladder is banded per discipline, so a French 7a target *is* a rope goal;
  accepting both would let them contradict each other, and the contradiction would only
  surface in the plan generator.
- **⚠️ UNANSWERED IS `NULL`, and revision `0005` is what made that expressible.**
  `primary_discipline`, `sessions_per_week` and `available_weekdays` were `NOT NULL` in
  `0004`, so a row created on step 1 had to carry invented values for questions steps 2 and
  4 had not asked. Two of them were indistinguishable from real answers —
  `sessions_per_week = 3` is a perfectly plausible reply — so the bar credited work nobody
  had done and PR #11's generator would have read a number the user never chose. `0005`
  drops all three `NOT NULL`s. **Nothing may substitute a fallback for a NULL here**: the
  generator must refuse to generate rather than assume a training frequency. `0` remains a
  legal weekday *mask* meaning "answered, no days" — a different thing from NULL, and **the
  API does accept and store it** (`ge=0`, and `PATCH` writes what it is given). Only the web
  client's own submit gate declines to send it, and a client-side gate is not an API
  property; an earlier version of this bullet claimed it was unreachable.
- **`PATCH {}` writes nothing at all**, not even a row. It used to create one, with those
  placeholders, purely because the handler always ran its upsert.
- **⚠️ A step needs a `*_reviewed_at` column exactly when ZERO ROWS is a legitimate
  answer.** Exactly one step qualifies now: `injuries_reviewed_at` ("nothing is hurting"
  writes no `user_injury` rows). The server stamps it whenever that step is submitted, with or
  without rows; an empty child table otherwise means "asked, nothing" or "never asked" and
  nothing can tell them apart. **No other step gets one** — the aspect step's answer is three
  scalar columns, and the grades and availability are scalars whose NULL carries it.
  `injuries_reviewed_at` also replaced a device-local `localStorage` flag that could only ever
  understate (PR #9's first draft, deleted with it).
  ⚠️ **`equipment_reviewed_at` was the second one and is RETIRED (`0006`).** Nothing reads or
  writes it; it is absent from `ProfileResponse` and from the completion maths. **The column
  still exists on purpose** — expand -> deploy -> contract, and
  `tests/test_migrations_additive.py` correctly refuses a `DROP COLUMN` on a table holding user
  rows. Dropping it is a later revision, once a deployed-and-verified `0006` has proved nothing
  reads it. Do not "tidy" it away in the same PR that stops using it.
- **⚠️ Gating a step because its empty answer is unrecordable was a HARD DEAD-END, and this
  is the lesson worth keeping.** The equipment step required at least one tick. Every one of
  the fifteen seeded rows was indoor gear or an indoor facility, so an outdoor-only climber
  had nothing they could honestly select: Continue never enabled, the editor's Save never
  enabled, 100% unreachable, and the dashboard nagged them forever about a step they had
  answered correctly. `draft.ts` even *stated* the cause — "an empty answer is
  indistinguishable from no answer" — and then resolved it by disabling a button. **"The
  answer cannot be stored" is a schema problem and gets a schema fix; it is never a reason to
  disable a control.**
- **⚠️ THE EQUIPMENT STEP IS GONE, AND THE SEMANTICS ARE DELIBERATELY DEFERRED (#54).** The
  step asked users to tick what they *have* out of seventeen rows, and Kilian's verdict was
  that this is backwards: someone with gym access has most of it, and enumerating gear is the
  wrong question. The new model is **assume access to everything**, and let a user flag "I do
  not have this" on the exercise that needs it, where the app can offer an alternative.
  **What this PR did and did not do:** the step is out of onboarding, `equipment_ids` is out of
  both request and response models, and `equipment_reviewed_at` is retired. **`user_equipment`,
  every `exercise_equipment` requirement and the whole vocabulary are untouched.** Whether
  `user_equipment` becomes a record of what is LACKED, or a second concept beside it, was
  open until #11a and is **now decided — see the next paragraph**. **PR #10 decided only where
  it CANNOT live: not on `GET /api/library`.** That response is cached for every user at once
  in a shared CDN, so a "this user lacks it" field there is a cross-account leak by
  construction — see "⚠️ `/api/library` is USER-INDEPENDENT, permanently". Whatever shape the
  storage takes, the read path is a separate endpoint that is never CDN-cached. Re-adding a
  write path is a later PR's job, with the decision attached.
  **⚠️ DECIDED (Kilian, 2026-08-24): the "I don't have access to this" flag is UNIFORM across
  all 17 equipment rows, outdoor ones included — only the wording differs.** His words: *"a
  user with no 'outdoor' access can also uncheck it, the same as a user with no hangboard can
  uncheck an exercise. The only difference is the text we show, I would suggest using 'I don't
  have access to this' or something similar."* So `user_equipment` becomes a record of what is
  LACKED: one flag, one storage shape, one read path, no outdoor special case — and still
  **never on `GET /api/library`**, which is the one part of this that was already settled.
  **PR #11a assumes the full 17-row vocabulary for every user**, because every real user has
  zero `user_equipment` rows since #54 deleted the step, so reading that table would thin every
  plan to its bodyweight options. It is behind one named constant —
  **`_ASSUMED_EQUIPMENT_KEYS` in `server/plans/routes.py`** — so the day the flag lands there is
  one line to change.
  The three bullets that follow are the history of the step that was, and every one of them is
  still worth reading before designing its replacement.
- **The equipment vocabulary covers FACILITIES, GEAR AND ROCK — it is not a gear inventory**
  (Kilian, 2026-08-21). It carries `outdoor_boulders` and `outdoor_routes`, split by
  discipline for the same reason `server/domain/grades.py` keeps boulder and rope on disjoint
  ordinal bands: they are different training stimuli and the generator must be able to
  prescribe one without the other. **The step RENDERS each row's description**, unlike the
  injury and weekday lists — "an indoor wall climbed without a rope" versus "bouldering on real
  rock" is the sentence that tells a rock climber which box is theirs, and for one release that
  copy existed only in the API payload and the contract test, where no user could read it. **A climber without gear is not a climber who cannot
  train** — they train by climbing, on rock, and with their own body. Seed data, so adding a
  row is a tuple edit and never a migration (`_upsert_reference_rows` upserts on `key` and
  rewrites `sort_order` from the tuple position).
- **⚠️ There is deliberately no `bodyweight` equipment row, and two obligations replace it.**
  A checkbox for having a body is noise, and a user who forgot to tick it would be back in
  the "empty set means nothing" hole. Instead: **an exercise with no `exercise_equipment`
  rows requires nothing and is always prescribable**, which made two things owed. Both are now
  settled, and neither landed as written.
  **PR #10 paid the first, NARROWED** (Kilian, 2026-08-23). Every *aspect* has a gearless
  option, but coverage is not per cell: a modern climbing gym has the full equipment set and
  gym access is the expected case, so the library spends its breadth on gear rather than on a
  bodyweight variant of every (phase, aspect) pair. **17 cells have no gearless candidate**,
  enumerated in `CELLS_WITH_NO_GEARLESS_OPTION` (`server/domain/exercises.py`) behind a guard
  that fails in **both** directions — so the list can rot into neither an oversight nor a
  stale exemption for a cell somebody has since filled. Substitution hints ("no dumbbell? a
  loaded backpack") did land where required: `exercise.substitution_hint`, next to the
  movement, not in a vocabulary.
  **The second is SUPERSEDED, and #11a has now answered it.** "PR #11 must never refuse to
  generate for lack of equipment" was withdrawn (Kilian, 2026-08-23): the generator **may**
  refuse, but it must **say so and name the missing equipment**. **#11a took the
  generate-and-name-the-shortfall branch and never refuses for equipment** — every session is
  built from what the climber has, and each thin or empty slot carries a `Shortfall` naming the
  gear that would fill it (`selection.unlock_options` / `shortfall_message`). **Equipment
  refusal is therefore not a thing to "restore"**: none of the six `RefusalReason` members is
  about gear. **Issue #61 is half-shipped** — the naming exists, the refusing deliberately does
  not. The constraint still stands: **it must not become the deleted onboarding equipment step
  behind a gate** — re-read the hard dead-end bullet above before designing it.
  ⚠️ **The invariant that decision rests on is MEASURED, and two phases have ZERO margin.**
  Every phase has at least `BLOCKS_PER_SESSION` (3) aspects a gearless climber can train — but
  `power_endurance` and `performance` have **exactly 3**. One content edit retiring a gearless
  exercise in either phase silently takes those sessions to two blocks, which is why
  `tests/test_planner_gearless.py` is parametrised per phase. And read the claim the right way:
  **"gearless, injury-free" means the CLIMBER has no open injuries, not that the exercise
  carries no contraindication.** Under the second reading the claim is *false* — 0 fillable
  aspects in those same two phases — and somebody will eventually read it that way.
  `tests/test_equipment_vocabulary.py` still guards the no-`bodyweight`-row half and the
  outdoor-coverage half.
- **⚠️ The improvised-load copy on that step has a SAFETY boundary that is not optional.**
  It says most exercises that add weight work with whatever is to hand — a loaded backpack,
  water bottles, a rock — and then says finger-strength protocols need a real edge and are
  left out rather than improvised. **Never suggest improvising finger loading** (home-made
  hangboards, door-frame edges, towel hangs): it is the most injury-prone thing a climber can
  rig, and it would contradict the whole reason `exercise_contraindication` exists. Static
  copy, deliberately: no `improvised_weight` row, no substitution mapping, no new column.
- **⚠️ `uq_user_injury_open_area` — at most one OPEN injury per area** (`0005`), a partial
  unique index because Postgres has no partial unique *constraint*. It closes a real race:
  the write path reads the open rows and then inserts the missing ones, so two concurrent
  PATCHes both saw "no open elbow row" and both inserted. The insert is
  `ON CONFLICT … WHERE resolved_on IS NULL DO UPDATE`, which **infers that index** — so the
  loser of the race updates instead of duplicating. Resolved rows are outside the predicate
  on purpose: flag → resolve → re-flag is the history the table exists for.
  ⚠️ `index_where=` needs `sqlalchemy.text(...)`; **`func.text(...)` compiles to a nonsense
  `WHERE text($1)`** that type-checks, lints and passes every local test, and fails only
  against real Postgres.
- **⚠️ The availability select opens on NOTHING chosen, and that is finding-2 territory.**
  `0005` stopped the server inventing `sessions_per_week = 3`; a select that opened on 3 put
  the identical placeholder back from the client, and the step's submit gate — which only
  checked the weekday mask — would have sent it the moment one day was ticked, into the
  column whose docstring tells PR #11 it may trust the value. Both halves are now required
  before the step can be submitted, exactly as the grade picker requires a grade. **When a
  column is nullable because "unanswered" is real, the control has to be able to say so too.**
- **⚠️ EIGHT SLIDERS WERE REPLACED BY THREE ANSWERS (#54), and the reasoning is the useful
  part.** The aspect step was eight 1-5 self-ratings, and Kilian's verdict was that it was the
  step most likely to hand the generator garbage: eight middling guesses are indistinguishable
  from eight real answers, and self-rating is hard to do honestly. It now asks three things
  anybody can answer, each with its own `0006` column:
  - **`current_grade_id`** — "I climb 6c" plus a 7a target tells the generator far more than any
    self-rating, because a 6c climber is *measurably* closer to 7a than a 6a climber is;
  - **`strength_aspect_id` and `weakness_aspect_id`** — one of each, from the eight aspects.
  The eight sliders survive **behind a disclosure** for anyone who wants to be specific, and
  picking a strength or weakness also writes that aspect's score, so the two can never
  disagree. `ck_user_profile_strength_and_weakness_differ` refuses the same aspect for both, at
  the edge (`ProfilePatchRequest`), against the stored row (`_require_aspects_differ`) and in
  the schema.
  ⚠️ **`UserAspectRating`'s docstring used to call itself "the generator's only picture of a
  weakness". #54 made that false and the docstring is rewritten** — the profile's
  `weakness_aspect_id` is the deliberate answer to a direct question and is the one to trust;
  a rating row may be nothing more than an untouched default. The old bullet's argument (that
  an accepted default IS a recorded answer) was right for a step whose eight controls were all
  visible, and is wrong now that they are behind a disclosure — which is why `canSubmit`
  requires the two picks rather than accepting eight 3s.
- **⚠️ The two grade columns must share a DISCIPLINE, and one of them can be cleared for you.**
  The ordinal ladders are banded per discipline and `domain.grades.convert` raises
  `CrossDisciplineError` rather than compare across them, so "French 7a goal, Font 7A now" is a
  row the plan generator can do nothing with. A CHECK cannot express it (it would have to follow
  two foreign keys into `grade`), so `server/profile/routes.py::_decide_grades` does, and the
  asymmetry is deliberate: an incoming **current** grade that disagrees is a **422** (the client
  locks both pickers to one scale, so it is a malformed request), while an incoming **target**
  that disagrees with the stored current grade **clears it**. A 422 there would be a dead end —
  a climber moving from sport to bouldering could never change their goal — and clearing is
  exactly what the client does to its own pickers. It is the one NULL that endpoint writes
  without being asked, and it is marked as such in the code.
- **⚠️ The grade FLOOR lives in the client, and that was re-decided when the schema opened.**
  Nobody sets a training goal of Font 4, so the pickers start at the rung whose label is `5` in
  each ladder's reference system — Font 5 / V2 for boulder, French 5 / 5.8 for sport — derived
  from one anchor label and applied by ordinal (`web/src/profile/grades.ts`). It **fails open**:
  a discipline with no `5` keeps every grade, because an empty picker is a dead end and a long
  one is not. It stays client-side for three reasons, all recorded in that file: the ladder is
  domain truth that `convert()` needs whole; `GET /api/vocabulary` is shared reference data
  behind a one-hour cache and the next consumer is an ascent log, where **Font 4 is a real thing
  to have climbed**; and a stored below-floor grade must still RENDER, which a filtered
  vocabulary would break. "We do not offer that as a goal" is not the claim "that grade does not
  exist".
- **The completion percentage is computed on the CLIENT** (`web/src/profile/completion.ts`),
  from raw state the endpoint returns. The server deliberately does not compute it: the
  definition of "a step" would then exist on both sides of the wire. Every one of the four
  tests reads a nullable column or a timestamp — **it is server truth, with no local
  component**, and `0006` is what finally made that true of the aspect step too (the three
  answers had no columns during the prototype and were held on the device; that scaffolding and
  its `ct:` storage key are deleted).
  The aspect step is complete when **all three** of `current_grade_id`, `strength_aspect_id`
  and `weakness_aspect_id` are set — deliberately *not* "at least one rating", because since
  #54 a rating row can be an untouched default and would credit a step nobody answered.
- **The bar opens at 20%, and the floor IS step 0.** It was 29% (2 of 7 units); #54 dropped it
  to 20% because that reads less manipulative, and the formula is
  `20 + 80 × steps_done / total_steps`. With four steps that is 20/40/60/80/100 — no rounding,
  every step worth the same.
  ⚠️ **The identity is what makes the framing honest, and it is worth checking before touching
  the arithmetic:** `20 + 80 × done/4` is identically `100 × (1 + done) / 5`. So the floor is
  not a gift — it is **one of five units already done**, and the unit is the account that
  exists. That is why the rail draws a node `0` labelled Account, ticked from the start, with
  the 0->1 connector filled: the tick and the 20% are one fact stated twice.
  `profile/completion.test.ts` asserts that equivalence directly.
  **A mechanic is allowed only if the progress it signals is TRUE** — that rule governs the
  whole feature, and it is why there is no labour-illusion spinner anywhere in the flow.
  (An earlier version of this bullet noted that "the display name is known" was aspirational
  because no such column existed. `0006` adds one, and it is deliberately **not** credited: it
  is not one of the four steps, and the floor stands for the account, not for a name.)
- **⚠️ Steps 1-4 are OPTIMISTIC and never wait; the FINAL step is awaited, and only it.**
  The round-1 bug was not the optimism — it was navigating in the same handler as the write.
  On the last step that unmounted the component before the mutation settled, so a failed
  write left the bar at **100%** with no injury in the database and the error rendered
  nowhere; the next reader of that profile is the plan generator, which would prescribe crimp
  work on an injured elbow. For the first four steps nothing unmounts, so the write is
  optimistic and does not wait: the overlay applies, the step advances, and a failure reports
  itself. Awaiting there would buy nothing and cost a Neon cold start at each of four
  boundaries, in the one flow whose whole premise is not losing people mid-way. The final step
  awaits because it is the only boundary where "we told you it saved" cannot be corrected
  afterwards. `web/src/onboardingSubmit.test.tsx` is the regression test; it fails if that
  await is removed, confirmed twice.
- **⚠️ THE QUERY CACHE HOLDS SERVER RESPONSES ONLY. The optimistic view is DERIVED.** This
  is the rule that finally made this layer correct, after three consecutive review rounds
  found three bugs in it — every one of them caused by having two writers for one cache
  entry. `web/src/profile/api.ts` carries the full reasoning and the source citations; the
  short version, because each attempt looks obviously right until it is measured:
  1. **Snapshot in `onMutate`, restore in `onError`** is correct only while exactly one write
     is in flight. `mutation.js` dispatches `pending` and runs `onMutate` *before*
     `retryer.start()`, and the `scope` gate is `canRun()` *inside* the retryer — so `scope`
     serialises the network call, **not** `onMutate`. A second `mutate()` snapshots a cache
     that already holds the first one's guess. Measured: two Continue clicks in one tick with
     both PATCHes failing left the bar at **71% against a truth of 57%**, for the full
     ten-minute `staleTime`, while the alert said the answer had not been counted.
  2. **`invalidateQueries` on error** moved the bug. The refetch is issued from the failing
     mutation's `onError`, before the next write commits, so it resolves second and overwrites
     a newer `onSuccess` — measured **71 at +5 ms, then 57**: a write that really did persist
     reading as unanswered, with the dashboard nagging for it.
  3. **And when that refetch itself fails** — the ordinary case, since whatever kills the
     PATCH usually kills the GET — `query.js`'s `case "error"` reducer sets `status: "error"`
     **unconditionally, data or no data**. `isError` flipped, the route swapped the wizard for
     its load-error paragraph, and the user's unsaved draft (a `useState` inside the wizard,
     including a typed injury note) went with it, with no way back because
     `refetchOnWindowFocus` is off.

  So: **no `onMutate`, no snapshot, and nothing at all on the error path.** `onSuccess` writes
  the server's own answer and is the only cache write in the file; the overlay comes from
  `useMutationState({ mutationKey, status: 'pending' })` at render time. It works because
  `mutation.js` dispatches `pending` **synchronously before** the retryer — so the overlay is
  established by the click and rendered **on the next tick** (`useMutationState` delivers
  through `notifyManager.schedule` -> `systemSetTimeoutZero`; measured, and the same scheduler
  a `setQueryData` went through, so nothing regressed) — and, on success, awaits
  `options.onSuccess` **before** dispatching `success`, so real data lands before the overlay
  drops and the bar cannot flicker backwards. A failed write now issues **no request at all**, which is
  also one less Neon wake. `scope` stays, for what it does buy: serialised requests, so
  `onSuccess` fires in commit order.
- **⚠️ A ROUTE MAY ONLY REPLACE ITSELF WITH AN ERROR WHEN THERE IS NOTHING TO SHOW.** Gate on
  `data === undefined`, never on `isError` — `queryObserver.js` derives
  `isLoadingError = isError && !hasData`, and that is the question being asked. Every screen
  holding unsaved input is one bad refetch away from losing it otherwise, and this is exactly
  how it was lost. `ProfileFallback` also carries a **retry button**, because nothing else
  will: `refetchOnWindowFocus` is off app-wide.
- **⚠️ A CREDENTIAL CHANGE MUST RESET THE QUERY CACHE, and the wiring is `createAppContext`.**
  Both session transitions here are client-side — the nav's `logOut()` navigates with the
  router, `/login` uses `router.history.push` — so **nothing reloads the page**, and no query
  key carries a user id. Measured before the fix: user A's dashboard at 86%, log out, log in as
  B, and B saw **86%** with `GET /api/profile` called once in the whole session (the profile's
  `staleTime` is ten minutes). The same cache entry feeds `draftFrom()` in the wizard and the
  editor, so B's form came prefilled with A's target grade, availability, equipment and
  self-ratings, and one Continue would have written A's answers into B's row. Two accounts in
  one tab is the dev and demo path, not a contrived setup.
  - **`queryClient.clear()` fires from `auth/authClient.ts`, beside the `session.clear()` that
    already guards all four credential calls.** It cannot hang off the session store:
    `refresh.ts` drops the token before **every** refresh POST (the same "drop the token
    before every `POST /api/auth/*`" rule), so a store-level hook on the token going null
    would wipe the cache on every silent rotation.
  - **`createAppContext()` in `router.tsx` is what links the pair**, and both entries use it.
    Wiring it per entry fails open — the first version did, and the test that was supposed to
    prove it built its own unlinked pair and passed. Do not go back to calling `createAuth()`
    and `createQueryClient()` separately in an entry.
  - **The query key is deliberately NOT scoped by user id.** The client has no user id before
    the first fetch — the field was removed from `ProfileResponse` in review, and this repo
    never decodes the token client-side — so keying on identity is chicken-and-egg, and keying
    on the token itself would change on every rotation and refetch the world. `clear()` at the
    transition is the fix; identity in the key would be a second mechanism for the same
    property.
  - **Both queries carry `enabled: isAuthenticated`, and that is a compute-budget fix, not
    hygiene.** Clearing the cache while a screen is still mounted makes its observer refetch:
    measured on the real logout path, **one extra `GET /api/profile`** issued after the token
    was dropped, which is a 401, which `refresh.ts` answers with a refresh POST — a **Postgres
    write** on a path that previously did none. `queryObserver.js:445/451/461` gate every fetch
    decision on `enabled`, so this closes it at the source. Re-measured after: zero.
- **⚠️ Anything touching mutations, the query cache or a route-level query guard must be
  VERIFIED against `web/node_modules/@tanstack/query-core/` for the installed version** —
  not from memory, not from the docs, not from reasoning about what would be sensible. Three
  rounds of bugs here were all "I reasoned about the semantics". State the invariant, read the
  source, write the failing test and record the measured numbers, and cite what you read in
  any comment that asserts library behaviour.
  ⚠️ **Cite the CONSTRUCT, never a line number.** Line numbers rot on every dependency bump
  with nothing to catch it — #73's bump falsified six of nine citations in `plan/api.ts` and
  `profile/api.ts` while the whole suite stayed green. So a citation quotes the code it refers
  to, and `web/src/api/libraryCitations.test.ts` asserts every quoted construct is still in the
  installed module (and, both ways, that a newly quoted one has a row). It lives in the WEB
  suite because it reads `web/node_modules`, which CI's `server` job does not install — a
  pytest guard there would pass locally and be vacuous in CI. What it cannot catch: a construct
  that still exists does not prove the logic around it still behaves the same way.
- **The "already complete" redirect reads an ENTRY SNAPSHOT, not the live profile.**
  Finishing the last step updates the cache before `navigate` runs, so a live check would
  race `/dashboard` against `<Navigate to="/profile">`. The snapshot is taken in a `useState`
  initialiser, which also keeps every hook unconditional. ⚠️ **Not test-guarded, and
  deliberately recorded as such**: reverting it to a live check leaves
  `onboardingSubmit.test.tsx` green, because jsdom never renders the intermediate state (the
  router visits only `/onboarding` then `/dashboard`). Structural prevention only — do not
  expect a test to catch its removal.
- **The profile mutation carries `scope: { id: 'profile' }`.** The editor has five Save
  buttons sharing one mutation; without a scope two saves can overlap, the older response
  can land second, and `setQueryData` installs a profile from before the newer write — the
  bar drops a step. Query serialises same-scope mutations.
- **`useProfile` carries a 10-minute `staleTime`.** The dashboard is where every
  authenticated session lands and it used to issue **zero SQL**; every PATCH response already
  replaces the cache. ⚠️ **A second TAB is stale for up to
  those ten minutes and focusing it will not refresh it** — `refetchOnWindowFocus` is `false`
  globally, because a gym phone flaps between focused and blurred constantly. Benign (the tab
  that did the writing is correct, and the number is a progress bar), but it is not "only
  another device can make this stale".
- **⚠️ `POST /api/profile/reset` exists so that `PATCH` did not have to change.** #54 needs a
  way back to a from-scratch wizard. Making `null` mean "clear" in `ProfilePatchRequest` was
  considered and **rejected** — that is the whole reason this endpoint exists, so do not
  "simplify" it away later. It clears, in ONE transaction: every column the four steps own
  (including `primary_discipline`, which is derived from the target grade and has to go with
  it), every `user_aspect_rating` row, and **only the OPEN `user_injury` rows**.
  ⚠️ **Resolved injuries are history and are not touched.** `flag -> resolve -> re-flag` is what
  that table exists for — it is why `0005` added a *partial* unique index — and a reset is not a
  claim about a past injury. It also does **not** clear `display_name` or `show_body_metrics`:
  neither is one of the four steps, and a reset walks the setup flow again rather than wiping an
  account. It is idempotent, it creates no row (same touch-on-read rule as `GET` and `PATCH {}`),
  and it returns the whole profile so the caller redraws the bar from the response.
- **The editor is SECTIONS; the wizard is the linear one-card flow.** They shared a stepper for
  one round and it was wrong: changing a target grade meant walking past three answered
  questions. So `/profile` renders every section at once with one Save at the end, and the rail
  doubles as an index into it. ⚠️ **Save sends only the steps that were TOUCHED** — a step joins
  the set when one of its own fields reports a change. It used to be "shown", which was the same
  thing while one card was visible and is not now: with every section on the page, "shown" means
  "all of them", and pressing Save after editing a grade would stamp `injuries_reviewed_at` and
  write eight default ratings for questions nobody looked at. `patchForAll(draft, [])` is `{}`,
  and `profile/draft.test.ts` pins it.
- **⚠️ The rail is BOTH the progress bar and the canonical stepper, and the nodes are SIBLINGS of
  the progressbar element.** There used to be two components — a percentage bar and a separate
  step list — and #54 collapsed them, because a filled track beside a node rail is the same
  thing said twice in two units, which is how a stepper starts disagreeing with a bar. So
  `ProfileProgress` renders one object: the `role="progressbar"` element is the spine and carries
  the name plus `aria-valuenow`, and the numbered nodes sit **outside** it in a
  `<nav aria-label>` -> `<ol>` -> `<li>` with `aria-current="step"`.
  ⚠️ **Not inside it: a `progressbar`'s contents are presentational, so focusable children there
  are invalid ARIA** — and these are real buttons that navigate. The connectors carry the fill
  instead of a percentage-width bar, which is also what makes the fill terminate at a node's edge
  rather than painting through it: each connector is a flex child of the gap it occupies, so its
  ends ARE the two nodes' edges and there is no length to compute. **Where the fill ends is
  presentation; what the bar reports is `completionPercent`.** Do not recompute one from the
  other. The last node is drawn "Finish" because it IS the last step (Injuries), not a terminal
  node after it, and its accessible name leads with that word because WCAG 2.5.3 requires the
  visible text to be contained in the name.
- **The accessibility contract is fixed** (`ProfileProgress.tsx`):
  stepper as `<nav aria-label>` → `<ol>` → `<li>` with `aria-current="step"` (it moved into
  `ProfileProgress` when the separate list was deleted, and `OnboardingStepper.tsx` is gone);
  the bar as `role="progressbar"` with an accessible **name** plus `aria-valuenow/min/max`;
  **announcements at step boundaries only**, through one polite live region that is always
  in the DOM (a region added at the same moment as its text is frequently not announced);
  the fill transition under `prefers-reduced-motion` while the **number updates instantly**;
  never colour alone — the percentage is text at 4.5:1, the active step is weight plus an
  outline, and a finished step says "Done" in words.
- **`GET /api/vocabulary` carries an `enums` object, and its justification is the TYPE
  CONTRACT — not a runtime consumer.** Five of the six closed vocabularies are referenced by
  no profile field, so without this object they never reach the OpenAPI schema, and retiring
  the hand-written `web/src/api/vocabularies.ts` would have silently dropped five of
  `test_vocabulary_contract.py`'s six assertions instead of re-pointing them. **Nothing in
  `web/src` reads `.enums` today** — an earlier draft of this section and of the module
  docstring claimed the pickers did, which was false; they iterate the real arrays
  (`climbing_aspects`, `equipment`, `injury_areas`). The cost is six short arrays in every
  response and zero database time, and the six assertions are worth that. Say only that.
- **Caching on that endpoint is `private, max-age=3600`, not the library rule's
  `public, immutable`.** It is user-independent and only a deploy can change it, but there is
  no build id in the URL (so a year-long immutable cache would pin a stale vocabulary) and it
  requires a bearer token (so it has no business in a shared CDN cache). React Query holds it
  at `staleTime: Infinity` for the rest of the session. ⚠️ **There is no `Vary:
  Authorization`, and that is only safe while the body is user-independent** — a browser
  cache keys on the URL alone, so two accounts sharing a browser share the entry. The moment
  any field there becomes user-scoped, that header goes in the same commit or the caching
  comes out. `tests/test_vocabulary_api.py` asserts both the header and the premise.
- **A demo token cannot write, so the wizard and the editor disable their buttons and say
  so** rather than producing a 403 the user cannot act on. The dashboard's "finish your
  profile" card is hidden in demo mode for the same reason.
- `show_body_metrics` is a real setting and is deliberately **not** on either screen — it is
  not one of the four steps, and it belongs with the settings work. (`display_name` IS on that
  screen, in its own Account section, because #54 asked for it — but it belongs to no step
  either, so the editor composes it separately and it can never move the completion bar.)

## The plan generator (PR #11a — preview only)

`server/domain/planner/` turns a profile into a whole plan tree and `POST /api/plans/preview`
returns it. **#11a writes no row** — persistence is #11b. Module docstrings carry the detail;
this is the map and the traps.

- **Module layout.** `contract.py` (`GENERATOR_VERSION`, `PlannerInput`, `RefusalReason`,
  `CannotPlanError`, `REFUSAL_MESSAGES`) · `periodisation.py` (gap → weeks, phase order,
  mesocycle spans) · `schedule.py` (weekday mask, date maths) · `selection.py` (`candidates`,
  `prescribable`, `ASPECT_EMPHASIS`, the shortfall machinery) · `generate.py` (`generate`) ·
  `blueprint.py` (the frozen output tree) · `fingerprint.py` (`library_digest`,
  `generator_input`) · `__init__.py`, **a re-export facade that defines nothing** — the
  definitions live in `contract.py` because `schedule.py` has to raise a refusal, and a
  definition in the facade the facade re-exports is a cycle. Purity is enforced by
  `server/domain/.ruff.toml`; see the purity bullet under "Session player invariants".
- **`week_count` comes from the grade-gap ORDINAL, and the table is literal.** A block is
  `LOADING_WEEKS 3 + UNLOAD_WEEKS 1`, so weeks are `4 × blocks`:

  | gap | ≤0 | 1 | 2 | 3 | 4 | 5 | ≥6 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | blocks | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
  | weeks | 8 | 12 | 16 | 20 | 24 | 28 | 32 |

  ⚠️ The "your target is more than one plan away" note fires at **`gap > 6`, not `>=`**
  (Kilian, 2026-08-24): at exactly 6 the formula asks for `MAX_BLOCKS` and gets it, so nothing
  was truncated and telling the user their plan was capped is untrue. **The approved plan
  document says `>= 6` and is wrong on this point** — do not restore it to match.
- **Phases are BLOCKS, and deload and taper are real mesocycles.** Each block is its phase's
  loading weeks plus one `deload` week, and the plan ends on a `taper`. Both read **their own
  `prescription_template` rows** and are **never a multiplier** over the previous phase's
  numbers — a deload is a different session, not a quieter one. `is_deload` is exactly
  `phase is Phase.DELOAD`; the taper is identified by its phase, never by that flag.
- **⚠️ The weekday spread maximises the ASCENDING-SORTED GAP PROFILE, lexicographically — and
  the obvious rule is wrong.** "The n-subset maximising the **minimum circular gap**,
  tie-broken lexicographically" is *undefined past 3 sessions a week*: with 4 of 7 days some
  pair is always adjacent, so every subset ties at a minimum gap of 1 and the lexicographic
  tie-break returns **Mon/Tue/Wed/Thu** — four on, three off, the exact opposite of the "it
  spreads rest" invariant the rule exists for. Every gap profile for a given `n` sums to 7, so
  "most even profile" *is* "most even", it agrees with the minimum-gap rule everywhere that
  rule actually decides (Mon–Fri/2 → Mon/Thu, full week/3 → Mon/Wed/Fri) and it decides where
  that rule does not (full week/4 → Mon/Tue/Thu/Sat). Pinned as literals in
  `tests/test_planner_schedule.py`. The chosen set is the **same every week**; only the
  aspect-emphasis rotation varies week to week.
- **Determinism rests on THREE inputs, and the third is the one nobody would guess.**
  `server/models.py:874-882` promises that the same `generator_version` + `generator_input`
  reproduce the same tree. That is false with two inputs, because **the exercise library is an
  input too**. So `generator_input` carries **`library_digest`**: a sha256 over `EXERCISES`
  canonicalised through `dataclasses.fields()`, so a new spec field joins it automatically and
  a *reorder* moves it (authored order is content `selection` reads). **Without the digest that
  promise breaks the first time a content edit ships, silently.** Deliberately not cached —
  `functools.cache` would stop a guard test substituting a library.
- **`POST /api/plans/preview` is `private, no-store`, and that is a security decision, not a
  cache-tuning one.** The body is per-user and **names the user's open injuries**, so it must
  never reach the shared CDN-cached path `/api/library` uses — see "⚠️ `/api/library` is
  USER-INDEPENDENT, permanently" for what a shared cache does with a user-scoped body. It is
  also the one endpoint where a query-cache persister would be a real data leak rather than a
  policy breach.
- **It is the second entry in `DEMO_WRITE_EXEMPT_ROUTES`, and all three demo mechanisms still
  hold.** It is a `POST` only because the request carries a body: it issues **no `INSERT` and
  no `UPDATE`** (asserted by a row-count test), the deny-by-default middleware exempts exactly
  this route and nothing else, and `SET LOCAL transaction_read_only` is still on for a demo
  principal — so the database would refuse a write even if the code attempted one. Without the
  entry the demo mount cannot see a plan at all.
- **The measured payload**, recorded the way `server/library/routes.py:20-27` records the
  library's, because payload size is the number to watch on both:

  | case | weeks | sessions | prescribed sets | raw | gzip -6 |
  | --- | --- | --- | --- | --- | --- |
  | worst (gap ≥7, 7 sessions/wk, full mask, all 17 equipment) | 32 | 224 | 2,421 | 583.2 KiB | 17.5 KiB |
  | the demo profile (6a→6b, 3/wk) | 16 | 48 | 507 | 124.6 KiB | 4.9 KiB |

  ⚠️ **Even the demo's 16-week plan is larger raw than the entire 85-exercise library** (~90
  KB); the worst case is ~6.5× it. The plan document's estimate (~1,150 sets, 170–250 KB) was
  low by 2–3×. What reaches the wire is the compressed figure — Vercel gzips by default — so
  the transfer is small and the real cost is `JSON.parse` and the client object graph.
  ⚠️ **Two profiles that look extreme are not the worst case**: zero equipment is *smaller*
  (fewer prescribable candidates → fewer sets), and a bigger gap is capped at 32 weeks. If it
  ever bites, the lever is trimming sets beyond the first N weeks, not splitting the endpoint.

## Persisting a plan (PR #11b — persist == activate)

`POST /api/plans` regenerates the tree from the profile and inserts it **already activated**,
standing the previous plan down in the same transaction. `GET /api/plans/active` reads it back;
`POST /api/plans/{id}/abandon` stands one down. Module docstrings carry the detail.

- **There is no "activate" endpoint and there will not be one.** A plan is created activated,
  so `activated_at` is never `NULL` on a persisted row and no state machine exists to get
  wrong. Abandon marks; it never deletes — `activity.planned_session_id` is the only link from
  a logged activity to the plan it satisfied.
- **One active plan per user is enforced TWICE, and neither half is optional.**
  `uq_plan_one_active_per_user` (partial unique index, `0008`) can only *refuse* a second
  active row — it cannot choose which one survives — so `create_plan` stands the old plan down
  in the **same transaction**, and **before** the insert, because the index is not deferrable
  and is checked per statement. What the index buys is that a concurrent double-tap is a
  **409** instead of two active plans, and 409 is a legitimate answer the client recovers from
  by reading. ⚠️ `_ACTIVE_STATE` in `server/plans/routes.py` is the app's one definition of
  "active" and is kept character-identical to the index predicate;
  `test_the_ACTIVE_CRITERION_and_the_INDEX_PREDICATE_cannot_drift` reads the predicate back out
  of `pg_indexes` and compares them.
- **`generator_caveats` is COORDINATE-ADDRESSED, not positional, and it DEGRADES rather than
  500ing.** The generator's commentary is not recoverable from the tree (a block's shortfall
  names the aspect it *wanted*), so it is stored — keyed by `(week_no, weekday, order_index)`
  rather than by list position, because a later generator emitting a different number of
  sessions would otherwise silently reattach caveats to the wrong ones. A shape
  `_StoredCaveats` does not recognise reads as "no caveats", so no schema change can make an
  already-persisted plan unopenable.
- **A preview and a persisted plan are ONE response shape**, so the client needs one renderer;
  a second renderer is where the two drift. `PlanOut` serves all four routes and the only
  difference is that a preview is not a row, so every `id` — plus `exercise_id`, `status` and
  `activated_at` — is `null`. ⚠️ `aspect_key` is the one field read **live** from the exercise
  rather than snapshotted, so it can drift; an accepted asymmetry, recorded on
  `models.py::SessionBlock`.
- **⚠️ THE BACKREF-CASCADE TRAP, and only a six-table row count catches it.** Round 1
  committed the `plan` row and silently dropped all ~2,400 descendants: HTTP **201**, one
  `SAWarning`, and nothing in the schema objected — **nothing requires a plan to have a
  mesocycle.** Appending through `plan.mesocycles` is what makes the unit-of-work cascade the
  whole tree; building children with a bare `mesocycle_id` does not. So the tests count rows in
  all six tables *and* count the rows **reachable from the plan by its foreign keys**, which is
  the assertion a wrongly-parented row fails.
- **Neither statement count is per-row.** The read is six `SELECT`s (one per level via
  `selectinload`) and the write is ~6 statements per level, because Postgres has
  `use_insertmanyvalues` with a 1000-row page. `server/plans/routes.py::_insert_plan_tree` cites
  the SQLAlchemy 2.0.52 source line by line — the ORM-graph-versus-explicit-insert decision
  rests on it.
- **⚠️ An `IntegrityError` is never re-raised.** `str(IntegrityError)` carries the statement
  *and its bound parameters*, which on the `plan` INSERT is `generator_input` — the climber's
  open-injury keys — in the function log. The handler logs the constraint name plus plan-level
  metadata and raises a 500 with `from None`. Input minimisation applies to the **log**, not
  only to the response.
- **⚠️ Size against the PERSISTED payload, not the preview.** Raw size is identical for the same
  tree (a filled `id` costs about what a `null` did) but **compressed size nearly doubles**,
  because thousands of repeated `null`s compress away and distinct integers do not. Figures and
  the sweep behind them are in PR #11b's notes; note they **do not reproduce #11a's 2,421 sets /
  583.2 KiB** worst case, which is stale.
- **`cache-control` is set by the routes AND defaulted by the middleware.** All three are
  `private, no-store` — the bodies name the climber's open injuries — and FastAPI discards a
  route's injected header whenever an `HTTPException` propagates, so `SecurityHeadersMiddleware`
  fills it in **only when absent**. ⚠️ Absent-means-uncacheable, never a blanket: overwriting
  `GET /api/library`'s `public, s-maxage=31536000, immutable` would be a real regression.

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
- The plan generator (`server/domain/planner/`) is a **pure module with no DB
  access** — no clock, no RNG, no I/O; dates are passed in. **Enforced** by the `TID251`
  banned-import rule in **`server/domain/.ruff.toml`** (`sqlalchemy`, `server.db`,
  `server.models`, `random`, `secrets`, `time`, `datetime.datetime.now`,
  `datetime.date.today` — the last two as *attribute accesses*, so importing `date`
  legitimately and then calling `.today()` is still caught). ⚠️ **Ruff has no per-directory
  rule section**, so the scoping is hierarchical config discovery: a nested `.ruff.toml` that
  `extend`s the root, picked up by a plain `ruff check .` with no `--config`. A global ban plus
  `per-file-ignores` was **rejected** — it inverts a guard into a lint that fires on legitimate
  code in every other package and gets "fixed" by widening a list. That purity is what makes
  `POST /api/plans/preview` (blueprint without writing) possible, which is what makes the demo
  mount interactive — see "The plan generator".

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
  `ct:keepScreenOn`) — see the federated-`localStorage` rule above.
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
