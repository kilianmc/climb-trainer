# Climb Trainer

A mobile-first **climbing training app**: pick a target grade, get a generated plan
that covers the different **aspects of climbing**, then follow the session along with
a timer and audio cues while it logs itself — and read it all back as a training
diary.

- **Live:** <https://climb.kilianmc.com> _(standalone app)_
- **Also runs inside** <https://kilianmc.com> as the **`climbTrainer`** Module
  Federation remote — the third showcase project in the portfolio, and the first with
  a **database and a backend that isn't JavaScript**.

## What it does

1. **Target grade in.** Log in, then answer four questions: the grade you climb now and
   the one you are training for, one strength and one weakness, your weekly availability,
   and anything that is currently injured.
2. **Plan out.** A pure-Python plan generator turns the gap between your current and
   target grade into a phased plan — base → strength → power → power endurance →
   peak/taper, with a deload every fourth week — allocating volume toward your weakest
   aspects, skipping anything an open injury contraindicates, and naming the gear that
   would unlock a session it had to build thin.
3. **Guided session player.** A protocol interpreter compiles any prescription (max
   hangs, repeaters, 4×4s, EMOM, min-edge, limit boulder, circuits) into one timeline
   of `prepare / work / rest / open` phases. Full-viewport colour changes and a huge
   countdown carry the cues, with synthesized audio and haptics on top. Every tap is a
   local write first, so it works with no signal in a basement gym.
4. **Training diary.** Notes live on the thing they describe — the session, the set,
   the ascent — plus free-standing journal entries, merged into one reverse-chronological
   timeline with full-text search.

## Stack

**Frontend** — React 19 · TypeScript 6 (strict) · Vite 8 · SCSS · Vitest + React
Testing Library · `@module-federation/vite` (remote role).

**Backend** — FastAPI · Python 3.13 · sync SQLAlchemy 2 · psycopg3 · Alembic · pytest ·
ruff.

**Data** — Neon Postgres. The plan tree is fully relational, closed vocabularies are
native enums, and grades carry an integer `ordinal` rather than a display string — one
contiguous ladder per discipline, so V-scale and Font boulder grades sit on the same
rungs while boulder and rope grades are deliberately not treated as comparable.

**Deploy** — a **single** Vercel project serves both the SPA and `/api/*`, so the API
is same-origin for the standalone app. `uv` manages the Python toolchain.

## Design direction

Modern and simple with tactile detail: bento-box card layouts, **opaque elevated
surfaces** (solid backgrounds, hairline borders, real press states, a restrained shadow
scale), and large touch targets for one-handed use mid-session. Glassmorphism was
considered and **rejected** — `backdrop-filter` costs GPU and battery on a phone that's
in use mid-session, and translucency is simply harder to read at arm's length in bad gym
lighting. The guiding principle is _useful over pretty_. `prefers-reduced-motion` is
respected, text meets WCAG AA 4.5:1, and cards use container queries so the same
component reflows between the standalone app and the narrower federated mount.

The public landing page is the one screen that breaks out of that reading measure: it
runs full-bleed photographic bands with the copy held to a ~65–75 character column. Its
photographs are self-hosted and bundled because the production CSP is `img-src 'self'
data:`, and icons are inline SVG components for the same reason.

**Regenerating the landing photographs** (only needed when a photo changes):

```bash
npm --prefix web run images:landing            # fill in anything missing
npm --prefix web run images:landing -- --force # re-encode everything
```

The originals live outside the repo (`~/Pictures/climb-trainer-photo-src`, or set
`CT_PHOTO_SRC`; each entry's `source` is a path relative to that root); the AVIF/WebP/JPEG
derivatives under `web/public/landing/` **are** committed, because CI and Vercel build from
a clone with no photo library. Credits and licences: `web/PHOTO-CREDITS.md`.

Input is deliberately **closed** wherever possible — enums, sliders, and grade pickers
sourced from the seeded grade ladder rather than free-text fields. Only eleven fields in the
whole product are genuinely free-form (notes, a route name, a plan title), which keeps both
the validation surface and the injection surface small.

The partial-by-partial ownership of `web/src/styles/`, the design tokens and the container-query
rules are in [`CLAUDE.md`](CLAUDE.md), along with the reason behind each one.

## Repo layout

```text
package.json  vercel.json  pyproject.toml  uv.lock  alembic.ini  .nvmrc  .python-version
api/index.py            thin Vercel Python entrypoint
migrations/             Alembic env.py + versions/
server/                 the FastAPI application
  app.py  settings.py  db.py  models.py  fields.py  openapi_schema.py  security_headers.py
  seed.py  contentseed.py  devseed.py  admin.py
  auth/  domain/  library/  plans/  profile/  vocabulary/
tests/                  backend tests (pytest)
web/                    the Vite SPA, built to web/dist
  src/
    main.tsx  remote.tsx  router.tsx  routeTree.gen.ts  theme.ts
    api/  auth/  library/  plan/  profile/  pwa/  routes/  styles/  ui/
  public/               static assets, including the committed landing derivatives
  scripts/              authoring tools
```

This layout is **load-bearing** — the `api/index.py` entrypoint, the `[tool.setuptools]`
package list and where the FastAPI app may live were all settled by a deployment spike. Read
[`CLAUDE.md`](CLAUDE.md)'s *Repo layout* section for the rules before moving any of it.

## Getting started

Requires Node per `.nvmrc` (24), [`uv`](https://docs.astral.sh/uv/) for Python 3.13, and
Postgres 17 for the database-backed tests.

```bash
# once
npm --prefix web ci
uv sync --all-groups
cp .env.example .env      # every variable is documented inline in the file
npm run db:up             # local Postgres: create the database and migrate it to head
```

Generate the `AUTH_SECRET` signing key with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`. `.env` is loaded automatically
by `server/settings.py`, so no `--env-file` flag is needed anywhere; it also has to be set in
Vercel, for every scope you deploy to.

Then run both halves — the API on `:8000`, the SPA on `:5173` with Vite proxying `/api` across
so the two share an origin exactly as they do in production:

```bash
# terminal 1
npm run dev:api           # uvicorn, against LOCAL Postgres

# terminal 2
npm --prefix web run dev  # http://localhost:5173
```

Regenerate the PWA icons after editing `web/public/mark.svg`, and commit the result:

```bash
npm --prefix web run generate:icons
```

> Several things here have a trap attached and are written up in
> [`CLAUDE.md`](CLAUDE.md): why `dev:api` rather than a bare `uvicorn`, exactly what `.env`
> loading does and does not do, why a local database means local accounts only (registration is
> invite-gated — mint one with `python -m server.admin create-invite`), why the Vite dev proxy
> proves nothing about Vercel's rewrite, and why the icon generator is deliberately not a
> dependency. Migrations are never run from a laptop against production: use the manual
> **Migrate** workflow (Actions → Migrate).

## Tests and quality gate

One command runs the same checks CI runs on the code:

```bash
npm run check          # web: format:check, lint, typecheck, build, test
                       # server: ruff check, ruff format --check, mypy, pytest
npm run check:web      # just the frontend half
npm run check:server   # just the backend half
```

`web/src/api/schema.ts` is **generated and committed**. Regenerate it whenever an endpoint
or a request/response model changes:

```bash
npm run codegen:api    # server/openapi_schema.py -> openapi-typescript -> src/api/schema.ts
```

Forgetting to is caught by `pytest`, not by a build step. The generated header carries two
digests — one of the OpenAPI document it was built from, one of the generated types
themselves — and `tests/test_vocabulary_contract.py` checks both, so the file can neither
fall behind the server nor be edited by hand. A FastAPI or Pydantic upgrade also lands
there, and only a regeneration fixes it.

The local gate needs **no database** — the Postgres-backed tests skip cleanly. CI runs them
for real against a pinned `postgres:17-alpine` service container after `alembic upgrade head`,
so **CI is what proves the migrations**, and adds `alembic check` and a gitleaks scan over full
history. The testing policy, the comment and prose budget, and what each CI job adds on top of
`npm run check` are all in [`CLAUDE.md`](CLAUDE.md).

## Signing in

The same public landing page serves both mounts. From it you can log in, create an account, or
open the **demo** — a seeded, read-only account that needs no email address, so the app can be
explored end to end without registering.

**Creating an account needs an invite code.** Codes are per person, stored only as a hash, and
carry a use count, an optional expiry and a revocation flag, so one can be withdrawn without
affecting anyone else's. The account records which invite created it, and that link cannot be
deleted away. A code that is unknown, expired, revoked or used up gets the same answer — one
that also points a returning invitee at the login form — and spending one happens in the same
transaction as the account insert, so a failed sign-up never burns the code its holder was
given. Demo mode stays open to everyone.

The access token is held **in memory only**, never in `localStorage` or `sessionStorage`, and
the refresh token is an httpOnly host-only cookie the browser attaches to `/api/auth` alone.
Refresh happens **lazily, on a 401**, never on a timer. Because rotation detects token reuse by
design, two refreshes racing each other would otherwise revoke the whole token family, so the
refresh path is serialised on three axes — within a tab, across tabs of one origin, and across
the two origins the app is mounted on. Discovering an existing session costs a database write,
so it is attempted only when a guarded route is entered, never for a visitor who is just
reading the landing page. Everything under `web/src/routes/_authed/` is behind a route guard
that redirects to `/login` with the intended path.

## Dual mount

One route tree, two entries:

| Mount          | Entry        | History                | Notes                                                               |
| -------------- | ------------ | ---------------------- | ------------------------------------------------------------------- |
| **Standalone** | `main.tsx`   | `createBrowserHistory` | `climb.kilianmc.com`, deep links, PWA-installable. Real product.    |
| **Federated**  | `remote.tsx` | `createRemoteHistory`  | Remote `climbTrainer`, exposes `./App`, mounted by portfolio-shell. |

The federated mount runs on the **kilianmc.com origin**, which constrains a surprising
amount: storage keys, service-worker registration, how the API base and asset URLs are
resolved, how `<Link>` hrefs are written, and why layout uses container queries rather than
viewport units. Auth works identically in both mounts because `climb.kilianmc.com` and
`kilianmc.com` share a registrable domain and are therefore same-site. Each of those rules
has a failure behind it — they are written up in [`CLAUDE.md`](CLAUDE.md).

## Deployment

Two long-lived branches: **`dev`** (integration) and **`main`** (production, and the
GitHub default branch). Feature PRs target `dev`; `main` only receives `dev`→`main`
promotion PRs. Dev iterations bump the minor (`npm run version:dev`), releases bump the
major (`npm run version:release`).

Agents and contributors: read **[`CLAUDE.md`](CLAUDE.md)** first — it opens with an index.
It records the deployment traps, the write policy, and the security rules, each with the
reason.
