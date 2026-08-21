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

1. **Target grade in.** Log in, set your target grade, discipline, weekly
   availability, available equipment, and self-rated strengths and weaknesses.
2. **Plan out.** A pure-Python plan generator turns the gap between your current and
   target grade into a phased plan — base → strength → power → power endurance →
   peak/taper, with a deload every fourth week — allocating volume toward your weakest
   aspects and filtering exercises by your equipment and injury flags.
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
sourced from the seeded grade ladder rather than free-text fields. Diary notes are the
only genuinely free-form input in the product, which keeps both the validation surface
and the injection surface small.

## Repo layout

```text
package.json        root — the version source of truth (web/ and pyproject stay 0.0.0)
vercel.json         framework:null + build command + /api and SPA rewrites
pyproject.toml      Python deps
uv.lock             committed lockfile
alembic.ini         Alembic config (URL comes from the environment, never this file)
api/index.py        thin Vercel Python entrypoint -> server.app:app
migrations/         Alembic env.py + versions/
server/
  app.py            the FastAPI application
  settings.py       env-driven config (CORS allowlist, the two Neon URLs)
  db.py             engine + session wiring, tuned for serverless + Neon billing
  models.py         SQLAlchemy 2 models, constraint naming convention, TIMESTAMPTZ
  seed.py           reference-data seed
  devseed.py        ten local test accounts — DEV ONLY
  admin.py          operator CLI: create-invite, set-password
  fields.py         bounded Pydantic field types, one per persisted CHECK
  openapi_schema.py the OpenAPI document, for the TypeScript codegen
  profile/          GET/PATCH /api/profile
  vocabulary/       GET /api/vocabulary — grades, lookup tables, closed enums
  domain/
    grades.py       the grade ordinal ladder — pure Python, no DB
tests/              backend tests (pytest; DB tests skip without DATABASE_URL)
web/
  index.html
  vite.config.ts    dev server + /api proxy to :8000
  vitest.config.ts
  src/
    main.tsx        standalone entry (browser history)
    remote.tsx      federated entry (memory history)
    api/client.ts   API client: base from import.meta.url + content-type guard
    api/schema.ts   GENERATED from the OpenAPI schema — never edit; see below
    profile/        onboarding + profile editor: one set of fields, two entry points
    publicUrl.ts    public/ asset URLs, resolved from import.meta.url (same trap)
    ui/             components; landingImages.ts is the image ladder, icons.tsx the SVGs
    styles/         SCSS
  public/landing/   committed responsive derivatives
  PHOTO-CREDITS.md  photograph provenance: title, creator, licence, source
  scripts/          authoring tools
```

The layout is load-bearing in several places — see [`CLAUDE.md`](CLAUDE.md) before
rearranging any of it.

## Getting started

Requires Node per `.nvmrc` (24) and [`uv`](https://docs.astral.sh/uv/) for Python 3.13.

```bash
# once
npm --prefix web ci
uv sync --all-groups
cp .env.example .env      # then fill in the Neon URLs and AUTH_SECRET
```

`.env` is **loaded automatically** by `server/settings.py`, so the API, `alembic`,
`pytest` and `python -m server.seed` all pick it up with no `--env-file` flag. An
exported environment variable always overrides the file, and the load is skipped
entirely on Vercel. Quote any value containing `&` (Neon appends
`&channel_binding=require`) if you also shell-source the file.

The variables, all documented inline in `.env.example`:

| Variable                | What it is                                                            |
| ----------------------- | --------------------------------------------------------------------- |
| `CORS_ORIGINS`          | Comma-separated allowlist. A `*` fails at startup.                    |
| `DATABASE_URL`          | Neon **pooled** endpoint (host contains `-pooler`) — the app.         |
| `DATABASE_URL_UNPOOLED` | Neon **direct** endpoint — Alembic only.                              |
| `AUTH_SECRET`           | HS256 signing key for access tokens. **≥32 chars**, generate it.      |
| `COOKIE_SECURE`         | Optional. Defaults to `true`; set `false` only for http on localhost. |

Generate a signing key with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`. It has to be set in
Vercel too, for every scope you deploy to — `.env` is not read inside a deployment.
Nothing secret may ever carry a `VITE_` prefix: that prefix is inlined into the public
client bundle.

Database migrations are **not** run from a laptop against production. Use the manual
**Migrate** workflow (Actions → Migrate); see `CLAUDE.md`.

Then run both halves — the API on `:8000`, the SPA on `:5173` with Vite proxying
`/api` across so the two share an origin exactly as they do in production:

```bash
# terminal 1
uv run uvicorn server.app:app --port 8000 --reload

# terminal 2
npm --prefix web run dev          # http://localhost:5173
```

> The Vite dev proxy is **not** Vercel's rewrite — it is a different mechanism that
> happens to look the same. Any change to routing, `vercel.json`, or the API base has
> to be re-verified on a real deploy. See `CLAUDE.md`.

The PWA icons in `web/public/` are generated and committed, not built, and the generator is
deliberately not a dependency (see `CLAUDE.md`). Regenerate them only after editing
`web/public/mark.svg`, and commit the result:

```bash
npm --prefix web run generate:icons
```

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

The local gate needs **no database** — the Postgres-backed tests skip cleanly. CI runs
them for real against a pinned `postgres:17-alpine` service container after
`alembic upgrade head`, so **CI is what proves the migrations**, and adds `alembic check`
and a gitleaks scan over full history. See [`CLAUDE.md`](CLAUDE.md) for what CI adds on
top of `npm run check`, and for the testing policy: tests are written where they buy
confidence — domain rules, core user paths, complex transforms, regressions — and
presentational UI, pass-through wrappers and anything the type system already guarantees
are deliberately left untested.

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
