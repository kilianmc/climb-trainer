"""`PUT /api/sessions/{client_uuid}` — recording that a session actually happened.

A package to match `server/plans/`'s shape, and `routes.py` is the whole of it: there is no
`schemas.py` anywhere in this repo, so the request and response models live inline beside the
one handler that reads them.

**Never write `ascent` or `ascent_tag_link` from here — not as a nested array on this
payload, not at all.** Ascent logging was cut from the product on 2026-09-07 and those tables
survive only because dropping them is a separate contract-phase migration.
"""
