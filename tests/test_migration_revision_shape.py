"""Two executable invariants over `migrations/versions/`, replacing prose deleted 2026-09-01.

A CHECK name the convention re-derives doubles (`ck_invite_ck_invite_max_uses_positive`) and
Alembic 1.19 compares CHECK constraints BY NAME, so it is a silent `alembic check` failure.
An enum built without `create_type=False` on the **postgresql dialect's** `ENUM` emits a
second `CREATE TYPE` and fails `type activity_kind already exists`; `sa.Enum` accepts that
keyword and discards it, so the wrong class looks correct. Both claims are executed below
against the installed libraries rather than asserted from memory.
"""

import ast
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from server.models import NAMING_CONVENTION, Base
from server.settings import ROOT

VERSIONS: Final = ROOT / "migrations" / "versions"

CONSTRAINT_NAME_TOKEN: Final = "%(constraint_name)s"

# Read off the real convention, so adding the token to another key extends this guard for
# free and removing it from `ck` cannot leave a detector quietly scanning for nothing.
DERIVING_KEYS: Final[frozenset[str]] = frozenset(
    key for key, pattern in NAMING_CONVENTION.items() if CONSTRAINT_NAME_TOKEN in pattern
)

SA_CONSTRUCT_KEYS: Final[dict[str, str]] = {
    "CheckConstraint": "ck",
    "UniqueConstraint": "uq",
    "ForeignKeyConstraint": "fk",
    "PrimaryKeyConstraint": "pk",
    "Index": "ix",
}
# Where `name` sits when it is passed positionally; absent means keyword-only in practice,
# because the leading positional arguments are columns.
SA_NAME_POSITION: Final[dict[str, int]] = {
    "CheckConstraint": 1,
    "ForeignKeyConstraint": 2,
    "Index": 0,
}

OP_CONSTRUCT_KEYS: Final[dict[str, str]] = {
    "create_check_constraint": "ck",
    "create_unique_constraint": "uq",
    "create_foreign_key": "fk",
    "create_primary_key": "pk",
    "create_index": "ix",
    "drop_index": "ix",
}
# `op.drop_constraint` with no `type_` builds a bare `Constraint`, which no convention key
# matches — so it takes its name literally and is out of scope.
DROP_CONSTRAINT_KEYS: Final[dict[str, str]] = {
    "check": "ck",
    "unique": "uq",
    "foreignkey": "fk",
    "primary": "pk",
}
OP_NAME_KEYWORDS: Final = ("constraint_name", "index_name", "name")
OP_TABLE_KEYWORDS: Final = ("table_name", "source_table", "source")

FINAL_NAME_CALLS: Final = frozenset({"op.f", "f", "conv"})
ENUM_LEAVES: Final = frozenset({"ENUM", "Enum"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation: where it is, and the sentence the next author needs."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"  {self.path}:{self.line} {self.message}"


def revisions() -> list[Path]:
    """Every revision file. Alembic globs `*.py`, so a stale `.pyc` is not one."""
    return sorted(VERSIONS.glob("*.py"))


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"`, so a name passed through a constant still resolves."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = value.value
    return found


def _literal_name(node: ast.expr, constants: dict[str, str]) -> str | None:
    """The string this name argument resolves to; `None` when `op.f()` already made it final."""
    if isinstance(node, ast.Call) and _dotted(node.func) in FINAL_NAME_CALLS:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _name_argument(
    call: ast.Call, position: int | None, keywords: tuple[str, ...]
) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg in keywords:
            return keyword.value
    if position is not None and len(call.args) > position:
        return call.args[position]
    return None


def _derived_prefix(key: str) -> str:
    """The literal head of the convention's own output, e.g. `ck_` — never hardcoded."""
    return NAMING_CONVENTION[key].split("%", 1)[0]


def _dropped_key(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "type_" and isinstance(keyword.value, ast.Constant):
            return DROP_CONSTRAINT_KEYS.get(str(keyword.value.value))
    return None


def _enclosing_tables(tree: ast.Module, constants: dict[str, str]) -> dict[int, str]:
    """Which `op.create_table` each nested constraint call sits in, so the message can name it."""
    tables: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _dotted(node.func).rsplit(".", 1)[-1] != "create_table":
            continue
        argument = _name_argument(node, 0, ("table_name", "name"))
        table = _literal_name(argument, constants) if argument is not None else None
        if table is None:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                tables[id(child)] = table
    return tables


def constraint_name_findings(path: Path, tree: ast.Module) -> tuple[list[Finding], int]:
    """Names that the convention would re-derive, plus how many names were inspected at all."""
    constants = _module_strings(tree)
    tables = _enclosing_tables(tree, constants)
    findings: list[Finding] = []
    inspected = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _dotted(node.func)
        leaf = called.rsplit(".", 1)[-1]
        table = tables.get(id(node))
        if leaf in SA_CONSTRUCT_KEYS:
            key = SA_CONSTRUCT_KEYS[leaf]
            argument = _name_argument(node, SA_NAME_POSITION.get(leaf), ("name",))
        elif leaf in OP_CONSTRUCT_KEYS or leaf == "drop_constraint":
            dropped = OP_CONSTRUCT_KEYS.get(leaf) or _dropped_key(node)
            if dropped is None:
                continue
            key = dropped
            argument = _name_argument(node, 0, OP_NAME_KEYWORDS)
            named = _name_argument(node, 1, OP_TABLE_KEYWORDS)
            table = _literal_name(named, constants) if named is not None else table
        else:
            continue
        if key not in DERIVING_KEYS or argument is None:
            continue
        inspected += 1
        value = _literal_name(argument, constants)
        if value is None or not value.startswith(_derived_prefix(key)):
            continue
        doubled = f"{_derived_prefix(key)}{table or '<table>'}_{value}"
        findings.append(
            Finding(
                path.name,
                node.lineno,
                f"{leaf}(...) is given the bare string {value!r}. The '{key}' naming "
                f"convention interpolates {CONSTRAINT_NAME_TOKEN}, so this comes back out "
                f"doubled as {doubled!r} and `alembic check` — which compares CHECK "
                f"constraints by NAME — goes red. Fix it one of two ways: wrap it as "
                f"op.f({value!r}) to declare the name already final, or pass only the "
                f"suffix and let the convention build the prefix.",
            )
        )
    return sorted(findings, key=lambda found: found.line), inspected


def enum_findings(path: Path, tree: ast.Module) -> tuple[list[Finding], int]:
    """Enum constructions that would emit a second CREATE TYPE, plus how many were seen."""
    findings: list[Finding] = []
    inspected = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _dotted(node.func)
        leaf = called.rsplit(".", 1)[-1]
        if leaf not in ENUM_LEAVES:
            continue
        inspected += 1
        if leaf == "Enum":
            findings.append(
                Finding(
                    path.name,
                    node.lineno,
                    f"{called}(...) cannot suppress CREATE TYPE. `create_type` lives on the "
                    f"postgresql dialect's ENUM, and a generic sa.Enum accepts the keyword "
                    f"and DISCARDS it — the adapted native type defaults back to True, so "
                    f"the second table using the type fails 'already exists'. Build it as "
                    f"postgresql.ENUM(..., create_type=False) and create the type once, "
                    f"explicitly, with .create(op.get_bind(), checkfirst=True).",
                )
            )
            continue
        suppressed = any(
            keyword.arg == "create_type"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in node.keywords
        )
        if suppressed:
            continue
        findings.append(
            Finding(
                path.name,
                node.lineno,
                f"{called}(...) has no create_type=False, so CREATE TABLE emits an implicit "
                f"CREATE TYPE for it and the second table using the type fails 'already "
                f"exists'. Add create_type=False and create the type once, explicitly, with "
                f".create(op.get_bind(), checkfirst=True) at the top of upgrade().",
            )
        )
    return sorted(findings, key=lambda found: found.line), inspected


def _scan() -> tuple[list[Finding], int, list[Finding], int]:
    names: list[Finding] = []
    name_count = 0
    enums: list[Finding] = []
    enum_count = 0
    for path in revisions():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found, seen = constraint_name_findings(path, tree)
        names.extend(found)
        name_count += seen
        found, seen = enum_findings(path, tree)
        enums.extend(found)
        enum_count += seen
    return names, name_count, enums, enum_count


@pytest.fixture(scope="module")
def scan() -> tuple[list[Finding], int, list[Finding], int]:
    return _scan()


def test_no_revision_hands_a_pre_derived_name_to_an_op_call(
    scan: tuple[list[Finding], int, list[Finding], int],
) -> None:
    """Invariant A. `op.*` applies the convention itself, so a pre-derived name doubles."""
    findings = scan[0]
    formatted = "\n".join(str(finding) for finding in findings)
    assert not findings, f"{len(findings)} pre-derived constraint name(s):\n{formatted}"


def test_every_enum_in_a_revision_suppresses_the_implicit_create_type(
    scan: tuple[list[Finding], int, list[Finding], int],
) -> None:
    """Invariant B. The implicit CREATE TYPE is what fails on the second table."""
    findings = scan[2]
    formatted = "\n".join(str(finding) for finding in findings)
    assert not findings, f"{len(findings)} unsuppressed enum construction(s):\n{formatted}"


def test_neither_detector_ran_over_nothing(
    scan: tuple[list[Finding], int, list[Finding], int],
) -> None:
    """A green scan of zero call sites is not a green scan. Both counts are measurements."""
    assert DERIVING_KEYS, (
        f"no NAMING_CONVENTION key interpolates {CONSTRAINT_NAME_TOKEN}, so invariant A "
        f"cannot fire. If the convention really changed, re-read this whole file."
    )
    assert scan[1] > 0, "invariant A inspected no constraint name in any revision"
    assert scan[3] > 0, "invariant B inspected no enum construction in any revision"


def _findings_for(source: str) -> tuple[list[Finding], list[Finding]]:
    tree = ast.parse(source)
    return (
        constraint_name_findings(Path("sample.py"), tree)[0],
        enum_findings(Path("sample.py"), tree)[0],
    )


SAMPLE_DOUBLED: Final = """
import sqlalchemy as sa
from alembic import op

PRE_DERIVED = "ck_invite_uses_within_max"


def upgrade() -> None:
    op.create_table(
        "invite",
        sa.CheckConstraint("max_uses >= 1", name="ck_invite_max_uses_positive"),
        sa.UniqueConstraint("code_hash", name="uq_invite_code_hash"),
    )
    op.create_check_constraint(PRE_DERIVED, "invite", "uses <= max_uses")
    op.drop_constraint("ck_invite_max_uses_positive", "invite", type_="check")
"""

SAMPLE_COMPLIANT: Final = """
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

activity_kind = postgresql.ENUM("climbing", name="activity_kind", create_type=False)


def upgrade() -> None:
    activity_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "invite",
        sa.CheckConstraint("max_uses >= 1", name="max_uses_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_invite"),
        sa.Column("kind", activity_kind),
    )
    op.create_check_constraint(op.f("ck_invite_uses_within_max"), "invite", "uses <= max_uses")
    op.drop_constraint("fk_app_user_invite_id_invite", "app_user", type_="foreignkey")
"""

SAMPLE_ENUMS: Final = """
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

leaked = postgresql.ENUM("a", "b", name="phase")
wrong_class = sa.Enum("a", "b", name="phase", create_type=False)
"""


def test_the_doubling_detector_sees_all_three_shapes_of_the_mistake() -> None:
    """Positive control. A detector nobody has watched fail is not evidence of anything."""
    names, _ = _findings_for(SAMPLE_DOUBLED)
    assert [finding.line for finding in names] == [11, 14, 15]
    assert "ck_invite_ck_invite_max_uses_positive" in names[0].message
    assert "ck_invite_ck_invite_uses_within_max" in names[1].message


def test_the_doubling_detector_clears_a_suffix_an_op_f_and_every_other_key() -> None:
    """The three false positives worth being sure about: `uq`/`pk`/`fk` take names literally."""
    names, enums = _findings_for(SAMPLE_COMPLIANT)
    assert names == []
    assert enums == []


def test_the_enum_detector_sees_a_missing_flag_and_the_wrong_class() -> None:
    """Positive control on both arms — the silent one is `sa.Enum` accepting the keyword."""
    _, enums = _findings_for(SAMPLE_ENUMS)
    assert [finding.line for finding in enums] == [5, 6]
    assert "no create_type=False" in enums[0].message
    assert "DISCARDS it" in enums[1].message


def test_the_convention_really_doubles_a_pre_derived_check_name() -> None:
    """Invariant A's premise, executed against the installed Alembic. No database."""
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "target_metadata": Base.metadata, "output_buffer": buffer},
    )
    Operations(context).create_check_constraint(
        "ck_invite_max_uses_positive", "invite", "max_uses >= 1"
    )
    Operations(context).create_unique_constraint("uq_invite_code_hash", "invite", ["code_hash"])
    emitted = buffer.getvalue()
    assert "ck_invite_ck_invite_max_uses_positive" in emitted
    assert "uq_invite_uq_invite_code_hash" not in emitted


def test_the_generic_enum_really_discards_create_type() -> None:
    """Invariant B's premise, executed against the installed SQLAlchemy. No database."""
    plain = sa.Enum("a", "b", name="ct_guard_probe", create_type=False)
    assert not hasattr(plain, "create_type")
    adapted = postgresql.ENUM.adapt_emulated_to_native(plain)  # type: ignore[no-untyped-call]
    assert adapted.create_type is True
    assert postgresql.ENUM("a", name="ct_guard_probe", create_type=False).create_type is False
