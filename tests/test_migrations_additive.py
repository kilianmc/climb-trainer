"""A migration's `upgrade()` must never destroy `app_user` rows.

Production carries real user accounts, and migrations are the one thing in this project
that can delete them irreversibly: a deploy can be rolled back, a bad row can be fixed,
but `DROP COLUMN` is gone the moment it commits. Per the testing policy in CLAUDE.md this
is the "anything that can lose user data" bullet, and per CLAUDE.md's own guidance it is a
"don't change this or X breaks" rule converted into a test rather than left as prose.

**`downgrade()` bodies are deliberately ignored.** They are *supposed* to be destructive —
`0003`'s downgrade drops `app_user.invite_id` and the `invite` table, correctly — so a
whole-file scan would fail on the existing repo. That asymmetry is exactly why this reads
the AST and scopes itself to the `upgrade` function rather than grepping the file. The
protection against a downgrade reaching production is structural instead: `migrate.yml`
offers no `downgrade` action, and recovery is a Neon branch restore.

## Two arms, because Alembic is not the only way to drop a column

1. **Alembic ops** — `op.drop_table("app_user")` / `op.drop_column("app_user", ...)`.
2. **Raw SQL** — `op.execute("ALTER TABLE app_user DROP COLUMN email")` bypasses arm 1
   entirely, and was verified to leave arm 1 fully green. Arm 2 flags a string literal that
   mentions `app_user` together with a destructive verb.

**Arm 2 is deliberately crude, and over-flags rather than under-flags.** It is a substring
match against a normalised copy of the string, not a SQL parser: a false positive costs a
developer one minute reading this file, a false negative costs production rows. If a
legitimate migration ever trips it, add the narrowest possible exemption *with a comment
saying why* — do not loosen the pattern.

⚠️ **Limit worth stating rather than implying: this inspects string LITERALS only.** SQL
built at runtime — an f-string, a `+` concatenation, a name read from a variable or a
constant defined elsewhere — is invisible to it. That is an accepted gap, not a guarantee;
migrations in this repo write their SQL inline, and a migration that assembles DDL
dynamically needs review by a human regardless.

**No database.** This is a file inspection, so it runs in the local gate as well as CI —
which matters, because the mistake it catches is made while writing a migration, long
before anything is applied.
"""

import ast
import pathlib
import re

import pytest

from server.settings import ROOT

_VERSIONS = ROOT / "migrations" / "versions"

# The table whose rows are irreplaceable. Reference data is re-seedable and sessions are
# re-issued on next login; a deleted account is not recoverable from anything in the repo.
PROTECTED_TABLE = "app_user"

# `op.<name>(<table>, ...)` — both take the table name as their first positional argument.
DESTRUCTIVE_OPS = frozenset({"drop_table", "drop_column"})

# Calls whose string arguments are executed as SQL rather than treated as data.
SQL_SINKS = frozenset({"execute", "text"})

# Destructive SQL, as it looks after whitespace normalisation. `ALTER COLUMN ... SET NOT
# NULL` is here because it is the one *non*-dropping statement that can still fail a
# non-empty table outright, or silently rewrite every row when paired with a default.
DESTRUCTIVE_SQL = (
    "drop column",
    "drop table",
    "delete from",
    "truncate",
    "set not null",
)


def _migration_files() -> list[pathlib.Path]:
    return sorted(p for p in _VERSIONS.glob("*.py") if not p.name.startswith("_"))


def _upgrade_body(source: str, name: str) -> ast.FunctionDef:
    """The module-level `def upgrade()`, or a failure — never a silent skip.

    A migration whose `upgrade` this cannot find would otherwise be scanned as an empty
    body and pass, which is the vacuity mode every guard in this repo is written against.
    """
    module = ast.parse(source, filename=name)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return node
    raise AssertionError(f"{name} has no module-level `def upgrade()`")


def _normalise_sql(value: str) -> str:
    """Lowercase, and collapse every run of whitespace — newlines included — to one space.

    A triple-quoted statement broken across lines must match the same patterns as a
    one-liner, or the guard is defeated by pressing Enter.
    """
    return re.sub(r"\s+", " ", value).strip().lower()


def _destructive_ops(fn: ast.FunctionDef) -> list[str]:
    """Arm 1: `op.drop_table`/`op.drop_column` naming the protected table."""
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in DESTRUCTIVE_OPS or not node.args:
            continue
        table = node.args[0]
        if isinstance(table, ast.Constant) and table.value == PROTECTED_TABLE:
            found.append(f"line {node.lineno}: op.{node.func.attr} on {PROTECTED_TABLE!r}")
    return found


def _destructive_sql(fn: ast.FunctionDef) -> list[str]:
    """Arm 2: a string literal reaching `op.execute(...)` or `sa.text(...)`.

    Every string anywhere inside the sink's arguments is checked, which is what covers
    `op.execute(sa.text("..."))` without special-casing the nesting.
    """
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in SQL_SINKS:
            continue
        for argument in node.args:
            for literal in ast.walk(argument):
                if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
                    continue
                sql = _normalise_sql(literal.value)
                if PROTECTED_TABLE not in sql:
                    continue
                for verb in DESTRUCTIVE_SQL:
                    if verb in sql:
                        found.append(
                            f"line {node.lineno}: op.{node.func.attr} SQL containing "
                            f"{verb!r} against {PROTECTED_TABLE!r}"
                        )
    return found


def test_there_are_migrations_to_check() -> None:
    """Non-vacuity: an empty or moved `versions/` directory must not read as compliance."""
    assert _migration_files(), f"no migrations found under {_VERSIONS}"


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.stem)
def test_upgrade_does_not_destroy_app_user(path: pathlib.Path) -> None:
    upgrade = _upgrade_body(path.read_text(encoding="utf-8"), path.name)
    offences = _destructive_ops(upgrade) + _destructive_sql(upgrade)
    assert not offences, (
        f"{path.name}'s upgrade() would destroy `{PROTECTED_TABLE}` data:\n  "
        + "\n  ".join(offences)
        + f"\n\nProduction holds real accounts. A migration touching `{PROTECTED_TABLE}` "
        "must be additive; see CLAUDE.md, 'Production data durability'."
    )
