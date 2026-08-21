"""`GET`/`PATCH /api/profile` — the profile onboarding fills in, one step at a time.

A package to match `server/auth/`'s shape; `routes.py` is the whole of it. The completion
*percentage* is deliberately not computed here — this endpoint returns which fields are
set and the client derives the number from that (`web/src/profile/completion.ts`), so the
definition of a step exists once rather than on both sides of the wire.
"""
