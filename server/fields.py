"""Bounded Pydantic field types — one definition per bound, wherever the bound comes from.

Most of these mirror something the database also enforces, and where it does, the bound
exists twice by necessity: as a `CHECK` (or a column length) in `migrations/` and as a
`Field(...)` on the request model. Some mirror no `CHECK` at all — `LookupId` is a sanity
floor on an id that is verified by looking it up, `InjuryNote` mirrors a column length, and
`SETS_PER_REQUEST_MAX` bounds a request body rather than a column. The unifying rule is one
definition per bound, not one per `CHECK`.

Where there is a database-side half, the two are not interchangeable and CLAUDE.md asks
for both. The `CHECK` is the last line of defence; the Pydantic bound is what turns a bad
payload into a **422 at the edge**, before a query runs:

- a named `CHECK` violation is an `IntegrityError` in the middle of a handler, which
  reads as a server fault and, on the outbox path, is a payload that **retries forever
  and can never succeed**;
- a 422 says which field was wrong, costs no database time, and the client can fix it.

⚠️ **`ActualReps`, `WorkSeconds` and `LoadKg` have no database half above zero.** Their
columns' `CHECK`s are `>= 0` only, and an over-large value overflows `SMALLINT` or
`Numeric(5, 2)` into a `DataError`, which carries no constraint name for a handler to map.
For those three, the bounds here are the only guard that exists.
"""

from decimal import Decimal
from typing import Annotated, Final

from pydantic import Field, StringConstraints

from server.models import DISPLAY_NAME_MAX, LOCATION_MAX, NOTES_MAX, SET_NOTE_MAX

# `activity.duration_minutes`: 24 hours. A payload in seconds is the unit error this
# catches — 3600 for a one-hour session is a 422 here rather than a retry loop.
DURATION_MINUTES_MAX: Final = 1440

# How many sets one flush may carry. The generator's own ceiling is 3 blocks x 10 sets = 30,
# so this is 4x that: the bound guards resource exhaustion, it does not model the domain.
SETS_PER_REQUEST_MAX: Final = 120

DurationMinutes = Annotated[int, Field(ge=1, le=DURATION_MINUTES_MAX)]
"""Minutes of an activity. `ge=1`: a zero-minute activity is not an activity."""

Rpe = Annotated[int, Field(ge=1, le=10)]
"""`activity.rpe` and `logged_set.rpe` — `CHECK (BETWEEN 1 AND 10)` on both columns.

One type for both: Borg CR10 is the same scale for a single set as for a whole session.
"""

SetIndex = Annotated[int, Field(ge=1, le=SETS_PER_REQUEST_MAX)]
"""`logged_set.set_index` — `CHECK (>= 1)`, and chronological across the whole session.

The upper bound is `SETS_PER_REQUEST_MAX` rather than a column bound: an index above it
names a set that no legal request could have carried.
"""

ActualReps = Annotated[int, Field(ge=0, le=500)]
"""`logged_set.actual_reps`. `ge=0` is deliberate — a failed set is zero reps, not no set.

The upper bound has no database half; see the module docstring.
"""

WorkSeconds = Annotated[int, Field(ge=0, le=3600)]
"""`logged_set.actual_work_seconds` — an hour of work in ONE set is already implausible.

The upper bound has no database half; see the module docstring.
"""

LoadKg = Annotated[Decimal, Field(ge=-500, le=500)]
"""`logged_set.actual_load_kg` — **added** load, and legitimately NEGATIVE.

Assisted hangboarding (pulley or band) is negative added load, and the column has no
`CHECK` at all, so a 4xx here would be permanent data loss. No `decimal_places`: Postgres
rounds a scale reading of `70.333` into `Numeric(5, 2)` losslessly, whereas Pydantic would
refuse it outright and turn a real measurement into a 422 that can never succeed.
"""

BodyWeightKg = Annotated[Decimal, Field(ge=20, le=300)]
"""`logged_set.body_weight_kg` — `CHECK (BETWEEN 20 AND 300)`.

No `decimal_places`, for the reason given on `LoadKg`.
"""

SessionsPerWeek = Annotated[int, Field(ge=1, le=7)]
"""`user_profile.sessions_per_week` — `CHECK (BETWEEN 1 AND 7)`.

The column is NULLABLE (revision `0005`) and NULL means "not answered". There is no
in-range value for that, which is exactly why the column had to become nullable.
"""

AvailableWeekdays = Annotated[int, Field(ge=0, le=127)]
"""`user_profile.available_weekdays` — a 7-bit mask, Monday = bit 0.

`0` is inside the range on purpose and **is reachable through the API**: it is a legal
mask meaning "answered, no days". "Not answered" is NULL, which is a different thing (see
`0005`). The web client's submit gate happens not to send 0, but that is a client
decision, not a property of this endpoint.
"""

AspectScore = Annotated[int, Field(ge=1, le=5)]
"""`user_aspect_rating.score` — `CHECK (BETWEEN 1 AND 5)`."""

LookupId = Annotated[int, Field(ge=1)]
"""A row id in a seeded lookup table.

The bound is only a sanity floor — an id that does not exist is rejected by looking it
up, never by trusting its shape. Client-supplied ids are resolved against the reference
table before anything is written.
"""

InjuryNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SET_NOTE_MAX)
]
"""`user_injury.note` — free text, and one of the ten fields on CLAUDE.md's inventory.

Bounded because an unbounded text column is a storage-exhaustion vector against a 0.5 GB
database. `min_length=1` after stripping, so an empty box is `null` rather than `''`:
two representations of "nothing said" is a distinction no query wants to remember.
"""

SetNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SET_NOTE_MAX)
]
"""`logged_set.note` — free text on CLAUDE.md's inventory, mirroring `String(SET_NOTE_MAX)`.

`min_length=1` after stripping, so an empty box is `null` rather than `''`.
"""

SessionNotes = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTES_MAX)
]
"""`logged_session.notes` — free text on CLAUDE.md's inventory, mirroring `String(NOTES_MAX)`.

`min_length=1` after stripping, so an empty box is `null` rather than `''`.
"""

SessionLocation = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LOCATION_MAX)
]
"""`logged_session.location` — the gym or crag name, and the free-text field readers forget.

`min_length=1` after stripping, so an empty box is `null` rather than `''`.
"""

DisplayName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=DISPLAY_NAME_MAX)
]
"""`user_profile.display_name` — free text, and the eleventh field on CLAUDE.md's inventory.

Bounded because an unbounded text column is a storage-exhaustion vector against a 0.5 GB
database, and mirrored by the column's own `String(DISPLAY_NAME_MAX)`.

`min_length=1` after stripping, so `""` and `"   "` are a 422 rather than a stored empty
string: two representations of "no name" is a distinction no query wants to remember.
⚠️ That also means **PATCH cannot clear a display name** — `null` means "no change" on this
endpoint, and an empty string is refused. Clearing one needs `POST /api/profile/reset` or a
future explicit affordance; it is not reachable by accident, which is the intended trade.
"""
