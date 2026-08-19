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

The public landing page is the one screen that breaks out of that reading measure: it
runs full-bleed photographic bands with the copy held to a ~65–75 character column. The
breakout is a **grid column**, never `100vw` or `position: fixed` — both resolve against
kilianmc.com's viewport in the federated mount. Its photographs are self-hosted and
bundled because the production CSP is `img-src 'self' data:`, and icons are inline SVG
components for the same reason.

**Regenerating the landing photographs** (only needed when a photo changes):

```bash
npm --prefix web run images:landing            # fill in anything missing
npm --prefix web run images:landing -- --force # re-encode everything
```

The originals live outside the repo (`~/Pictures/climb-trainer-photo-src`, or set
`CT_PHOTO_SRC`; each entry's `source` is a path relative to that root); the AVIF/WebP/JPEG derivatives under `web/public/landing/` **are**
committed, because CI and Vercel build from a clone with no photo library. Credits and
licences: `web/PHOTO-CREDITS.md` (deliberately outside `public/` — it is a provenance
record, not something to ship and precache).

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
  devseed.py        ten local test accounts — DEV ONLY, refuses to run in CI
  admin.py          operator CLI: create-invite, set-password
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
    publicUrl.ts    public/ asset URLs, resolved from import.meta.url (same trap)
    ui/             components; landingImages.ts is the image ladder, icons.tsx the SVGs
    styles/         SCSS
  public/landing/   committed responsive derivatives (nothing else — asserted)
  PHOTO-CREDITS.md  photograph provenance: title, creator, licence, source
  scripts/          authoring tools, never part of `build`
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

The PWA icons in `web/public/` are generated and committed, not built, and the generator is
deliberately not a dependency (see `CLAUDE.md`). Regenerate them only after editing
`web/public/mark.svg`, and commit the result — the script downloads a pinned version on demand:

```bash
npm --prefix web run generate:icons
```

## Tests and quality gate

One command runs the same checks CI does:

```bash
npm run check          # web: format:check, lint, typecheck, build, test
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

## Signing in

The same public landing page serves both mounts. From it you can log in, create an account, or
open the **demo** — a seeded, read-only account that needs no email address, so the app can be
explored end to end without registering.

**Creating an account needs an invite code.** Codes are per person, stored only as a hash, and
carry a use count, an optional expiry and a revocation flag, so one can be withdrawn without
affecting anyone else's. The account records which invite created it, and that link cannot be
deleted away. A code that is unknown, expired, revoked or used up gets the same answer — one
that also points a returning invitee at the login form, since re-entering a code you already
used is the commonest way to see it — and spending one happens in the same transaction as the
account insert, so a failed sign-up never burns the code its holder was given. Demo mode stays
open to everyone.

The access token is held **in memory only**, never in `localStorage` or `sessionStorage`, and
the refresh token is an httpOnly host-only cookie the browser attaches to `/api/auth` alone.
Refresh happens **lazily, on a 401**, never on a timer, and is guarded on three axes, because
rotation detects reuse by design and two racing refreshes would otherwise revoke the whole
token family. Within a tab, concurrent 401s share one in-flight refresh. Across tabs of one
origin, which share the cookie but not that closure, a Web Lock makes the second tab wait and
then rotate legitimately in its turn. Across the **two origins** — the standalone app and the
federated mount, which share a cookie but get separate lock managers — the server answers the
loser of a race with a 409 inside a 10-second window and the client retries once, rotating
whatever the shared cookie jar now holds. That is a strong mitigation rather than a guarantee:
one retry converges exactly two origins, and a loser delayed past the window is still read as a
replay. When it does not converge, the mount reports a signed-out session and a reload fixes it
— the token family survives. No token is ever shared between tabs. Demo sessions
have no refresh cookie and re-mint instead.

Everything under `web/src/routes/_authed/` is behind a route guard that redirects to `/login`
with the intended path, and `web/src/publicRoutes.test.ts` asserts no route can become public
by being filed in the wrong directory. Discovering an existing session costs a database write,
so it is attempted only when a guarded route is entered — never for a visitor who is just
reading the landing page.

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
