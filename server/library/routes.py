"""`GET /api/library` — the seeded exercise library, whole, in one request.

Four statements, no lazy loading: the exercises, their equipment requirements, their
contraindications and their per-phase prescriptions are each selected once and stitched
together in Python by `exercise_id`. Walking `Exercise.equipment` through relationships
would be an N+1 over the whole library, and every extra round trip is Neon awake time
(CLAUDE.md, "Neon bills AWAKE TIME").

## One endpoint, not list + detail — and this is the read-shape decision

A browse screen needs the aspect, the name and the requirements; a detail screen adds the
instructions, the substitution hint and the prescriptions. That is the classic case for a
list endpoint plus `GET /api/library/{key}`, and it is the wrong trade here:

- **The whole library is ~90 KB of JSON for today's 85 exercises** (measured over the
  authored content in the response shape). It is reference content,
  identical for every user and changed only by a seed run, so the client fetches it once
  and keeps it — exactly like `GET /api/vocabulary`.
- **A detail endpoint would cost a database round trip per exercise browsed**, against a
  free-tier Postgres whose scarce resource is awake time, to save a payload smaller than
  one photograph on the landing page.
- Splitting it would also mean two cache entries with two lifetimes for one seed run.

If the library ever grows past a few hundred exercises (media, per-move breakdowns), the
split becomes right; the number to watch is payload size, not the endpoint count.

## Aspect grouping arrives as ORDER, not as nesting

The array is ordered by `climbing_aspect.sort_order`, then by name, so a UI grouping by
`climbing_aspect_id` walks it once and gets the aspects in the same order every picker in
the app already uses. Same reason the lookup tables in `GET /api/vocabulary` are arrays in
`sort_order` rather than maps: a nested `{aspect: [...]}` object would carry the grouping
in JSON key order, which nothing guarantees.

**Names come from `GET /api/vocabulary`, not from here.** Equipment, injury areas and the
aspects themselves are sent as **ids**, and the client joins them against the vocabulary
payload it already holds. Duplicating the display text would give the app two copies of
every equipment name and one of them would eventually be the stale one.

## Everything here is untrusted on OUTPUT

`instructions`, `substitution_hint` and every name are authored content rather than user
input, but the output rule does not depend on the source: they are **JSON, never HTML**,
and the client renders them as React children with no `dangerouslySetInnerHTML` (CLAUDE.md,
"Notes are untrusted on OUTPUT too"). `media_url` is sent for completeness and is NULL
across today's library; a client must treat it as a URL to validate, not to interpolate.

## Caching: `public, s-maxage=31536000, immutable`, on a SHARED CDN

Kilian's choice, and it is the design CLAUDE.md's compute-budget section already
prescribed. The arithmetic behind it: Neon Free is **100 CU-hr/month = ~400 awake hours**,
and **autosuspend is fixed at 5 minutes** — so *any* origin read costs a five-minute
window, whatever it reads. `POST /api/auth/demo` was deliberately made zero-SQL so a
portfolio visitor costs no Neon time at all, and an uncached library read is the first
thing that would undo that. Served from the CDN, the whole library costs one origin read
per deploy and then nothing.

**`?v=<buildId>` is what makes a year-long `immutable` safe.** The URL changes on every
deploy (`web/src/buildId.ts`), so a content edit ships a new URL rather than waiting out a
cache. The parameter is accepted and **ignored**: the response must not depend on it, or
the cache would hold as many different bodies as there have been builds.

**It stays AUTHENTICATED, and that is not theatre now that the body is publicly
cacheable.** Auth gates who can cause a **cache MISS**, and a cache miss is an origin read
and therefore a Neon wake. An unauthenticated endpoint would let a bot wake the database at
will — the same exposure the demo endpoint was rewritten to close. It is deliberately not
in `PUBLIC_ROUTES`.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Annotated, Final

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel
from sqlalchemy import Row, select

from server.auth.deps import RequestSession
from server.domain.grades import Discipline
from server.domain.vocabulary import Phase, ProtocolKind
from server.models import (
    ClimbingAspect,
    Equipment,
    Exercise,
    ExerciseContraindication,
    ExerciseEquipment,
    InjuryArea,
    PrescriptionTemplate,
)

router = APIRouter(prefix="/api/library", tags=["library"])

# One year and immutable, keyed on `?v=<buildId>`. See the module docstring for the
# awake-time arithmetic that chose it.
#
# ⚠️⚠️ **THE RULE, and it is a SECURITY rule, not a caching preference.**
#
# `/api/library` is user-independent, permanently. It is served from a shared CDN keyed on
# URL alone with no `Vary: Authorization`, so any per-user field would be served from one
# user's cache to another and **no test would catch it**. Per-user state about exercises
# (the "I don't have this gear" flag, personal bests, anything derived from a `user_*`
# table) goes on a SEPARATE endpoint that is never CDN-cached.
#
# **Adding a user-scoped field to this response is a security change, not a feature
# change.** This is concrete, not hypothetical: **PR #11's equipment flag is exactly the
# field that would spring the trap** — whether `user_equipment` becomes a record of what is
# LACKED is still open (it waits on the alternatives lookup), and wherever that lands, it does
# not land here. `tests/test_library_contract.py` pins the field list and this header so that
# adding one is a red test and a visible diff.
_CACHE_CONTROL: Final = "public, s-maxage=31536000, immutable"

# `?v=` is a cache-buster and nothing else: accepted, documented in the schema so the
# client's URL is a typed contract, and never read. Bounded because every distinct value is
# a distinct CDN cache key — auth is what actually stops a flood, but an unbounded string in
# a cache key is not a thing to leave open (CLAUDE.md, "Prefer CLOSED inputs").
_BUILD_ID_MAX: Final = 64


class PrescriptionOut(BaseModel):
    """The default prescription for one exercise in one phase.

    `reps` and `work_seconds` are independent and both nullable — a repeater has seconds
    and no reps, a pull-up set has reps and no seconds, and a circuit legitimately has
    neither. `intensity_pct` has no anchor field: what the percentage is *of* follows from
    the exercise's `protocol_kind` (see `PrescriptionTemplate` in `server/models.py`).
    """

    phase: Phase
    sets: int
    reps: int | None
    work_seconds: int | None
    rest_seconds: int | None
    rest_between_sets_seconds: int | None
    intensity_pct: int | None
    target_rpe: int | None


class ExerciseOut(BaseModel):
    """One library exercise, with everything a browse + detail UI needs.

    `key` is the data contract and the rest is display or generator input, the same split
    as `ReferenceSpec`. `equipment_ids` is an **AND set**: every id is a requirement, so
    an empty list means the exercise needs nothing and is always prescribable — which is
    what replaces the `bodyweight` equipment row that deliberately does not exist.

    `discipline` is NULL for most of the library (a hangboard protocol serves boulderers
    and rope climbers alike). `substitution_hint` is NULL for every finger-loading
    protocol on purpose — see `server/domain/exercises.py` for the safety boundary.
    """

    id: int
    key: str
    name: str
    climbing_aspect_id: int
    protocol_kind: ProtocolKind
    discipline: Discipline | None
    instructions: str
    substitution_hint: str | None
    media_url: str | None
    # These cannot dangle into a retired exercise: `_upsert_exercises` nulls both columns
    # on every run and `_link_progressions` only resolves keys the content authors, so a
    # served row never points at one the content dropped.
    progression_of_id: int | None
    regression_of_id: int | None
    equipment_ids: list[int]
    contraindicated_injury_area_ids: list[int]
    prescriptions: list[PrescriptionOut]


class ExerciseLibraryResponse(BaseModel):
    """The whole library. An object rather than a bare array, so the payload can grow a
    sibling field (a content revision, say) without breaking every client."""

    exercises: list[ExerciseOut]


def _grouped_by_exercise(rows: Sequence[Row[tuple[int, int]]]) -> dict[int, list[int]]:
    """`(exercise_id, other_id)` pairs, grouped, preserving the query's order.

    The two callers order by the referenced table's `sort_order`, so a UI renders
    "hangboard, weight belt" the way the equipment picker does. Without the ORDER BY the
    list would arrive in physical row order, which is insert order.
    """
    grouped: dict[int, list[int]] = defaultdict(list)
    for exercise_id, other_id in rows:
        grouped[exercise_id].append(other_id)
    return grouped


@router.get("")
def read_library(
    response: Response,
    session: RequestSession,
    v: Annotated[str | None, Query(max_length=_BUILD_ID_MAX)] = None,
) -> ExerciseLibraryResponse:
    """The library, ordered by aspect. Authenticated like every other route.

    User-independent: nothing here is scoped by `user_id` because nothing here belongs to
    a user, and per the rule at `_CACHE_CONTROL` nothing here ever will. Read-only — the
    library is written by `server/contentseed.py`, out of band.

    `v` is **declared and deliberately unused**. It exists so the client can put a build id
    in the URL and so the schema documents it; reading it here — even to log it — is the
    one change that would make the CDN's single cache entry wrong.
    """
    del v  # the cache key is the whole job; see the docstring
    response.headers["cache-control"] = _CACHE_CONTROL

    # The join to the referenced lookup table is what the ORDER BY needs; without it
    # SQLAlchemy would add the table to the FROM clause and cross-join it.
    #
    # These three are deliberately NOT filtered on `retired_at`: they are keyed lookups
    # stitched by `exercise_id`, and an entry for an exercise the final query left out is
    # never read. Adding the join to filter them would buy a few unread rows off the wire
    # and cost a third join on the hot path.
    equipment_ids = _grouped_by_exercise(
        session.execute(
            select(ExerciseEquipment.exercise_id, ExerciseEquipment.equipment_id)
            .join(Equipment, Equipment.id == ExerciseEquipment.equipment_id)
            .order_by(Equipment.sort_order)
        ).all()
    )
    injury_ids = _grouped_by_exercise(
        session.execute(
            select(
                ExerciseContraindication.exercise_id,
                ExerciseContraindication.injury_area_id,
            )
            .join(InjuryArea, InjuryArea.id == ExerciseContraindication.injury_area_id)
            .order_by(InjuryArea.sort_order)
        ).all()
    )

    prescriptions: dict[int, list[PrescriptionOut]] = defaultdict(list)
    # `ORDER BY phase` on a native enum column is Postgres's own declaration order, which
    # is the order `Phase` declares and the order a timeline should present.
    for row in session.execute(
        select(
            PrescriptionTemplate.exercise_id,
            PrescriptionTemplate.phase,
            PrescriptionTemplate.sets,
            PrescriptionTemplate.reps,
            PrescriptionTemplate.work_seconds,
            PrescriptionTemplate.rest_seconds,
            PrescriptionTemplate.rest_between_sets_seconds,
            PrescriptionTemplate.intensity_pct,
            PrescriptionTemplate.target_rpe,
        ).order_by(PrescriptionTemplate.exercise_id, PrescriptionTemplate.phase)
    ).all():
        prescriptions[row.exercise_id].append(
            PrescriptionOut(
                phase=row.phase,
                sets=row.sets,
                reps=row.reps,
                work_seconds=row.work_seconds,
                rest_seconds=row.rest_seconds,
                rest_between_sets_seconds=row.rest_between_sets_seconds,
                intensity_pct=row.intensity_pct,
                target_rpe=row.target_rpe,
            )
        )

    # ⚠️ `climbing_aspect.sort_order`, never `climbing_aspect_id`: a serial follows INSERT
    # order, so ordering by it is declaration order only on a FRESH database. Same trap
    # `GET /api/vocabulary` paid for in revision `0006`.
    exercises = session.execute(
        select(
            Exercise.id,
            Exercise.key,
            Exercise.name,
            Exercise.climbing_aspect_id,
            Exercise.protocol_kind,
            Exercise.discipline,
            Exercise.instructions,
            Exercise.substitution_hint,
            Exercise.media_url,
            Exercise.progression_of_id,
            Exercise.regression_of_id,
        )
        .join(ClimbingAspect, ClimbingAspect.id == Exercise.climbing_aspect_id)
        # ⚠️ Retired exercises are NOT served and are therefore not prescribable. A row
        # only ever gets `retired_at` because a plan or a logged set points at it and
        # Postgres refused the delete (`server/contentseed.py`); it exists so old history
        # resolves, not so the library keeps offering it. `retired_at` itself stays OUT of
        # the payload — the CDN rule above forbids growing this response by habit, and the
        # client has no use for a date it must never render.
        .where(Exercise.retired_at.is_(None))
        .order_by(ClimbingAspect.sort_order, Exercise.name)
    ).all()

    return ExerciseLibraryResponse(
        exercises=[
            ExerciseOut(
                id=row.id,
                key=row.key,
                name=row.name,
                climbing_aspect_id=row.climbing_aspect_id,
                protocol_kind=row.protocol_kind,
                discipline=row.discipline,
                instructions=row.instructions,
                substitution_hint=row.substitution_hint,
                media_url=row.media_url,
                progression_of_id=row.progression_of_id,
                regression_of_id=row.regression_of_id,
                equipment_ids=equipment_ids.get(row.id, []),
                contraindicated_injury_area_ids=injury_ids.get(row.id, []),
                prescriptions=prescriptions.get(row.id, []),
            )
            for row in exercises
        ]
    )
