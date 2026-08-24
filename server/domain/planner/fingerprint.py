"""The reproducibility key: `library_digest()` over the library, `generator_input()` over a run.

## Why the generator needs this at all

`server/models.py::Plan` promises that re-running version X against the same input
reproduces the tree. **The library is a third input.** Without a digest that promise is
false the first time somebody rewords a prescription, and the failure is silent: same
version, same profile, different plan. With it, a content change reads as a *different
input*, which is exactly what it is.

## What "stable" has to mean

Stable **across processes**, not merely within one — `generator_input` is persisted and
compared later, and a Python run with a different `PYTHONHASHSEED` must produce the same
string. So: no `hash()`, no `id()`, no set iteration. The serialisation is JSON text with
sorted keys, hashed as UTF-8 bytes.

## Nothing is sorted, and that is the point

`EXERCISES` contains no sets at runtime — every field is a scalar or an authored tuple — so
there is no iteration-order nondeterminism to sort away. And the authored **order** of
`EXERCISES` and of each spec's `prescriptions` is itself content: selection walks the library
in authored order, so a reorder changes the generated plan and therefore must move the
digest. Sorting here would hide exactly the edit this exists to notice.

`sort_keys=True` is the one exception, and it is about field *names*: reordering the
attributes of `ExerciseSpec` changes no plan, so it should not move the digest.

## Not cached, deliberately

Recomputed per call — roughly a hundred small dicts, well under a millisecond, against an
endpoint that already does several `SELECT`s. `functools.cache` would also make the guard
test unable to substitute a library and watch the digest move, and a cache that defeats its
own test is a bad trade for microseconds.
"""

import enum
import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import date

from server.domain.exercises import EXERCISES
from server.domain.planner.contract import GENERATOR_VERSION, PlannerInput


def library_digest() -> str:
    """A hex sha256 of the whole library. Moves if any spec, or their order, changes."""
    payload = json.dumps(
        [_canonicalise(spec) for spec in EXERCISES],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generator_input(planner_input: PlannerInput) -> dict[str, object]:
    """Everything a rerun has to match, as the JSON-ready dict `plan.generator_input` stores.

    The `PlannerInput` verbatim, plus the two things that are inputs without being fields:
    the algorithm's version and the library's digest. `plan.generator_input` is `jsonb` and
    nothing queries inside it, so this is a dict rather than a string — canonical because
    every value is a scalar or a list of them, so `json.dumps(..., sort_keys=True)` of it is
    byte-stable in any interpreter.

    ⚠️ It is the input, not a summary of it: fields go through `dataclasses.fields()` so a
    new one on `PlannerInput` joins automatically. A hand-written list would leave the next
    field out, and the promise would quietly stop covering it.
    """
    return {
        "generator_version": GENERATOR_VERSION,
        "library_digest": library_digest(),
        **{
            field.name: _canonicalise(getattr(planner_input, field.name))
            for field in fields(planner_input)
        },
    }


def _canonicalise(value: object) -> object:
    """Dataclasses to dicts, tuples to lists, enums to their values, in declaration order.

    Generic rather than a hand-written field list on purpose: a new field on `ExerciseSpec`
    or `PrescriptionSpec` joins the digest automatically. A hand-written list would leave a
    new field out, which is the silent failure this whole module exists to prevent.

    The enum branch is explicit even though `StrEnum` members already serialise as strings,
    so that a future non-`str` enum in the library becomes its value rather than a
    `TypeError` — or, worse, a repr. The `date` branch is for `PlannerInput.start_date`;
    the library holds no dates, and ISO-8601 is the one date form that sorts as it reads.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonicalise(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple | list):
        return [_canonicalise(item) for item in value]
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value
