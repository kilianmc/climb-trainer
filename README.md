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
