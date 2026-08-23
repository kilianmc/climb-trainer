"""`GET /api/library` — the read endpoint over the seeded exercise library.

A package to match `server/vocabulary/`'s shape. The library content itself lives in
`server/domain/exercises.py` and is written by `server/contentseed.py`; this package only
reads what the seed wrote.
"""
