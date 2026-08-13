"""Authentication: password hashing, tokens, refresh rotation, and the deny-by-default
dependency that enforces all of it.

Split into small modules on purpose — the enforcement logic in `deps.py` is the part
that has to be readable at a glance, and burying it in a file that also does argon2
parameters and cookie attributes is how a subtle hole gets reviewed past.

- `passwords.py`  argon2id hashing, and the timing-equalising dummy verify.
- `tokens.py`     HS256 access tokens. Verification NEVER touches the database.
- `refresh.py`    opaque refresh tokens, rotation, and reuse detection.
- `cookies.py`    the one cookie this app sets, and why each attribute is what it is.
- `ratelimit.py`  fixed-window counter in Postgres (there are no background workers).
- `deps.py`       deny-by-default auth, demo read-only, and the request session.
- `routes.py`     the `/api/auth/*` endpoints.

Nothing here is imported by `server/db.py`; the dependency arrow points one way, so the
engine wiring stays usable by Alembic and the seed with no auth stack loaded.
"""
