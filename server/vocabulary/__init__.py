"""`GET /api/vocabulary` — the reference data every picker in the app is built from.

One module, and it is a package only to match `server/auth/`'s shape. The vocabularies
themselves live in `server/domain/vocabulary.py` and `server/domain/grades.py`; this
package is the read endpoint over the seeded tables plus the closed enums.
"""
