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

**Data** — Neon Postgres (fully relational plan tree, native enums, a shared grade
ordinal ladder so V-scale / Font / French grades are directly comparable).

**Deploy** — a **single** Vercel project serves both the SPA and `/api/*`, so the API
is same-origin for the standalone app. `uv` manages the Python toolchain.

## Design direction

Modern and simple with tactile detail: bento-box card layouts, **opaque elevated
surfaces** (solid backgrounds, hairline borders, real press states, a restrained shadow
scale), and large bottom-anchored touch targets for one-handed use mid-session.
Glassmorphism was considered and **rejected** — `backdrop-filter` costs GPU and battery
on a phone that's in use mid-session, and translucency is simply harder to read at arm's
length in bad gym lighting. The guiding principle is _useful over pretty_.
`prefers-reduced-motion` is respected, text meets WCAG AA 4.5:1, and cards use container
queries so the same component reflows between the standalone app and the narrower
federated mount.

Input is deliberately **closed** wherever possible — enums, sliders, and grade pickers
sourced from the seeded grade ladder rather than free-text fields. Diary notes are the
only genuinely free-form input in the product, which keeps both the validation surface
and the injection surface small.

## Repo layout

```text
package.json        root — the version source of truth (web/ and pyproject stay 0.0.0)
vercel.json         framework:null + build command + /api and SPA rewrites
pyproject.toml      Python deps (no requirements.txt, deliberately)
uv.lock             committed lockfile
alembic.ini         Alembic config (URL comes from the environment, never this file)
api/index.py        thin Vercel Python entrypoint -> server.app:app
migrations/         Alembic env.py + versions/
server/
  app.py            the FastAPI application
  settings.py       env-driven config (CORS allowlist, the two Neon URLs)
  db.py             engine + session wiring, tuned for serverless + Neon billing
  models.py         SQLAlchemy 2 models, constraint naming convention, TIMESTAMPTZ
  seed.py           reference-data seed (the same module CI and production run)
  domain/
    grades.py       the grade ordinal ladder — pure Python, no DB
tests/              backend tests (pytest; DB tests skip without DATABASE_URL)
web/
  index.html
  vite.config.ts    dev server + /api proxy to :8000
  vitest.config.ts
  src/
    main.tsx        standalone entry (browser history)
    App.tsx
    api/client.ts   API client: base from import.meta.url + content-type guard
    styles/         SCSS
    test/setup.ts   jsdom setup
```

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
entirely on Vercel so a stray `.env` can never shadow production config. Quote any
value containing `&` (Neon appends `&channel_binding=require`) if you also shell-source
the file.

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

## Tests and quality gate

One command runs the same checks CI does:

```bash
npm run check          # web: format:check, lint, typecheck, test, build
                       # server: ruff check, ruff format --check, mypy, pytest
npm run check:web      # just the frontend half
npm run check:server   # just the backend half
```

The local gate needs **no database**: the Postgres-backed tests skip cleanly when
`DATABASE_URL` is unset. CI runs them for real against a pinned `postgres:17-alpine`
service container, after `alembic upgrade head` — so **CI is what proves the
migrations** — plus `alembic check` to catch model drift. SQLite is never substituted;
the schema depends on native enums, `text[]`, `GENERATED … STORED` and GIN.

CI (`.github/workflows/ci.yml`) enforces three required jobs: **`web`**, **`server`**,
and **`secrets`** (gitleaks over full history). `npm run check` covers the first two;
gitleaks is CI-only.

**Testing policy:** tests are written where they buy confidence — domain rules (the
grade ordinal ladder, plan generation, date maths), core user paths (auth, anything
that saves or can lose data), complex transforms and state machines (the protocol
compiler, the player clock), and regressions. Presentational UI, pass-through wrappers,
and anything the type system already guarantees are deliberately left untested. See
[`CLAUDE.md`](CLAUDE.md) for the full rule.

## Dual mount

One route tree, two entries:

| Mount          | Entry        | History                | Notes                                                               |
| -------------- | ------------ | ---------------------- | ------------------------------------------------------------------- |
| **Standalone** | `main.tsx`   | `createBrowserHistory` | `climb.kilianmc.com`, deep links, PWA-installable. Real product.    |
| **Federated**  | `remote.tsx` | `createRemoteHistory`  | Remote `climbTrainer`, exposes `./App`, mounted by portfolio-shell. |

The federated mount runs on the **kilianmc.com origin**, which is why every
`localStorage` key is namespaced `ct:`, no service worker is ever registered from
`remote.tsx`, the API base is resolved from `import.meta.url` rather than a relative
path, and `<Link>` hrefs are rewritten to absolute `climb.kilianmc.com` URLs so a
cmd-click opens the standalone app instead of 404-ing on the portfolio (a left-click
still navigates in place). Auth works identically in both mounts because
`climb.kilianmc.com` and
`kilianmc.com` share a registrable domain and are therefore same-site: an httpOnly
`SameSite=Lax; Secure` refresh cookie plus an in-memory access token, with no tokens
in `localStorage` anywhere.

## Deployment

Two long-lived branches: **`dev`** (integration, default) and **`main`** (production).
Feature PRs target `dev`; `main` only receives `dev`→`main` promotion PRs. Production
baseline is `1.0.0` — dev iterations bump the minor (`npm run version:dev`), releases
bump the major (`npm run version:release`).

Agents and contributors: read **[`CLAUDE.md`](CLAUDE.md)** first. It records the
deployment traps, the write policy, and the security rules, each with the reason.
