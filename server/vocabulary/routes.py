"""`GET /api/vocabulary` — grades, the seeded lookup tables, and the closed enums.

One request, five statements, no joins and no lazy loading: each table is selected once
and the client matches rows by id. The obvious alternative — walking
`GradeSystem.grades` through the relationship — is an N+1 over the four grade systems,
and every extra round trip is Neon awake time (CLAUDE.md, "Neon bills AWAKE TIME").

## Why the enums are in the payload

`enums` carries no database rows at all: it is the value list of each native Postgres
enum, straight from `server/domain/vocabulary.py`.

**Its justification is the TYPE CONTRACT, and it has no runtime consumer today — do not
claim one.** An earlier version of this docstring said the client needed these lists to
render its pickers. It does not: the pickers iterate `climbing_aspects`, `equipment` and
`injury_areas`, which are rows, and grepping `web/src` for `.enums` finds nothing outside a
test. What this field actually buys is that **every closed vocabulary reaches the OpenAPI
schema**, and therefore the generated TypeScript: five of the six are referenced by no
profile field, so without it `tests/test_vocabulary_contract.py` could only have been
re-pointed for one of them and retiring the hand-written `web/src/api/vocabularies.ts`
would have silently dropped the other five assertions. Six real cross-language assertions
for six short arrays and zero database time is a good trade; a fictional consumer is not a
reason.

It is also the obvious place for a future picker of an ascent style or a protocol kind to
read from (PR #10 onward), which is why it ships as data rather than as a comment.

## Caching: `private`, not `public, immutable`

The payload is user-independent and changes only when the seed does, i.e. per deploy —
which is CLAUDE.md's argument for serving `/api/library?v=<buildId>` as
`public, s-maxage=31536000, immutable`. Two differences here: there is no build id in the
URL, so an immutable year-long cache would pin a stale vocabulary for a year after a seed
edit; and this response requires a bearer token, so it has no business in a shared CDN
cache even though its body would be identical for everyone. `private` keeps it in the
one browser that asked, and an hour is long enough that a reload costs no database time.
"""

from typing import Final

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.auth.deps import RequestSession
from server.domain.grades import Discipline
from server.domain.vocabulary import (
    ActivityKind,
    AscentStyle,
    Phase,
    ProtocolKind,
    SessionStatus,
)
from server.models import ClimbingAspect, Equipment, Grade, GradeSystem, InjuryArea

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])

# One hour. Bounded staleness against a payload that only a deploy can change.
#
# ⚠️ **No `Vary: Authorization`, and that is only safe while this body is
# user-independent.** `private` keeps the response in the requesting browser's own cache,
# but that cache keys on the URL alone — so two accounts sharing a browser share the entry.
# Identical bytes for everyone is what makes that harmless today. **The moment any field
# here becomes user-scoped, this becomes a cross-account leak**: add `Vary: Authorization`
# in the same commit, or drop the caching. Nothing enforces this but the comment and
# `tests/test_vocabulary_api.py`, which pins the header so a change to it is deliberate.
_CACHE_CONTROL: Final = "private, max-age=3600"

# The three tables whose columns are `id, key, name, description, sort_order`. Named so
# `_reference_rows` can be written once instead of three times.
_ReferenceTable = type[ClimbingAspect] | type[Equipment] | type[InjuryArea]


class GradeSystemOut(BaseModel):
    """A grading scale. `discipline` is what makes the boulder/rope split selectable."""

    id: int
    key: str
    name: str
    discipline: Discipline


class GradeOut(BaseModel):
    """One rung of one scale.

    `ordinal` is the shared integer ladder and is sent so the client can sort and compare
    without a second request. It is display/ordering input only — **a client never sends
    an ordinal back**; a grade goes on the wire as its `id` (CLAUDE.md).
    """

    id: int
    grade_system_id: int
    label: str
    ordinal: int


class ReferenceRowOut(BaseModel):
    """A seeded lookup row: the stable `key` plus the display text.

    `key` is the data contract and `name`/`description` are display only — the same
    split as `server.domain.vocabulary.ReferenceSpec`. `sort_order` is not sent: the
    arrays below are already returned in it.
    """

    id: int
    key: str
    name: str
    description: str


class ClosedVocabulariesOut(BaseModel):
    """The native Postgres enums, as their persisted **values** (never member names).

    Order is declaration order, which is also Postgres's `ORDER BY` order for these
    types and the order a picker should present them in.
    """

    disciplines: list[Discipline]
    activity_kinds: list[ActivityKind]
    ascent_styles: list[AscentStyle]
    protocol_kinds: list[ProtocolKind]
    phases: list[Phase]
    session_statuses: list[SessionStatus]


class VocabularyResponse(BaseModel):
    grade_systems: list[GradeSystemOut]
    grades: list[GradeOut]
    climbing_aspects: list[ReferenceRowOut]
    equipment: list[ReferenceRowOut]
    injury_areas: list[ReferenceRowOut]
    enums: ClosedVocabulariesOut


def _closed_vocabularies() -> ClosedVocabulariesOut:
    """Straight from the enum classes, so a new member cannot be forgotten here."""
    return ClosedVocabulariesOut(
        disciplines=list(Discipline),
        activity_kinds=list(ActivityKind),
        ascent_styles=list(AscentStyle),
        protocol_kinds=list(ProtocolKind),
        phases=list(Phase),
        session_statuses=list(SessionStatus),
    )


def _reference_rows(session: Session, table: _ReferenceTable) -> list[ReferenceRowOut]:
    """One lookup table, in `sort_order`. The three tables are column-identical."""
    rows = session.execute(
        select(table.id, table.key, table.name, table.description).order_by(table.sort_order)
    ).all()
    return [
        ReferenceRowOut(id=row.id, key=row.key, name=row.name, description=row.description)
        for row in rows
    ]


@router.get("")
def read_vocabulary(response: Response, session: RequestSession) -> VocabularyResponse:
    """Everything onboarding and the loggers need to render a closed input.

    Authenticated like every other route (deny-by-default), but user-independent: nothing
    here is scoped by `user_id` because nothing here belongs to a user.
    """
    response.headers["cache-control"] = _CACHE_CONTROL

    # ⚠️ `sort_order`, not `id` (issue #55, revision `0006`). A serial follows INSERT order,
    # so ordering by it is only declaration order on a FRESH database: add a system mid-tuple
    # and CI keeps passing while dev and production render the new one last. Every sibling
    # lookup table below already orders this way.
    grade_systems = session.execute(
        select(GradeSystem.id, GradeSystem.key, GradeSystem.name, GradeSystem.discipline).order_by(
            GradeSystem.sort_order
        )
    ).all()
    grades = session.execute(
        select(Grade.id, Grade.grade_system_id, Grade.label, Grade.ordinal).order_by(
            Grade.grade_system_id, Grade.ordinal
        )
    ).all()

    return VocabularyResponse(
        grade_systems=[
            GradeSystemOut(id=row.id, key=row.key, name=row.name, discipline=row.discipline)
            for row in grade_systems
        ],
        grades=[
            GradeOut(
                id=row.id,
                grade_system_id=row.grade_system_id,
                label=row.label,
                ordinal=row.ordinal,
            )
            for row in grades
        ],
        climbing_aspects=_reference_rows(session, ClimbingAspect),
        equipment=_reference_rows(session, Equipment),
        injury_areas=_reference_rows(session, InjuryArea),
        enums=_closed_vocabularies(),
    )
