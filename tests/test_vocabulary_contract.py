"""The closed vocabularies are written down THREE times. Here are the two guards.

`server/domain/vocabulary.py` is the source of truth. It is duplicated into
`web/src/api/schema.ts` (now GENERATED from the OpenAPI schema — see below) and into
`migrations/versions/0004_domain_schema.py` (because a migration must not import live
application code, or it stops describing history). Neither duplicate is checked by
anything else: `tsc` cannot see Python, and `alembic check` cannot see inside an enum
type. So both are checked here.

## Part 1 — the TypeScript copy, since PR #9 the GENERATED one

`web/src/api/vocabularies.ts` used to mirror these lists by hand, because OpenAPI codegen
had no endpoints to generate from. `GET /api/vocabulary` is those endpoints, so the file
is gone and `web/src/api/schema.ts` — written by `npm run codegen:api` — took its place.

**The guarantee is unchanged and is deliberately not weakened: the Python enums still
have to match what the client sees.** What changed is which file is read. Two things had
to be true before the hand-written mirror could be retired, and both are:

1. **Every enum has to appear in the schema.** Five of the six are not referenced by any
   profile field, so `GET /api/vocabulary` returns them explicitly (its `enums` object) —
   without that, retiring the mirror would have silently dropped five of these
   assertions rather than re-pointing them.
2. **The generated file has to be provably current AND unedited.** A stale `schema.ts`
   agreeing with Python proves nothing about the running API, so the header carries two
   digests and both are checked here: `openapi-sha256` (the document it was generated
   from, recomputed from the live app) and `types-sha256` (everything below the header,
   recomputed from the file). The first catches "I added an endpoint and forgot to
   regenerate"; the second catches a hand-edit, which the first cannot — changing
   `sessions_per_week: number` to `number | null` in the committed file left the digest,
   `tsc` and the whole gate green while the client believed a nullability the API does not
   have. Both run in the local gate, with no Node and no network.

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

DB-free, all of them, so they run in the local gate.
"""

import hashlib
import importlib.util
import json
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
from server.openapi_schema import canonical_json, fingerprint
from server.settings import ROOT

SCHEMA_TS = ROOT / "web" / "src" / "api" / "schema.ts"

# OpenAPI component name -> the Python enum it is generated from. The component name is
# the Pydantic/Python class name, so these are the same string on both sides; the mapping
# exists to state the pairing explicitly and to be iterated.
MIRRORED = {
    "Discipline": Discipline,
    "ActivityKind": ActivityKind,
    "AscentStyle": AscentStyle,
    "ProtocolKind": ProtocolKind,
    "Phase": Phase,
    "SessionStatus": SessionStatus,
}

# `openapi-typescript` emits an enum as a property whose type is a union of string
# literals, wrapped across lines by Prettier when it is long:
#
#     ActivityKind: 'climbing' | 'cardio' | 'strength' | 'mobility' | 'other';
#     Phase:
#       | 'base'
#       | 'strength'
#       ...
#
# `[^;]*` therefore spans the wrap, and stops at the terminating semicolon. Pointed at an
# OBJECT schema by mistake it captures a fragment rather than a union, which fails the
# comparison loudly instead of matching a subset — see the third positive control.
_UNION = r"^\s+{name}:\s*(?P<union>[^;]*);"
# Single quotes: the generator emits double, and `npm run codegen:api` formats its output
# with this repo's Prettier config (`singleQuote: true`) before writing the file.
_VALUE = re.compile(r"'([^']*)'")

# The two digests in the generated header, both written by
# `web/scripts/gen-api-types.mjs`: one over the exact bytes `server/openapi_schema.py`
# printed, one over the generated body it was about to write.
_FINGERPRINT = re.compile(r"^ \* openapi-sha256: ([0-9a-f]{64})$", re.MULTILINE)
_TYPES_DIGEST = re.compile(r"^ \* types-sha256: ([0-9a-f]{64})$", re.MULTILINE)

# The generator writes `header + body`, and the header is one block comment, so the FIRST
# `*/` followed by a blank line ends it. The body contains `*/` of its own (every schema
# gets a JSDoc block), hence the split limit.
_HEADER_END = "*/\n\n"


def _generated_body(source: str) -> str:
    """Everything `types-sha256` is taken over: the file below its own header."""
    header, _, body = source.partition(_HEADER_END)
    assert body, f"{SCHEMA_TS.name} has no generated body after its header comment"
    assert "openapi-sha256" in header, "the digests must live in the header, not the body"
    return body


def _union_values(source: str, name: str) -> list[str] | None:
    """The string literals of one generated union, in order. `None` if it is absent."""
    match = re.search(_UNION.format(name=re.escape(name)), source, re.MULTILINE)
    return None if match is None else _VALUE.findall(match.group("union"))


@pytest.fixture(scope="module")
def generated() -> str:
    assert SCHEMA_TS.is_file(), (
        f"{SCHEMA_TS} is missing. It is generated and COMMITTED — run "
        f"`npm run codegen:api` from the repo root."
    )
    return SCHEMA_TS.read_text(encoding="utf-8")


def test_the_generated_types_were_built_from_this_api(generated: str) -> None:
    """The freshness check: the committed types describe the API as it is *now*.

    Everything else in Part 1 compares two things this repository controls, so all of it
    would keep passing against a `schema.ts` generated months ago. This is the assertion
    that makes those meaningful — and it is the quality gate's codegen check, which is
    why it lives in `pytest` rather than in a CI step needing both toolchains.

    It proves the input, not the output: a different `openapi-typescript` version would
    emit different TypeScript from the same document and the digest would still match.
    """
    declared = _FINGERPRINT.search(generated)
    assert declared is not None, (
        f"{SCHEMA_TS.name} carries no `openapi-sha256:` header line. It is written by "
        f"web/scripts/gen-api-types.mjs; do not hand-edit the file."
    )
    assert declared.group(1) == fingerprint(), (
        "the committed API types were generated from a DIFFERENT OpenAPI document than "
        "this application produces. Run `npm run codegen:api` from the repo root and "
        "commit the result. (A FastAPI or Pydantic upgrade also lands here: it changes "
        "the document this application produces, and only a regeneration fixes it.)"
    )


def test_the_generated_types_have_not_been_hand_EDITED(generated: str) -> None:
    """The other half: the file's body is the one the generator wrote.

    The digest above is over the generator's INPUT, so it says nothing about the file it
    produced — a one-word edit to a type inside `schema.ts` left it, `tsc`, `eslint` and
    every test green while the client believed a nullability the API does not have. "Do
    not edit this file" was a comment; this is the check.

    It is tamper-EVIDENT, not tamper-proof: an editor who also recomputes the digest gets
    through, exactly as with the committed route tree. What it catches is the realistic
    case — someone fixing a type by hand instead of fixing the server.
    """
    declared = _TYPES_DIGEST.search(generated)
    assert declared is not None, (
        f"{SCHEMA_TS.name} carries no `types-sha256:` header line. Regenerate it with "
        f"`npm run codegen:api`."
    )
    actual = hashlib.sha256(_generated_body(generated).encode("utf-8")).hexdigest()
    assert declared.group(1) == actual, (
        f"{SCHEMA_TS.name} does not match its own `types-sha256`, so it has been edited by "
        f"hand (or partially regenerated). It is GENERATED: change the Python models and "
        f"run `npm run codegen:api`."
    )


def test_every_enum_is_mirrored(generated: str) -> None:
    """Non-vacuity: a renamed or deleted component must fail loudly, not silently pass.

    Without this, dropping `Phase` from the schema — by removing the last field that
    references it — would make the parametrised test below collect one fewer case and
    stay green.
    """
    missing = [name for name in MIRRORED if _union_values(generated, name) is None]
    assert not missing, (
        f"{SCHEMA_TS.name} declares no union for {missing}. An enum reaches the generated "
        f"types only if some request or response model references it — see the `enums` "
        f"field of `GET /api/vocabulary`, which exists for exactly this reason."
    )


@pytest.mark.parametrize("component", sorted(MIRRORED))
def test_values_and_order_match_the_python_enum(component: str, generated: str) -> None:
    """Same values, same order.

    Order as well as membership, because these lists populate selects: reordering one
    side silently reorders a picker, and keeping them identical costs nothing.
    """
    assert _union_values(generated, component) == [member.value for member in MIRRORED[component]]


def test_the_parser_would_notice_a_wrong_value() -> None:
    """Positive control. A detector that cannot see its own violation is worse than none."""
    source = "    Phase: 'base' | 'strenth' | 'power';\n"
    assert _union_values(source, "Phase") == ["base", "strenth", "power"]
    assert _union_values(source, "Phase") != [member.value for member in Phase]


def test_the_parser_would_notice_a_missing_union() -> None:
    """The other control: a file with nothing in it must not read as agreement."""
    assert _union_values("// nothing here", "Phase") is None


def test_the_parser_does_not_mistake_an_object_schema_for_a_union() -> None:
    """A control for the failure mode `[^;]*` could plausibly have: a partial match.

    If `Phase` ever became an object, the capture must not happen to equal the enum's
    values — it must be visibly wrong.
    """
    source = "    Phase: {\n      /** Name */\n      name: 'base';\n    };\n"
    assert _union_values(source, "Phase") != [member.value for member in Phase]


def test_the_fingerprint_would_notice_a_changed_schema() -> None:
    """Positive control for the freshness check: the digest has to move when the API does."""
    document = json.loads(canonical_json())
    document["paths"]["/api/invented"] = {"get": {"responses": {}}}
    mutated = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert mutated != fingerprint()


def test_the_body_digest_would_notice_a_one_WORD_hand_edit(generated: str) -> None:
    """Positive control for the hand-edit check, using the exact edit review demonstrated.

    Asserted on the real file so the control cannot drift from what the test does: flip one
    type in the body, leave the header alone, and the digest must move.
    """
    body = _generated_body(generated)
    edited = body.replace("sessions_per_week: number | null;", "sessions_per_week: number;", 1)
    assert edited != body, "the sample edit no longer applies — point this at a real line"
    assert (
        hashlib.sha256(edited.encode("utf-8")).hexdigest()
        != hashlib.sha256(body.encode("utf-8")).hexdigest()
    )


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
