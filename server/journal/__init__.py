"""`PUT /api/journal/{client_uuid}` — writing down how a session, or a day, actually went.

A package to match `server/sessions/`'s shape, and `routes.py` is the whole of it: there is no
`schemas.py` anywhere in this repo, so the request and response models live inline beside the
one handler that reads them.

**Reading entries back is not here.** The trend chart and the entry list are PR C, and the GIN
index on `journal_entry.body` stays unused until something actually searches it. The trend, when
it arrives, is smoothed or rolling only — never a raw day-to-day weight line.
"""
