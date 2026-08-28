"""`POST /api/plans/preview` — a whole training plan, built and returned, never written.

A package to match `server/library/`'s shape; `routes.py` is the whole of it. The algorithm
lives in `server/domain/planner/`, which is pure by lint rule, so this package's entire job
is the two boundaries the domain refuses to cross: reading the profile out of Postgres, and
turning frozen dataclasses into a wire shape.

**Nothing here writes.** Persisting a plan is PR #11b.
"""
