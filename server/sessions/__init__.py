"""`PUT /api/sessions/{client_uuid}` — recording that a session actually happened.

A package to match `server/plans/`'s shape, and `routes.py` is the whole of it: there is no
`schemas.py` anywhere in this repo, so the request and response models live inline beside the
one handler that reads them.

**Ascents are deliberately absent.** A send is the emotional payload of the whole app and
needs its own contract rather than a nested array here, so `ascent` and `ascent_tag_link` stay
unwritten until the follow-up issue this PR files.
"""
