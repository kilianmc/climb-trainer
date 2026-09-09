"""`PUT /api/journal/{client_uuid}` and `GET /api/journal` — the diary, written and read back.

A package to match `server/sessions/`'s shape, and `routes.py` is the whole of it: there is no
`schemas.py` anywhere in this repo, so the request and response models live inline beside the
handlers that read them.

The GIN index on `journal_entry.body` stays unused: the read is a bounded newest-first window,
not a search. ⚠️ **BODY WEIGHT is smoothed or rolling only — never a raw day-to-day line**, and
the 1-5 scores are NOT: a subjective reading IS the datum, so the client plots them as written.
"""
