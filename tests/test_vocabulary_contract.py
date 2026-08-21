"""The closed vocabularies are written down THREE times. Here are the two guards.

`server/domain/vocabulary.py` is the source of truth. It is duplicated by hand into
`web/src/api/vocabularies.ts` (because OpenAPI codegen has no endpoints to generate from
until PR #9) and into `migrations/versions/0004_domain_schema.py` (because a migration must
not import live application code, or it stops describing history). Neither duplicate is
checked by anything else: `tsc` cannot see Python, and `alembic check` cannot see inside an
enum type. So both are checked here.

## Part 1 — the TypeScript copy

`web/src/api/vocabularies.ts` is written by hand because OpenAPI codegen (PR #9) has no
endpoints to generate from yet — see that file's header. **This test is what stands in
for the generator until then**, and it is the reason writing them by hand is acceptable
rather than reckless.

It satisfies the "project-wide invariants that silently rot" bullet in CLAUDE.md's
testing policy, and it is the same shape as `tests/test_version.py`: a Python test
reading a web-side file, because the invariant spans both languages and neither side can
check it alone. The drift it catches is silent in both directions — a value missing from
the TypeScript union is a feature the UI cannot express, and a value that exists only in
the TypeScript is a 422 at runtime.

## Part 2 — the migration's copy

Below the TypeScript tests. That one is the more dangerous of the two, because it decides
what values the database will physically accept; see the comment block above
`_MIGRATION` for why `alembic check` cannot see it.

DB-free, both of them, so they run in the local gate.
"""

import importlib.util
import re
from types import ModuleType

import pytest
from sqlalchemy.dialects.postgresql import ENUM

from server.domain.grades import Discipline
from server.domain.vocabulary import (
    ActivityKind,
    AscentStyle,
    Phase,
    ProtocolKind,
    SessionStatus,
)
from server.settings import ROOT

VOCABULARIES_TS = ROOT / "web" / "src" / "api" / "vocabularies.ts"

# TypeScript array name -> the Python enum it mirrors. Adding an enum to one side without
# the other fails `test_every_enum_is_mirrored`, so this mapping is the full contract.
MIRRORED = {
    "DISCIPLINES": Discipline,
    "ACTIVITY_KINDS": ActivityKind,
    "ASCENT_STYLES": AscentStyle,
    "PROTOCOL_KINDS": ProtocolKind,
    "PHASES": Phase,
    "SESSION_STATUSES": SessionStatus,
}

# `export const NAME = [ ... ] as const;` — the literal form the TS file is required to
# use. Anything assembled, spread or imported would not match, which is deliberate: this
# parser is why that file says "written as plain literals".
_ARRAY = re.compile(r"export const (\w+) = \[(.*?)\] as const;", re.DOTALL)
_VALUE = re.compile(r"'([^']*)'")


def _parse(source: str) -> dict[str, list[str]]:
    """Every `as const` string array in a TypeScript source, in file order."""
    return {name: _VALUE.findall(body) for name, body in _ARRAY.findall(source)}


@pytest.fixture(scope="module")
def parsed() -> dict[str, list[str]]:
    assert VOCABULARIES_TS.is_file(), f"{VOCABULARIES_TS} is missing"
    return _parse(VOCABULARIES_TS.read_text(encoding="utf-8"))


def test_every_enum_is_mirrored(parsed: dict[str, list[str]]) -> None:
    """Non-vacuity: a renamed or deleted array must fail loudly, not silently pass.

    Without this, dropping `PHASES` from the TypeScript would make the parametrised test
    below collect one fewer case and stay green.
    """
    assert set(parsed) == set(MIRRORED), (
        f"vocabularies.ts exports {sorted(parsed)}, the contract expects {sorted(MIRRORED)}"
    )


@pytest.mark.parametrize("array_name", sorted(MIRRORED))
def test_values_and_order_match_the_python_enum(
    array_name: str, parsed: dict[str, list[str]]
) -> None:
    """Same values, same order.

    Order as well as membership, because these arrays populate selects: reordering one
    side silently reorders a picker, and keeping them identical costs nothing.
    """
    assert parsed[array_name] == [member.value for member in MIRRORED[array_name]]


def test_the_parser_would_notice_a_wrong_value() -> None:
    """Positive control. A detector that cannot see its own violation is worse than none."""
    source = "export const PHASES = ['base', 'strenth', 'power'] as const;"
    assert _parse(source) == {"PHASES": ["base", "strenth", "power"]}
    assert _parse(source)["PHASES"] != [member.value for member in Phase]


def test_the_parser_would_notice_a_missing_array() -> None:
    """The other control: a file with nothing in it must not read as agreement."""
    assert _parse("// nothing here") == {}


# ---------------------------------------------------------------------------------
# The migration's copy — the one that decides what the DATABASE will accept
# ---------------------------------------------------------------------------------
#
# ⚠️ **`alembic check` is blind to this, and `0004`'s docstring used to claim otherwise.**
# A SQLAlchemy `ENUM` compiles to its type *name*, so `compare_type=True` compares
# `activity_kind` against `activity_kind` and never looks inside. Delete `taper` from the
# migration's `phase` list and `alembic upgrade`, `alembic check` and every other test in
# this repo stay green — then the first plan that needs a taper mesocycle dies at runtime
# on `invalid input value for enum phase`.
#
# Note the asymmetry that made this worth writing: the same vocabulary is duplicated twice,
# and the copy pointing at TypeScript was guarded from day one while the copy that decides
# what Postgres will accept was not.
#
# The duplication itself stays. A migration that imported `server.domain.vocabulary` would
# be un-pinned from history — `0004` would start creating whatever the enum says *today*
# rather than what it said when it was written, which is the one thing a migration must
# never do. So: duplicate the values, test the duplication.

_MIGRATION = ROOT / "migrations" / "versions" / "0004_domain_schema.py"

# Migration module attribute -> the Python enum it must match. `discipline` is included
# even though 0001 created the type: 0004 re-declares its value list to pass it to
# `op.create_table`, so it is a third copy and can be wrong in the same way.
MIGRATION_ENUMS = {
    "discipline": Discipline,
    "activity_kind": ActivityKind,
    "ascent_style": AscentStyle,
    "protocol_kind": ProtocolKind,
    "phase": Phase,
    "session_status": SessionStatus,
}


def _load_migration() -> ModuleType:
    """Import `0004` by path — its module name starts with a digit, so no import works.

    Executing it is safe and cheap: the module body only declares revision identifiers and
    `postgresql.ENUM` objects. Nothing connects, and `upgrade()` is not called.
    """
    spec = importlib.util.spec_from_file_location("migration_0004_under_test", _MIGRATION)
    assert spec is not None and spec.loader is not None, f"cannot load {_MIGRATION}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared_values(module: ModuleType, name: str) -> list[str]:
    """The value list of one `postgresql.ENUM` declared in the migration."""
    declared = getattr(module, name, None)
    assert isinstance(declared, ENUM), f"{name} is not a postgresql.ENUM in {_MIGRATION.name}"
    return list(declared.enums)


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    return _load_migration()


def test_the_migration_declares_every_enum(migration: ModuleType) -> None:
    """Non-vacuity: a renamed or deleted declaration must fail, not skip a case."""
    missing = [
        name for name in MIGRATION_ENUMS if not isinstance(getattr(migration, name, None), ENUM)
    ]
    assert not missing, f"{_MIGRATION.name} declares no postgresql.ENUM named {missing}"


@pytest.mark.parametrize("enum_name", sorted(MIGRATION_ENUMS))
def test_migration_enum_values_and_order_match_the_python_enum(
    enum_name: str, migration: ModuleType
) -> None:
    """Same values, same order, because Postgres orders enum labels by declaration.

    Order matters here in a way it does not in TypeScript: `ORDER BY phase` uses the type's
    declaration order, so reordering the migration's list silently reorders every query
    that sorts by one of these columns.
    """
    assert _declared_values(migration, enum_name) == [
        member.value for member in MIGRATION_ENUMS[enum_name]
    ]


def test_the_comparison_would_notice_a_dropped_enum_value() -> None:
    """Positive control — the exact defect the reviewer demonstrated on `phase`/`taper`."""
    crippled = ENUM(*[m.value for m in Phase if m is not Phase.TAPER], name="phase")
    assert list(crippled.enums) != [member.value for member in Phase]
    assert "taper" not in crippled.enums


def test_the_comparison_would_notice_a_reordered_enum_value() -> None:
    """And ordering, which a set comparison would have missed."""
    values = [member.value for member in Phase]
    reordered = ENUM(*reversed(values), name="phase")
    assert set(reordered.enums) == set(values)
    assert list(reordered.enums) != values
