"""Authentication: hashing, tokens, refresh rotation, and the deny-by-default dependency.
Split into small modules on purpose — the enforcement logic in `deps.py` has to be readable at a
glance, and burying it in a file that also does argon2 parameters and cookie attributes is how a
subtle hole gets reviewed past. `passwords.py` argon2id and the timing-equalising dummy verify ·
`tokens.py` HS256 access tokens, verification NEVER touches the database · `refresh.py` opaque
tokens, rotation, reuse detection · `cookies.py` the one cookie and why each attribute is what it
is · `ratelimit.py` the Postgres counter · `deps.py` deny-by-default, demo read-only, the request
session · `routes.py` the endpoints. Nothing here is imported by `server/db.py`: the arrow points
one way, so Alembic and the seed load no auth stack.
"""
