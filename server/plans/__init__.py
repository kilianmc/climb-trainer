"""`/api/plans` — a whole training plan: generated, returned, persisted, read back, renamed.

A package to match `server/library/`'s shape; `routes.py` is the whole of it. The algorithm
lives in `server/domain/planner/`, which is pure by lint rule, so this package's entire job
is the two boundaries the domain refuses to cross: reading the profile out of Postgres, and
turning frozen dataclasses into a wire shape.

**Only `POST /api/plans/preview` writes nothing.** `POST /api/plans` persists the generated
tree in one transaction, `GET /active` reads it back and `PUT /{plan_id}/name` renames one.
"""
