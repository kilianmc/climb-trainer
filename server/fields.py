"""Bounded Pydantic field types — one definition per bound, wherever the bound comes from.

Most of these mirror something the database also enforces, and where it does, the bound
exists twice by necessity: as a `CHECK` (or a column length) in `migrations/` and as a
`Field(...)` on the request model. Two do not mirror a `CHECK` at all — `LookupId` is a
sanity floor on an id that is verified by looking it up, and `InjuryNote` mirrors a
`String(500)` column length rather than a constraint. The unifying rule is one definition
per bound, not one per `CHECK`.

Where there is a database-side half, the two are not interchangeable and CLAUDE.md asks
for both. The `CHECK` is the last line of defence; the Pydantic bound is what turns a bad
payload into a **422 at the edge**, before a query runs:

- a named `CHECK` violation is an `IntegrityError` in the middle of a handler, which
  reads as a server fault and, on the outbox path, is a payload that **retries forever
  and can never succeed**;
- a 422 says which field was wrong, costs no database time, and the client can fix it.

Declared centrally rather than inline so that the two request models that will accept
`duration_minutes` (a logged activity, PR #10) cannot disagree with each other.

## `DurationMinutes` has no consumer in this PR, deliberately

`activity.duration_minutes` is `CHECK (BETWEEN 1 AND 1440)` because `srpe_load` is
`rpe::integer * duration_minutes` and a seconds-instead-of-minutes payload overflows
`SMALLINT` *before* it widens into the `INTEGER` column — see `Activity` in
`server/models.py`. PR #9 owes the matching Pydantic bound (CLAUDE.md, "The domain
schema"), and the honest way to pay a debt whose first caller has not been written yet is
to declare the type now, with the reason attached, and test the bound. PR #10 imports it
instead of re-deriving 1440 from memory.
"""

from typing import Annotated, Final

from pydantic import Field, StringConstraints

from server.models import DISPLAY_NAME_MAX, SET_NOTE_MAX

# `activity.duration_minutes`: 24 hours. A payload in seconds is the unit error this
# catches — 3600 for a one-hour session is a 422 here rather than a retry loop.
DURATION_MINUTES_MAX: Final = 1440

DurationMinutes = Annotated[int, Field(ge=1, le=DURATION_MINUTES_MAX)]
"""Minutes of an activity. `ge=1`: a zero-minute activity is not an activity."""

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
