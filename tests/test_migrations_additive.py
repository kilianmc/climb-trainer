"""A migration's `upgrade()` must never destroy user-owned rows.

Production carries real user data, and migrations are the one thing in this project that
can delete it irreversibly: a deploy can be rolled back, a bad row can be fixed, but
`DROP COLUMN` is gone the moment it commits. Per the testing policy in CLAUDE.md this is
the "anything that can lose user data" bullet, and per CLAUDE.md's own guidance it is a
"don't change this or X breaks" rule converted into a test rather than left as prose.

**`downgrade()` bodies are deliberately ignored.** They are *supposed* to be destructive —
`0003`'s downgrade drops `app_user.invite_id` and the `invite` table, correctly, and
`0004`'s drops the whole domain schema — so a whole-file scan would fail on the existing
repo. That asymmetry is exactly why this reads the AST and scopes itself to the `upgrade`
function rather than grepping the file. The protection against a downgrade reaching
production is structural instead: `migrate.yml` offers no `downgrade` action, and recovery
is a Neon branch restore.

## The protected set is a FLOOR, unioned with a derivation

It used to be the single string `app_user`, which was right when accounts were the only
irreplaceable rows. `0004` added twenty-four tables, and a climber's ascents, diary entries
and logged sets are every bit as unrecoverable as the account they hang off.

Half of the answer is a **derivation** from `Base.metadata`: `app_user`, plus every table
that reaches it through foreign keys, transitively. That means a new table with a `user_id`
column is protected the moment it is declared, with no edit here — which a hand-written
list would have needed in every such PR, and would have been forgotten exactly once.

⚠️ **The derivation alone is WEAKER than the hard-coded string it replaced, against the
exact scenario this file exists for.** To drop `ascent`, a PR deletes the `Ascent` model
*and* writes `op.drop_table("ascent")` — at which point `ascent` is no longer reachable in
`Base.metadata`, the derived set no longer contains it, and arm 1 waves it through. Derived
alone, this guard only fires when a migration **disagrees** with the models, which is
precisely what `alembic check` already covers; it would have stopped covering the case
where they agree and are both wrong. So the derivation is unioned with
`PROTECTED_TABLE_FLOOR`, a literal list that a deleted model cannot delete.

Three honest notes:

- The floor is asserted to be a **subset of the derivation** today, which is what stops it
  rotting into a list of misspelled or long-gone table names.
- **`auth_session` is included and is not really irreplaceable** — a refresh token row is
  re-issued on the next login. Excluding it would mean an exception list, and an exception
  list is the thing that grows until the guard means nothing. It stays in.
- **Reference tables are excluded, but that does not make them free to drop.**
  `grade`, `exercise`, `equipment`, `ascent_tag` and the rest are re-seedable from
  `server/seed.py`, so losing their rows is recoverable — which is why they are out of
  scope *here*. Dropping one is still blocked by the foreign key graph
  (`logged_set.exercise_id` and `session_block.exercise_id` are `NO ACTION` references into
  `exercise`), and forcing it through with `CASCADE` would orphan user rows. That is a
  different failure, caught by a different thing; it is not this guard saying yes.
- ⚠️ **`invite` is in the floor, and "re-seedable" was never true of it.** The derivation
  cannot reach it — the foreign key points *from* `app_user` *into* `invite`, so no walk
  outward from `app_user` ever finds it — and its rows are created at runtime by an operator
  (`python -m server.admin create-invite`), never by the seed. `invite.label` is the only
  record of who invited whom, which is why the column exists at all and why
  `app_user.invite_id` is `ON DELETE RESTRICT`. `op.drop_column("invite", "label")` was
  silently permitted until 2026-08-21.
- **`rate_limit` stays out**, genuinely: a fixed-window counter is ephemeral by
  construction, so dropping it costs one window of protection and no history.

## Six arms, because there are six ordinary ways to write the same damage

1. **Alembic drop ops** — `op.drop_table("app_user")`, `op.drop_column("ascent", "notes")`,
   **and their keyword forms** (`op.drop_column(table_name=..., column_name=...)`). An
   earlier version read `node.args[0]` only, so the keyword spelling — which is a normal
   way to write the op, not an exotic bypass — defeated the guard completely.
2. **`op.alter_column(..., nullable=False)`** — the `SET NOT NULL` that CLAUDE.md names as
   forbidden without a backfill plan. The docstring used to claim this was covered when
   only the raw-SQL arm caught it, i.e. a named rule was unguarded while the file said
   otherwise.
3. **`op.drop_constraint(...)`** naming a protected table — dropping a unique constraint or
   a foreign key is how a later bad write becomes possible.
4. **`op.rename_table("ascent", "ascent_old")`**, followed by
   `op.drop_table("ascent_old")` — a name no longer in the protected set. Two ordinary ops,
   and not an exotic bypass: rename-then-drop is the usual spelling of the *contract* phase
   in the expand -> deploy -> contract discipline this repo mandates, and if the model is
   renamed in the same PR then `alembic check` agrees with it too. A rename of a protected
   table is flagged outright, on the same reasoning the `NULLABILITY_OPS` note gives for
   `new_column_name`: a rename is a breaking change whether or not it loses a row.
5. **`with op.batch_alter_table("ascent") as b: b.drop_column(...)`** — the batch context
   manager routes the same ops through a different object, so arms 1-4 never see them.
6. **Raw SQL** — `op.execute("ALTER TABLE app_user DROP COLUMN email")` bypasses all of
   the above. This arm flags a string literal that mentions a protected table together
   with a destructive verb, **including `UPDATE ... SET col = NULL`**, which is irreversible
   loss of user notes and was not previously matched by anything.

**Arm 6 is deliberately crude, and over-flags rather than under-flags.** It is a substring
match against a normalised copy of the string, not a SQL parser: a false positive costs a
developer one minute reading this file, a false negative costs production rows. If a
legitimate migration ever trips it, add the narrowest possible exemption *with a comment
saying why* — do not loosen the pattern.

⚠️ **Limits worth stating rather than implying.** Arm 6 is *presented* as covering
irreversible note loss, so the ways it does not are worth naming rather than discovering.
Everything below is MISSED, none of it is realistic enough in this repo to be worth the
machinery, and all of it needs human review regardless:

- **String LITERALS only, for the SQL text.** A `+` concatenation, or SQL read from a
  variable or a constant defined elsewhere, is invisible. **This gap is NARROWER than an
  earlier draft of this file claimed:** a literal table name inside an **f-string** *is*
  still caught, because `ast.walk` reaches the `Constant` parts of a `JoinedStr` — only the
  interpolated segments are opaque.
- **Indirect dispatch.** `getattr(op, "drop_column")("ascent", "notes")` matches no
  attribute name, so arms 1-5 never see it.
- **`op.execute` of a SQLAlchemy construct** — `update(Ascent).values(notes=None)` — is not
  inspected. Nothing in `migrations/` does this today.
- **Three spellings of a null-ing UPDATE the arm-6 pattern cannot match**: `SET x = DEFAULT`;
  a row constructor, `SET (a, b) = (NULL, NULL)`, which contains no `= NULL` anywhere; and
  `SET notes = ''`, which destroys a note as thoroughly as NULL while reading as a tidy-up.
- **A table name passed to an op as a variable** rather than as a literal.

**No database.** This is a file inspection, so it runs in the local gate as well as CI —
which matters, because the mistake it catches is made while writing a migration, long
before anything is applied.

Every arm carries a **positive control** at the bottom of this file, and every entry in
`DESTRUCTIVE_SQL` has one written in an *independent* spelling: a detector nobody has seen
fail is a detector nobody should trust, and a control assembled from the constant it tests
would cheerfully confirm a typo to itself.
"""

import ast
import pathlib
import re

import pytest
from sqlalchemy import MetaData

from server.models import Base
from server.settings import ROOT

_VERSIONS = ROOT / "migrations" / "versions"

# The root of ownership. Everything reachable from here is somebody's data.
OWNER_TABLE = "app_user"

# ⚠️ **The floor. A literal list, because deleting a model must not delete its own
# protection.** See the module docstring. Every name here is asserted to still exist in the
# derived set by `test_the_floor_is_a_subset_of_the_derivation`, so this cannot silently
# become a list of typos.
PROTECTED_TABLE_FLOOR = frozenset(
    {
        "app_user",
        "auth_session",
        "user_profile",
        "user_equipment",
        "user_aspect_rating",
        "user_injury",
        "plan",
        "mesocycle",
        "microcycle",
        "planned_session",
        "session_block",
        "prescribed_set",
        "activity",
        "logged_session",
        "logged_set",
        "ascent",
        "ascent_tag_link",
        "journal_entry",
        # NOT reachable by the derivation: app_user points INTO invite, not the other way,
        # so a walk outward from app_user never arrives here. Operator-authored, never
        # seeded, and the only record of who invited whom.
        "invite",
    }
)


def _derived_protected_tables(metadata: MetaData) -> frozenset[str]:
    """`app_user` plus every table transitively holding a foreign key into it."""
    owned = {OWNER_TABLE}
    grew = True
    while grew:
        grew = False
        for table in metadata.sorted_tables:
            if table.name in owned:
                continue
            if any(key.column.table.name in owned for key in table.foreign_keys):
                owned.add(table.name)
                grew = True
    return frozenset(owned)


def _protected_tables(metadata: MetaData) -> frozenset[str]:
    """The floor, plus whatever the live models add to it. Never less than the floor."""
    return PROTECTED_TABLE_FLOOR | _derived_protected_tables(metadata)


PROTECTED_TABLES = _protected_tables(Base.metadata)

# `op.drop_table(table)` / `op.drop_column(table, column)` — the table is the first
# positional argument, or the `table_name` keyword.
DESTRUCTIVE_OPS = frozenset({"drop_table", "drop_column"})

# `op.drop_constraint(constraint_name, table_name, ...)` — the table is the SECOND
# positional argument here, which is exactly why it needs its own entry rather than
# joining the set above.
CONSTRAINT_OPS = frozenset({"drop_constraint"})

# Ops that are destructive only for certain arguments: `alter_column(..., nullable=False)`
# is `SET NOT NULL`, which fails outright on a non-empty table or, with a default, rewrites
# every row. `alter_column(..., new_column_name=...)` is a rename, which loses nothing but
# breaks the running code — out of scope here.
NULLABILITY_OPS = frozenset({"alter_column"})

# `op.rename_table(old_table_name, new_table_name)` — the table is the first positional
# argument, like the drop ops, but it needs its own set because it is flagged
# UNCONDITIONALLY: renaming a protected table both breaks the running code and takes the
# table out of `PROTECTED_TABLES`, so a following `op.drop_table(<new name>)` is invisible.
RENAME_OPS = frozenset({"rename_table"})

# Methods on a `batch_alter_table` context object that destroy data.
BATCH_DESTRUCTIVE_METHODS = frozenset({"drop_column", "drop_constraint", "alter_column"})

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

# Patterns that a substring cannot express. `UPDATE ascent SET notes = NULL` destroys user
# notes as thoroughly as a DROP and reads as an ordinary data fix-up.
DESTRUCTIVE_SQL_PATTERNS = ((r"\bupdate\b.*\bset\b.*=\s*null", "update ... set ... = null"),)


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


def _table_argument(node: ast.Call, position: int) -> str | None:
    """The table name a call names, positionally OR by `table_name=` keyword.

    Reading `node.args[0]` alone is what let `op.drop_column(table_name="ascent", ...)`
    through — a spelling nobody would call exotic.
    """
    if len(node.args) > position:
        candidate = node.args[position]
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value
    for keyword in node.keywords:
        if keyword.arg == "table_name" and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            if isinstance(value, str):
                return value
    return None


def _sets_not_null(node: ast.Call) -> bool:
    """`alter_column(..., nullable=False)` — positional `nullable` is not a thing."""
    for keyword in node.keywords:
        if keyword.arg == "nullable" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is False
    return False


def _destructive_ops(fn: ast.FunctionDef) -> list[str]:
    """Arms 1-3: Alembic ops naming a protected table, positionally or by keyword."""
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        if name in DESTRUCTIVE_OPS or name in RENAME_OPS:
            table = _table_argument(node, 0)
        elif name in CONSTRAINT_OPS or name in NULLABILITY_OPS:
            # drop_constraint(constraint_name, table_name, ...) and
            # alter_column(table_name, column_name, ...) — different positions, so the
            # position is passed in rather than assumed.
            table = _table_argument(node, 1 if name in CONSTRAINT_OPS else 0)
        else:
            continue
        if table not in PROTECTED_TABLES:
            continue
        if name in NULLABILITY_OPS and not _sets_not_null(node):
            # A column type change is not this guard's business. A column *rename* is a
            # breaking change, but it loses no row and Alembic spells it with
            # `new_column_name` — out of scope here, deliberately, and named in the
            # module docstring's limits so it is a decision rather than an oversight.
            continue
        if name in RENAME_OPS:
            detail = " (rename: takes the table OUT of the protected set)"
        elif name in NULLABILITY_OPS:
            detail = " (SET NOT NULL)"
        else:
            detail = ""
        found.append(f"line {node.lineno}: op.{name} on {table!r}{detail}")
    return found


def _destructive_batch_ops(fn: ast.FunctionDef) -> list[str]:
    """Arm 4: `with op.batch_alter_table("ascent") as b: b.drop_column(...)`.

    Batch mode routes the same operations through a context object, so arms 1-3 — which
    match on `op.<name>(<table>, ...)` — never see the table name at all. Scoped to the
    `with` body so that a batch block doing only additive work is not flagged.
    """
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr != "batch_alter_table":
                continue
            table = _table_argument(call, 0)
            if table not in PROTECTED_TABLES:
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call) or not isinstance(inner.func, ast.Attribute):
                    continue
                if inner.func.attr not in BATCH_DESTRUCTIVE_METHODS:
                    continue
                if inner.func.attr in NULLABILITY_OPS and not _sets_not_null(inner):
                    continue
                found.append(
                    f"line {inner.lineno}: batch {inner.func.attr} inside "
                    f"batch_alter_table({table!r})"
                )
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
                mentioned = sorted(table for table in PROTECTED_TABLES if table in sql)
                if not mentioned:
                    continue
                for verb in DESTRUCTIVE_SQL:
                    if verb in sql:
                        found.append(
                            f"line {node.lineno}: op.{node.func.attr} SQL containing "
                            f"{verb!r} against {mentioned}"
                        )
                for pattern, label in DESTRUCTIVE_SQL_PATTERNS:
                    if re.search(pattern, sql):
                        found.append(
                            f"line {node.lineno}: op.{node.func.attr} SQL containing "
                            f"{label!r} against {mentioned}"
                        )
    return found


def test_there_are_migrations_to_check() -> None:
    """Non-vacuity: an empty or moved `versions/` directory must not read as compliance."""
    assert _migration_files(), f"no migrations found under {_VERSIONS}"


def test_the_protected_set_is_derived_and_not_trivial() -> None:
    """Non-vacuity for the derivation itself.

    If the walk ever returned just `{'app_user'}` — a refactor that broke the foreign-key
    traversal, say — every other test here would still pass while protecting almost
    nothing. It also pins the two ends of the transitive chain: `logged_set` is four
    tables away from `app_user`, and `grade` is reference data that must NOT be in the set.
    """
    assert OWNER_TABLE in PROTECTED_TABLES
    assert {"ascent", "journal_entry", "logged_set", "prescribed_set"} <= PROTECTED_TABLES
    assert not ({"grade", "grade_system", "exercise", "equipment"} & PROTECTED_TABLES)


def test_the_floor_survives_its_models_being_deleted() -> None:
    """⚠️ The reason the floor exists, asserted rather than described.

    Empty metadata stands in for "somebody deleted the `Ascent` model in the same PR that
    dropped the table". The derivation collapses to `{app_user}`; the union must not.
    """
    assert _derived_protected_tables(MetaData()) == {OWNER_TABLE}
    assert _protected_tables(MetaData()) == PROTECTED_TABLE_FLOOR
    assert "ascent" in _protected_tables(MetaData())
    assert "logged_set" in _protected_tables(MetaData())


def test_the_floor_and_the_derivation_are_EXACTLY_equal() -> None:
    """⚠️ Equality, not `<=`. One-directional was a hole that could not stay closed.

    Both directions matter, and each catches a different rot:

    - **floor - derived** = a floor entry that is no longer a real, user-owned table, i.e. a
      typo or a name left behind by a rename. It would look like protection and be none.
    - **derived - floor** = a NEW user-owned table that nobody added to the floor. That was
      the live hole: it passed a `<=` assertion silently, so nothing ever prompted the
      update — and then a second PR could delete the model *and* drop the table, at which
      point the derivation no longer contains it, the floor never did, arm 1 waves it
      through, and `alembic check` agrees because the models and the migration agree and
      are both wrong. That is verbatim the scenario the floor exists to stop, reachable in
      two ordinary PRs.

    `invite` is the one deliberate exception, and it is spelled out rather than tolerated:
    the FK points from `app_user` INTO `invite`, so no outward walk can reach it.
    """
    derived = _derived_protected_tables(Base.metadata)
    assert PROTECTED_TABLE_FLOOR == derived | {"invite"}, (
        "the floor and the derivation have diverged.\n"
        f"  in the floor but not user-owned in the models: "
        f"{sorted(PROTECTED_TABLE_FLOOR - derived - {'invite'})}\n"
        f"  user-owned in the models but missing from the floor: "
        f"{sorted(derived - PROTECTED_TABLE_FLOOR)}\n"
        "Add the new table to PROTECTED_TABLE_FLOOR: a table protected only by the "
        "derivation loses that protection the moment its model is deleted."
    )


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.stem)
def test_upgrade_does_not_destroy_user_data(path: pathlib.Path) -> None:
    upgrade = _upgrade_body(path.read_text(encoding="utf-8"), path.name)
    offences = (
        _destructive_ops(upgrade) + _destructive_batch_ops(upgrade) + _destructive_sql(upgrade)
    )
    assert not offences, (
        f"{path.name}'s upgrade() would destroy user-owned data:\n  "
        + "\n  ".join(offences)
        + "\n\nProduction holds real accounts and real training history. A migration "
        "touching a user-owned table must be additive; see CLAUDE.md, 'Production data "
        "durability'."
    )


# --- Positive controls -----------------------------------------------------------------
#
# Each arm gets a migration that DOES violate the rule, and the near-misses matter as much
# as the hits: an over-eager arm would fail on legitimate work and get loosened, and
# loosening is how a guard quietly stops guarding.
#
# Kilian's standing rule is that a guard is not trusted until it has been SHOWN to fail.
# Every arm below has been.

_VIOLATING_OPS_POSITIONAL = """
def upgrade() -> None:
    op.drop_column("ascent", "notes")
"""

# The spelling that defeated this guard entirely before 2026-08-21.
_VIOLATING_OPS_KEYWORD = """
def upgrade() -> None:
    op.drop_column(table_name="ascent", column_name="notes")
"""

_VIOLATING_SET_NOT_NULL = """
def upgrade() -> None:
    op.alter_column("app_user", "password_hash", nullable=False)
"""

_VIOLATING_DROP_CONSTRAINT = """
def upgrade() -> None:
    op.drop_constraint("uq_ascent_user_id_client_uuid", "ascent", type_="unique")
"""

_VIOLATING_RENAME = """
def upgrade() -> None:
    op.rename_table("ascent", "ascent_old")
    op.drop_table("ascent_old")
"""

_VIOLATING_BATCH = """
def upgrade() -> None:
    with op.batch_alter_table("ascent") as batch_op:
        batch_op.drop_column("notes")
"""

_VIOLATING_SQL = '''
def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE journal_entry
        DROP COLUMN body
    """))
'''

_VIOLATING_UPDATE_TO_NULL = """
def upgrade() -> None:
    op.execute("UPDATE ascent SET notes = NULL")
"""

# Additive work on a protected table, plus a data write that is NOT a null-ing, plus a
# batch block that only adds. None of it may be flagged.
_INNOCENT = """
def upgrade() -> None:
    op.create_table("ascent", sa.Column("notes", sa.String(length=10)))
    op.add_column("ascent", sa.Column("board_angle", sa.SmallInteger()))
    op.create_index("ix_ascent_climbed_on", "ascent", ["climbed_on"])
    op.execute(sa.text("UPDATE ascent SET board_angle = 0 WHERE board_angle IS NULL"))
    op.alter_column("ascent", "notes", type_=sa.String(length=20))
    with op.batch_alter_table("ascent") as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=10)))
"""

# ⚠️ Independent spellings, NOT built from DESTRUCTIVE_SQL — a control assembled from the
# constant it is testing would happily confirm a typo ("trunacte") to itself.
_SQL_CONTROLS = {
    "drop column": "ALTER TABLE ascent DROP COLUMN notes",
    "drop table": "DROP TABLE journal_entry",
    "delete from": "DELETE FROM logged_set WHERE id > 0",
    "truncate": "TRUNCATE TABLE ascent",
    "set not null": "ALTER TABLE app_user ALTER COLUMN password_hash SET NOT NULL",
}


def test_every_destructive_verb_has_a_control() -> None:
    """Adding a verb without a control, or misspelling one, must fail here.

    Four of the five verbs had no control at all until 2026-08-21: a typo in the constant
    would have silently disarmed that verb and no test would have noticed.
    """
    assert set(_SQL_CONTROLS) == set(DESTRUCTIVE_SQL)


@pytest.mark.parametrize("verb", sorted(_SQL_CONTROLS))
def test_detector_sees_each_destructive_verb(verb: str) -> None:
    source = f'\ndef upgrade() -> None:\n    op.execute("{_SQL_CONTROLS[verb]}")\n'
    offences = _destructive_sql(_upgrade_body(source, "synthetic"))
    assert offences, f"{verb!r} was not caught: {_SQL_CONTROLS[verb]!r}"
    assert all(verb in offence for offence in offences)


def test_detector_sees_a_dropped_column_named_positionally() -> None:
    offences = _destructive_ops(_upgrade_body(_VIOLATING_OPS_POSITIONAL, "synthetic"))
    assert offences == ["line 3: op.drop_column on 'ascent'"]


def test_detector_sees_a_dropped_column_named_by_keyword() -> None:
    """The gap that made arm 1 bypassable by ordinary formatting."""
    offences = _destructive_ops(_upgrade_body(_VIOLATING_OPS_KEYWORD, "synthetic"))
    assert offences == ["line 3: op.drop_column on 'ascent'"]


def test_detector_sees_alter_column_set_not_null() -> None:
    """The rule CLAUDE.md names and this file used to claim, wrongly, to cover."""
    offences = _destructive_ops(_upgrade_body(_VIOLATING_SET_NOT_NULL, "synthetic"))
    assert offences == ["line 3: op.alter_column on 'app_user' (SET NOT NULL)"]


def test_detector_sees_a_dropped_constraint() -> None:
    """Note the table is the SECOND positional argument here, unlike every other op."""
    offences = _destructive_ops(_upgrade_body(_VIOLATING_DROP_CONSTRAINT, "synthetic"))
    assert offences == ["line 3: op.drop_constraint on 'ascent'"]


def test_detector_sees_a_renamed_protected_table() -> None:
    """Rename-then-drop: two ordinary ops, and both were MISSED before 2026-08-21.

    Only the rename is flagged, and that is enough — the `drop_table("ascent_old")` on the
    next line genuinely cannot be recognised, because by then the name is not one this file
    knows about. Which is exactly why the rename itself has to be the tripwire.
    """
    offences = _destructive_ops(_upgrade_body(_VIOLATING_RENAME, "synthetic"))
    assert offences == [
        "line 3: op.rename_table on 'ascent' (rename: takes the table OUT of the protected set)"
    ]


def test_detector_allows_renaming_a_table_it_does_not_protect() -> None:
    """Specificity: reference tables may be reorganised freely."""
    source = '\ndef upgrade() -> None:\n    op.rename_table("equipment", "gear")\n'
    assert not _destructive_ops(_upgrade_body(source, "synthetic"))


def test_detector_sees_a_batch_alter_table_drop() -> None:
    offences = _destructive_batch_ops(_upgrade_body(_VIOLATING_BATCH, "synthetic"))
    assert offences == ["line 4: batch drop_column inside batch_alter_table('ascent')"]


def test_detector_sees_destructive_raw_sql_across_newlines() -> None:
    """The whitespace normalisation is what makes this work; without it, Enter defeats it.

    `op.execute(sa.text(...))` reports the offence TWICE — once for each sink in the nest
    — and that is left alone deliberately. Deduplicating would mean the two arms could no
    longer be read independently, and a guard that over-reports is doing its job.
    """
    offences = _destructive_sql(_upgrade_body(_VIOLATING_SQL, "synthetic"))
    assert offences, "the nested op.execute(sa.text(...)) form must be seen"
    assert all("'drop column'" in offence for offence in offences)
    assert all("journal_entry" in offence for offence in offences)


def test_detector_sees_an_update_that_nulls_a_column() -> None:
    """Irreversible loss of user notes, spelled as an ordinary data fix-up.

    No substring in `DESTRUCTIVE_SQL` can express this, which is why it is a pattern.
    """
    offences = _destructive_sql(_upgrade_body(_VIOLATING_UPDATE_TO_NULL, "synthetic"))
    assert offences == [
        "line 3: op.execute SQL containing 'update ... set ... = null' against ['ascent']"
    ]


def test_detector_ignores_additive_work() -> None:
    """Creating, adding, indexing, a non-null-ing UPDATE, a type change, an additive batch.

    Note what is NOT in here any more: `op.drop_table("exercise")` used to be, on the
    grounds that reference tables are re-seedable. That was wrong to bless in a test called
    "innocent" — `logged_set.exercise_id` and `session_block.exercise_id` are `NO ACTION`
    references into `exercise`, so the op either errors outright or, forced with CASCADE,
    orphans user rows. Out of this guard's scope is not the same as harmless.
    """
    upgrade = _upgrade_body(_INNOCENT, "synthetic")
    assert not _destructive_ops(upgrade)
    assert not _destructive_batch_ops(upgrade)
    assert not _destructive_sql(upgrade)


def test_detector_fails_loudly_on_a_migration_with_no_upgrade() -> None:
    """The vacuity mode this file was written against, asserted rather than assumed."""
    with pytest.raises(AssertionError, match="no module-level"):
        _upgrade_body("def downgrade() -> None:\n    pass\n", "synthetic")
