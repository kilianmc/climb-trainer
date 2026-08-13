"""Pure domain logic — no DB access, no clock, no RNG, no I/O.

Everything in this package must stay importable without a database, because the
plan generator (PR #11) lives here and `POST /api/plans/preview` runs it without
writing anything. A ruff banned-import rule will enforce that once the planner
lands; until then the rule is: **nothing in `server/domain/` may import
`server.db`, `server.models`, or `sqlalchemy`.**
"""
