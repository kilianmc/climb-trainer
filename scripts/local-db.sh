#!/usr/bin/env bash
# Local Postgres for the test suite. Driven by `npm run db:up` / `npm run db:reset`.
#
# Reads CT_TEST_DATABASE_URL and NOTHING else. It never writes a URL anywhere, never
# sets DATABASE_URL outside the single `alembic` invocation below, and only ever prints
# host / port / database name — the same redaction level as
# `server.db.target_host_and_database`, because this repo is public and so is a pasted
# terminal transcript.
set -euo pipefail

# Homebrew's postgresql@17 is KEG-ONLY: its binaries are not on PATH, so they are
# addressed by absolute path rather than hoped for.
PG_BIN=/opt/homebrew/opt/postgresql@17/bin
FORMULA=postgresql@17

die() { printf '%s\n' "$*" >&2; exit 1; }

[ -x "$PG_BIN/psql" ] || die "No postgresql@17 at $PG_BIN. Install it: brew install $FORMULA"

url=${CT_TEST_DATABASE_URL:-}
[ -n "$url" ] || die "CT_TEST_DATABASE_URL is not set. See CLAUDE.md, 'Local Postgres for the test suite'."

# --- Parse the URL into parts. The URL itself is never passed on or printed. ---------
rest=${url#*://}
case $rest in
  *@*) cred=${rest%%@*}; rest=${rest#*@} ;;
  *)   cred= ;;
esac
case $rest in
  */*) hostport=${rest%%/*}; db=${rest#*/}; db=${db%%\?*} ;;
  *)   die "CT_TEST_DATABASE_URL names no database (nothing after the host)." ;;
esac
[ -n "$db" ] || die "CT_TEST_DATABASE_URL names no database (nothing after the host)."
case $hostport in
  \[*)  host=${hostport#\[}; host=${host%%\]*}; port=${hostport##*\]} ; port=${port#:} ;;
  *:*)  host=${hostport%%:*}; port=${hostport##*:} ;;
  *)    host=$hostport; port= ;;
esac
port=${port:-5432}
user=${cred%%:*}
pass=${cred#*:}
if [ "$pass" = "$cred" ]; then pass=; fi
user=${user:-$(id -un)}

# --- The guard. Only the HOST crosses this boundary, never the URL: a URL bound to a
# --- function argument or a frame local is rendered by pytest and by most tracebacks,
# --- password included (see server/db.py::host_of). Reuses the repo's own allowlist so
# --- it cannot drift from server.db.LOCAL_DB_HOSTS.
uv run python -c \
  'import sys; from server.db import is_local_host; raise SystemExit(0 if is_local_host(sys.argv[1]) else 1)' \
  "$host" \
  || die "refusing: CT_TEST_DATABASE_URL host '$host' is not local. This script only ever touches a local database; there is no override."

psql_maint() { PGPASSWORD=$pass "$PG_BIN/psql" -X -q -h "$host" -p "$port" -U "$user" -d postgres "$@"; }

ensure_server() {
  if "$PG_BIN/pg_isready" -q -h "$host" -p "$port"; then return 0; fi
  command -v brew >/dev/null 2>&1 \
    || die "Postgres is not accepting connections on $host:$port and brew is not on PATH. Start it with: $PG_BIN/pg_ctl -D /opt/homebrew/var/$FORMULA start"
  brew services start "$FORMULA"
  for _ in $(seq 1 30); do
    if "$PG_BIN/pg_isready" -q -h "$host" -p "$port"; then return 0; fi
    sleep 1
  done
  die "Postgres did not come up on $host:$port within 30s. Check: brew services info $FORMULA"
}

db_exists() {
  # `:'name'` is psql's own literal interpolation — it quotes and escapes, so the
  # database name is never concatenated into SQL. It has to arrive on stdin via `-f -`:
  # the lexer that expands `:'name'` does not run for `-c`, which sends the string to
  # the server verbatim and fails with `syntax error at or near ":"`.
  local found
  found=$(printf '%s\n' "SELECT 1 FROM pg_database WHERE datname = :'name'" \
    | psql_maint -v name="$db" -tA -f -) \
    || die "could not list databases on $host:$port. Is the server up, and does role '$user' exist?"
  [ -n "$found" ]
}

migrate() {
  # The ONLY place a URL is put in an environment, and it is scoped to this one command.
  # DATABASE_URL="" is what stops .env's production value being loaded: python-dotenv
  # runs with override=False, so a key already present in the environment — even empty —
  # is skipped. DATABASE_URL_UNPOOLED is what migrations/env.py reads first
  # (`direct_database_url()`), and require_migration_host then sees a local host and
  # allows it. CT_ALLOW_REMOTE_MIGRATION is never set here.
  DATABASE_URL="" DATABASE_URL_UNPOOLED="$url" uv run alembic upgrade head
}

case ${1:-} in
  up)
    ensure_server
    db_exists || PGPASSWORD=$pass "$PG_BIN/createdb" -h "$host" -p "$port" -U "$user" "$db"
    migrate
    printf 'db:up — %s/%s at head\n' "$host" "$db"
    ;;
  reset)
    ensure_server
    PGPASSWORD=$pass "$PG_BIN/dropdb" --if-exists --force -h "$host" -p "$port" -U "$user" "$db"
    PGPASSWORD=$pass "$PG_BIN/createdb" -h "$host" -p "$port" -U "$user" "$db"
    migrate
    printf 'db:reset — %s/%s recreated and at head\n' "$host" "$db"
    ;;
  *) die "usage: scripts/local-db.sh {up|reset}" ;;
esac
