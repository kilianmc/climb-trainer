"""Pure domain logic — no DB access, no clock, no RNG, no I/O.

Everything here must stay importable without a database, because the plan generator lives here
and `POST /api/plans/preview` runs it without writing anything.

**Enforced, not asked for**: `server/domain/.ruff.toml` bans `server.db`, `server.models`,
`sqlalchemy`, `random`, `secrets`, `time`, `datetime.datetime.now` and `datetime.date.today`
under `TID251`. A scoped config rather than a global rule with exemptions, because a global one
would fire on every other package and get "fixed" by widening an ignore list.
"""
