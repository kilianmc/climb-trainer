"""`PUT /api/sessions/{client_uuid}` — session logging, one idempotent route for all of it.

Start, every mid-run flush and Finish share one shape, because CLAUDE.md's Tier-1 rule has a
mid-run action piggyback the pending outbox in the same request — one contract means there is
no second request to forget to attach the outbox to.

**`sets` is a DELTA.** The PUT replaces the addressed activity's identity and merges field
values; a set absent from the payload is left alone, because a piggyback carries only the
unsent tail. ⚠️ **4xx here is PERMANENT: quarantine the flush, never retry it.** 5xx retries.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Final, Literal, NamedTuple
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Integer, Select, case, cast, func, literal, null, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DatabaseError, DataError, IntegrityError
from sqlalchemy.orm import Session

from server.auth.deps import CurrentUser, RequestSession
from server.domain.grades import Discipline
from server.domain.vocabulary import ActivityKind, SessionStatus
from server.fields import (
    SETS_PER_REQUEST_MAX,
    ActualReps,
    BodyWeightKg,
    DurationMinutes,
    LoadKg,
    LookupId,
    Rpe,
    SessionLocation,
    SessionNotes,
    SetIndex,
    SetNote,
    WorkSeconds,
)
from server.models import (
    Activity,
    LoggedSession,
    LoggedSet,
    Microcycle,
    Plan,
    PlannedSession,
    PrescribedSet,
    SessionBlock,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# The same argument as `server/plans/routes.py`: this body is one climber's training, so a
# shared-cache entry would hand a stranger their log. `private` forbids the CDN, `no-store` disk.
_CACHE_CONTROL: Final = "private, no-store"

# How far either side of the server's own UTC clock a date or an instant may sit. A year back
# because "I forgot to log last month" is real; a day forward covers UTC+14 and phone clock skew.
_BACKDATE_DAYS: Final = 365
_HORIZON_DAYS: Final = 1

# Matched on psycopg3's `Diagnostic.constraint_name`, never on a substring of a driver message.
# These two are the only integrity failures this route can explain to a client.
_EXERCISE_FK: Final = "fk_logged_set_exercise_id_exercise"
_SUBTYPE_FK: Final = "fk_logged_session_activity_id_activity_kind_activity"

# ⚠️ Every detail below is a FIXED string with no interpolation. A hand-built message carrying
# request data would bypass `server/app.py::validation_error_handler`'s allowlist entirely.
_NO_PLANNED_SESSION: Final = "No such planned session."
_NO_PRESCRIBED_SET: Final = "No such prescribed set."
_NO_EXERCISE: Final = "No such exercise."
_WRONG_KIND: Final = "That session id already belongs to a different kind of activity."
_EXERCISE_MISMATCH: Final = (
    "A logged set names a different exercise than the set it was prescribed from."
)
_NOT_SAVED: Final = "Your session could not be saved."

# Every column of `logged_set` a client may write, in one tuple: a multi-row `VALUES` needs
# identical keys in every dict, and the `DO UPDATE` has to set exactly the same set.
_SET_COLUMNS: Final = (
    "exercise_id",
    "prescribed_set_id",
    "set_index",
    "actual_reps",
    "actual_work_seconds",
    "actual_load_kg",
    "rpe",
    "body_weight_kg",
    "body_weight_as_of",
    "note",
    "completed_at",
)


def _today_utc() -> date:
    """The server's own date. Bounds judge the client's value against this."""
    return datetime.now(UTC).date()


def _bounded_day(value: date) -> date:
    """A date inside the window this endpoint accepts, or a `ValueError` the client sees as 422."""
    today = _today_utc()
    if not today - timedelta(days=_BACKDATE_DAYS) <= value <= today + timedelta(days=_HORIZON_DAYS):
        raise ValueError("that date is outside the window this endpoint accepts")
    return value


def _bounded_instant(value: datetime) -> datetime:
    """The same window for an aware instant: bounds clock skew and silent backdating."""
    now = datetime.now(UTC)
    if not now - timedelta(days=_BACKDATE_DAYS) <= value <= now + timedelta(days=_HORIZON_DAYS):
        raise ValueError("that timestamp is outside the window this endpoint accepts")
    return value


def _not_found(detail: str) -> HTTPException:
    """Absent from this user's own tree. Not-yours and not-there get the same answer."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    """Well-formed, but unbuildable against stored state. Matches the house helper."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _conflict(detail: str) -> HTTPException:
    """A uuid that already names something this route may not overwrite."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _constraint_name(error: DatabaseError) -> str | None:
    """psycopg3's `Diagnostic.constraint_name` — the ONLY part of the error we may keep."""
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


class LoggedSetIn(BaseModel):
    """One set that happened, replaced whole by its `client_uuid`.

    There is no omitted-versus-null distinction per set: a `logged_set` is minted complete when
    the set finishes, and a multi-row `VALUES` requires identical keys in every row anyway.
    """

    model_config = ConfigDict(extra="forbid")

    client_uuid: UUID
    exercise_id: LookupId
    prescribed_set_id: LookupId | None = None
    set_index: SetIndex
    actual_reps: ActualReps | None = None
    actual_work_seconds: WorkSeconds | None = None
    actual_load_kg: LoadKg | None = None
    rpe: Rpe | None = None
    body_weight_kg: BodyWeightKg | None = None
    body_weight_as_of: date | None = None
    note: SetNote | None = None
    completed_at: AwareDatetime | None = None

    @field_validator("body_weight_as_of")
    @classmethod
    def _a_plausible_weigh_in(cls, value: date | None) -> date | None:
        """The snapshot's provenance date, bounded like every other date here."""
        return None if value is None else _bounded_day(value)

    @field_validator("completed_at")
    @classmethod
    def _a_plausible_instant(cls, value: datetime | None) -> datetime | None:
        """Bounded against clock skew and against backdating a set into last year."""
        return None if value is None else _bounded_instant(value)

    @model_validator(mode="after")
    def _a_weight_with_its_provenance(self) -> "LoggedSetIn":
        """A weight with no as-of date is exactly what the pair exists to prevent."""
        if (self.body_weight_kg is None) != (self.body_weight_as_of is None):
            raise ValueError("body_weight_kg and body_weight_as_of must be sent together")
        return self


class SessionLogRequest(BaseModel):
    """The activity/logged_session envelope plus the delta of sets. `extra="forbid"`.

    An **omitted** envelope field means "no change"; an explicit **`null`** means "clear", read
    through `model_fields_set` — the idiom at `server/profile/routes.py::InjuryIn`.

    `finished` is a request field and **not a column**: the only server behaviour that depends
    on finish-ness is the `planned_session.status` transition, which is why this endpoint needed
    no Alembic revision. `duration_minutes` must be **elapsed minutes so far**, floored at 1,
    never the plan's `estimated_minutes` — see the handler's `GREATEST` rule.
    """

    model_config = ConfigDict(extra="forbid")

    occurred_on: date
    duration_minutes: DurationMinutes
    discipline: Discipline
    rpe: Rpe | None = None
    started_at: AwareDatetime | None = None
    notes: SessionNotes | None = None
    location: SessionLocation | None = None
    planned_session_id: LookupId | None = None
    finished: bool = False
    sets: Annotated[list[LoggedSetIn], Field(max_length=SETS_PER_REQUEST_MAX)] = []

    @field_validator("occurred_on")
    @classmethod
    def _a_plausible_day(cls, value: date) -> date:
        """A session cannot have happened next month, and backdating is bounded at a year."""
        return _bounded_day(value)

    @field_validator("started_at")
    @classmethod
    def _a_plausible_instant(cls, value: datetime | None) -> datetime | None:
        """The same window. `None` is "not sent" or "cleared", not a value to bound."""
        return None if value is None else _bounded_instant(value)

    @model_validator(mode="after")
    def _one_row_per_conflict_key(self) -> "SessionLogRequest":
        """Two rows with one conflict key is a Postgres `cardinality_violation`, i.e. a 500."""
        # Refused rather than de-duplicated: a repeated uuid means the client's minting is
        # broken, and silently keeping one of the pair loses a set the climber performed.
        uuids = [entry.client_uuid for entry in self.sets]
        if len(set(uuids)) != len(uuids):
            raise ValueError("every set must carry a distinct client_uuid")
        indexes = [entry.set_index for entry in self.sets]
        if len(set(indexes)) != len(indexes):
            raise ValueError("every set must carry a distinct set_index")
        return self


class LoggedSetAck(BaseModel):
    """The server's id for one set, so the client can retire it from the outbox.

    Nothing the user typed is echoed back; see `SessionLogResponse`.
    """

    client_uuid: UUID
    id: int
    set_index: int


class SessionLogResponse(BaseModel):
    """What the server now holds for this session. **Always 200**, never a conditional 201.

    A replayed PUT must not change the status code, because the outbox does not branch on it.
    `duration_minutes` is the post-`GREATEST` value, so a client can see that a stale retry did
    not shorten the session.

    **No user free text is echoed** — `notes`, `location` and each set's `note` are all absent.
    So nothing in this body needs escaping downstream, and a mid-run piggyback response stays
    small even when it acknowledges a hundred sets.
    """

    id: int
    client_uuid: UUID
    occurred_on: date
    duration_minutes: int
    rpe: int | None
    planned_session_id: int | None
    planned_session_status: SessionStatus | None
    sets: list[LoggedSetAck]


class _Ownership(NamedTuple):
    """What one statement found inside this user's own plan tree."""

    planned_sessions: frozenset[int]
    exercise_by_prescribed_set: dict[int, int]


class _StoredActivity(NamedTuple):
    """The activity as Postgres now holds it, read back from the upsert's `RETURNING`."""

    id: int
    occurred_on: date
    duration_minutes: int
    rpe: int | None
    planned_session_id: int | None


def _owned(
    session: Session,
    user_id: int,
    planned_session_id: int | None,
    prescribed_set_ids: frozenset[int],
) -> _Ownership:
    """One statement for the whole flush, whatever N is; bound parameters only, never SQL text."""
    branches: list[Select[Any]] = []
    if prescribed_set_ids:
        branches.append(
            select(
                literal("prescribed_set"),
                PrescribedSet.id,
                SessionBlock.exercise_id,
            )
            .select_from(PrescribedSet)
            .join(SessionBlock, SessionBlock.id == PrescribedSet.session_block_id)
            .join(PlannedSession, PlannedSession.id == SessionBlock.planned_session_id)
            .join(Microcycle, Microcycle.id == PlannedSession.microcycle_id)
            # `mesocycle` is deliberately NOT joined: `microcycle.plan_id` is denormalised but
            # tied back by `fk_microcycle_mesocycle_id_plan_id_mesocycle`, so it cannot disagree.
            .join(Plan, Plan.id == Microcycle.plan_id)
            .where(Plan.user_id == user_id, PrescribedSet.id.in_(prescribed_set_ids))
        )
    if planned_session_id is not None:
        branches.append(
            select(
                literal("planned_session"),
                PlannedSession.id,
                cast(null(), Integer),
            )
            .select_from(PlannedSession)
            .join(Microcycle, Microcycle.id == PlannedSession.microcycle_id)
            .join(Plan, Plan.id == Microcycle.plan_id)
            .where(Plan.user_id == user_id, PlannedSession.id == planned_session_id)
        )
    if not branches:
        return _Ownership(frozenset(), {})

    planned: set[int] = set()
    exercises: dict[int, int] = {}
    for kind, row_id, exercise_id in session.execute(union_all(*branches)).all():
        if kind == "prescribed_set":
            exercises[row_id] = exercise_id
        else:
            planned.add(row_id)
    return _Ownership(frozenset(planned), exercises)


def _activity_envelope(payload: SessionLogRequest) -> dict[str, Any]:
    """Only the `activity` fields the client actually SENT: omitted means "no change"."""
    sent = payload.model_fields_set
    columns: dict[str, Any] = {}
    if "rpe" in sent:
        columns["rpe"] = payload.rpe
    if "started_at" in sent:
        columns["started_at"] = payload.started_at
    if "planned_session_id" in sent:
        columns["planned_session_id"] = payload.planned_session_id
    return columns


def _upsert_activity(
    session: Session, user_id: int, client_uuid: UUID, payload: SessionLogRequest
) -> _StoredActivity | None:
    """One statement. `None` means the uuid already names a different KIND of activity — a 409."""
    columns = _activity_envelope(payload)
    statement = pg_insert(Activity).values(
        {
            "user_id": user_id,
            "client_uuid": client_uuid,
            "activity_kind": ActivityKind.CLIMBING,
            "occurred_on": payload.occurred_on,
            "duration_minutes": payload.duration_minutes,
            **columns,
        }
    )
    # `srpe_load` never appears here — it is GENERATED. `duration_minutes` takes the GREATEST so
    # a stale late retry cannot shorten a session and silently regrade its training load.
    row = session.execute(
        statement.on_conflict_do_update(
            # ⚠️ A structural security property: the conflict target binds `user_id` from the
            # token, so the idempotency key IS the authorisation scope.
            index_elements=[Activity.user_id, Activity.client_uuid],
            set_={
                "occurred_on": payload.occurred_on,
                "duration_minutes": func.greatest(
                    Activity.duration_minutes, statement.excluded.duration_minutes
                ),
                **columns,
            },
            # A uuid that already names a bike ride matches no row here: the statement updates
            # nothing and raises nothing, and the empty `RETURNING` is the 409 signal.
            where=Activity.activity_kind == ActivityKind.CLIMBING,
        ).returning(
            Activity.id,
            Activity.occurred_on,
            Activity.duration_minutes,
            Activity.rpe,
            Activity.planned_session_id,
        )
    ).one_or_none()
    if row is None:
        return None
    return _StoredActivity(
        id=row.id,
        occurred_on=row.occurred_on,
        duration_minutes=row.duration_minutes,
        rpe=row.rpe,
        planned_session_id=row.planned_session_id,
    )


def _upsert_logged_session(session: Session, activity_id: int, payload: SessionLogRequest) -> None:
    """One statement on the PK. `activity_kind` is omitted so its server default holds."""
    sent = payload.model_fields_set
    columns: dict[str, Any] = {"discipline": payload.discipline}
    if "notes" in sent:
        columns["notes"] = payload.notes
    if "location" in sent:
        columns["location"] = payload.location
    statement = pg_insert(LoggedSession).values({"activity_id": activity_id, **columns})
    session.execute(
        statement.on_conflict_do_update(index_elements=[LoggedSession.activity_id], set_=columns)
    )


def _upsert_sets(session: Session, activity_id: int, sets: list[LoggedSetIn]) -> list[LoggedSetAck]:
    """One statement for the whole batch, or none at all when the delta is empty."""
    if not sets:
        return []
    # Sorted by uuid so two concurrent flushes take their row locks in the same order and
    # cannot deadlock. Precedent: `server/profile/routes.py::_replace_aspect_ratings`.
    rows = [
        {
            "logged_session_id": activity_id,
            "client_uuid": entry.client_uuid,
            **{name: getattr(entry, name) for name in _SET_COLUMNS},
        }
        for entry in sorted(sets, key=lambda entry: entry.client_uuid.bytes)
    ]
    statement = pg_insert(LoggedSet).values(rows)
    returned = session.execute(
        statement.on_conflict_do_update(
            index_elements=[LoggedSet.logged_session_id, LoggedSet.client_uuid],
            set_={name: statement.excluded[name] for name in _SET_COLUMNS},
        ).returning(LoggedSet.client_uuid, LoggedSet.id, LoggedSet.set_index)
    ).all()
    # `RETURNING` order is not guaranteed by Postgres, so the acks are sorted here rather
    # than trusted — a replay's response body has to be byte-identical.
    acks = [
        LoggedSetAck(client_uuid=row.client_uuid, id=row.id, set_index=row.set_index)
        for row in returned
    ]
    return sorted(acks, key=lambda ack: ack.set_index)


def _advance_planned_session(
    session: Session, user_id: int, planned_session_id: int, *, finished: bool
) -> SessionStatus:
    """One statement that re-scopes ownership, so there is no TOCTOU against the check above."""
    owned = (
        select(literal(1))
        .select_from(Microcycle)
        .join(Plan, Plan.id == Microcycle.plan_id)
        .where(Microcycle.id == PlannedSession.microcycle_id, Plan.user_id == user_id)
        .exists()
    )
    # `skipped` and `rescheduled` are deliberately NOT terminal — actually doing the session is
    # stronger evidence than a plan-screen tap that said it would not happen.
    target = SessionStatus.COMPLETED if finished else SessionStatus.IN_PROGRESS
    # The CASE is unconditional rather than a `WHERE status <> 'completed'` guard: that is what
    # keeps a finishing replay's response byte-identical, bought with one no-op row rewrite.
    row = session.execute(
        update(PlannedSession)
        .where(PlannedSession.id == planned_session_id, owned)
        .values(
            status=case(
                (PlannedSession.status == SessionStatus.COMPLETED, PlannedSession.status),
                else_=target,
            )
        )
        .returning(PlannedSession.status)
    ).one_or_none()
    if row is None:
        raise _not_found(_NO_PLANNED_SESSION)
    return SessionStatus(row.status)


@router.put("/{client_uuid}")
def log_session(
    client_uuid: UUID,
    payload: SessionLogRequest,
    principal: CurrentUser,
    session: RequestSession,
    response: Response,
) -> SessionLogResponse:
    """Create or locate this climber's session by the uuid their client minted, and merge. 200.

    A **Tier-1 write**: one request, one transaction, one Neon wake, and **at most five
    statements whatever the set count**. Called at start (`sets: []`), at every mid-run moment
    that piggybacks the outbox, and at Finish (`finished: true`).

    **`sets` merges, it never replaces.** A set is replaced whole by its `client_uuid`; a set
    already stored and absent from this payload is untouched, because a piggyback carries only
    the unsent tail. **`duration_minutes` only ever grows** — the client must send elapsed
    minutes so far, never an estimate, and issue #12's "edit a logged session" cannot reuse
    this route because it cannot shorten one.

    A `planned_session_id` or `prescribed_set_id` outside the caller's own plan tree is a 404
    identical to the missing case. A set whose `exercise_id` disagrees with its prescription is
    a 422 that rejects the **whole flush**, because the rest of that block is then suspect.
    `planned_session.status` advances to `in_progress`, or `completed` when finished, and never
    regresses. Ascents are not loggable here.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    prescribed_set_ids = frozenset(
        entry.prescribed_set_id for entry in payload.sets if entry.prescribed_set_id is not None
    )
    owned = _owned(session, principal.user_id, payload.planned_session_id, prescribed_set_ids)

    # ⚠️ Ownership BEFORE the mismatch check, always: an unowned id must never reach the 422
    # branch, or that message would confirm that somebody else's row exists.
    if (
        payload.planned_session_id is not None
        and payload.planned_session_id not in owned.planned_sessions
    ):
        raise _not_found(_NO_PLANNED_SESSION)
    if prescribed_set_ids - owned.exercise_by_prescribed_set.keys():
        raise _not_found(_NO_PRESCRIBED_SET)
    for entry in payload.sets:
        if entry.prescribed_set_id is None:
            continue
        if owned.exercise_by_prescribed_set[entry.prescribed_set_id] != entry.exercise_id:
            raise _unprocessable(_EXERCISE_MISMATCH)

    try:
        activity = _upsert_activity(session, principal.user_id, client_uuid, payload)
        if activity is None:
            raise _conflict(_WRONG_KIND)
        _upsert_logged_session(session, activity.id, payload)
        acks = _upsert_sets(session, activity.id, payload.sets)
        planned_status = (
            _advance_planned_session(
                session,
                principal.user_id,
                payload.planned_session_id,
                finished=payload.finished,
            )
            if payload.planned_session_id is not None
            else None
        )
        # Serialised BEFORE the commit, like `server/plans/routes.py::create_plan`.
        body = SessionLogResponse(
            id=activity.id,
            client_uuid=client_uuid,
            occurred_on=activity.occurred_on,
            duration_minutes=activity.duration_minutes,
            rpe=activity.rpe,
            planned_session_id=activity.planned_session_id,
            planned_session_status=planned_status,
            sets=acks,
        )
        session.commit()
    except (DataError, IntegrityError) as error:
        session.rollback()
        name = _constraint_name(error)
        if name == _EXERCISE_FK:
            raise _not_found(_NO_EXERCISE) from error
        if name == _SUBTYPE_FK:
            raise _conflict(_WRONG_KIND) from error
        # ⚠️ **Never re-raised: input minimisation applies to the LOG.** `str(DataError)` carries
        # the statement AND its bound parameters, i.e. a climber's set note and body weight.
        _logger.error(
            "session log failed: constraint=%s user_id=%s sets=%s",
            name or "unknown",
            principal.user_id,
            len(payload.sets),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=_NOT_SAVED
        ) from None
    return body


# --- GET /api/sessions/completion — how much of each planned session got done ----

# The widest window one request may ask for. A 32-week plan is 224 days, so this is the whole
# longest plan plus room, and it is what stops an unbounded scan of somebody's whole history.
_COMPLETION_SPAN_DAYS: Final = 400
# A hard server-side maximum, per CLAUDE.md's rule for list endpoints — in (session x block)
# ROWS now: every block of the 224 sessions of the longest plan at 7 a week, plus room.
_COMPLETION_ROWS_MAX: Final = 1500

CompletionState = Literal["completed", "skipped", "pending"]


class CompletionWindow(BaseModel):
    """The dates this read covers, `from`..`to` inclusive.

    Both are required and the span is capped: "return everything" is the resource-exhaustion
    risk `CLAUDE.md` names for every list endpoint, and a wider window is also a longer Neon
    read. `from` and `to` are the wire names; they are Python keywords, hence the aliases.

    `plan_id` is OPTIONAL and names the plan the caller means. Omitted, the read is every plan
    of theirs whose sessions fall in the window — the documented behaviour, unchanged. Given,
    only that plan's sessions come back: a client asking for its ACTIVE plan's own span
    otherwise spends the row cap below on plans it stood down, which can push live sessions out
    of the answer, and any caller grouping by date rather than by session id mixes plans.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    start: Annotated[date, Field(alias="from")]
    end: Annotated[date, Field(alias="to")]
    plan_id: int | None = None

    @model_validator(mode="after")
    def _bounded_span(self) -> "CompletionWindow":
        if self.end < self.start:
            raise ValueError("the end of the window is before its start")
        if (self.end - self.start).days > _COMPLETION_SPAN_DAYS:
            raise ValueError(f"that window is longer than {_COMPLETION_SPAN_DAYS} days")
        return self


class SessionCompletionOut(BaseModel):
    """How much of ONE planned session got done — **derived**, never a stored column.

    `done_block_ids` says WHICH blocks got done, over the join
    `logged_set.prescribed_set_id → session_block`: a block with EVERY prescribed set of it
    logged, keyed on `session_block.id`, the id `plans.BlockOut` carries for a persisted plan.
    `blocks_done` is its length; `block_count` counts only blocks that CAN be logged. A set with
    null `actual_*` values is a **real** completion — "I did this myself" mints exactly those.

    `status` is what the write path stored: `completed` means "pressed Finish", never "did it
    all". `state` is derived from it and from `as_of`: `completed`, `pending` for a session still
    to come, `skipped` for one whose day has passed unfinished.

    ⚠️ **`skipped` names the OUTCOME, not the cause: "past and not finished, whatever the
    reason".** A past `in_progress` session reads `skipped` and that is CORRECT — unfinished and
    skipped are the same result in real life (Kilian, 2026-08-30), which is why the UI shows only
    the percentage. Never render it as "the climber chose to skip this".

    `percent` is `null` for a session with nothing loggable in it: there is nothing to have
    done, and reporting 0% for that would read as a failure nobody had.
    """

    planned_session_id: int
    scheduled_on: date
    status: SessionStatus
    state: CompletionState
    block_count: int
    blocks_done: int
    done_block_ids: list[int]
    percent: int | None


class SessionCompletionResponse(BaseModel):
    """Completion for every planned session of this climber's inside the window.

    `as_of` is the server's own date, i.e. the boundary `state` was decided against, so the
    client never re-derives "past" from a clock of its own.

    Sessions from a stood-down plan are included when their date falls in the window and no
    `plan_id` was named — the response is keyed by `planned_session_id`, so a caller reads the
    ones it asked about.
    """

    as_of: date
    sessions: list[SessionCompletionOut]


def _percent(blocks_done: int, block_count: int) -> int | None:
    """Whole percent, half-up to match `web/src/session/runStore.ts`'s `Math.round`."""
    if block_count == 0:
        return None
    return (blocks_done * 200 + block_count) // (block_count * 2)


def _completion_state(status: SessionStatus, scheduled_on: date, today: date) -> CompletionState:
    """`skipped` is INFERRED — no endpoint writes it — and only once the day is over."""
    if status is SessionStatus.COMPLETED:
        return "completed"
    return "skipped" if scheduled_on < today else "pending"


# The block's prescribed sets, and the ones a logged set was written against. DISTINCT because a
# RE-RUN of an item writes a second row against the same prescribed set (#81: none can be deleted).
_PRESCRIBED = func.count(func.distinct(PrescribedSet.id))
_COVERED = func.count(func.distinct(case((LoggedSet.id.is_not(None), PrescribedSet.id))))


def _completion_query(user_id: int, window: CompletionWindow) -> Select[Any]:
    """ONE statement for the whole window, grouped by (session, BLOCK) rather than by session:
    "33% done" cannot say WHICH third, and no per-session query, whatever the plan's length."""
    return (
        select(
            PlannedSession.id,
            PlannedSession.scheduled_on,
            PlannedSession.status,
            # Null for a session with no blocks at all, which the outer join still yields a row
            # for — that is the `percent = null` case, not an absent session.
            SessionBlock.id.label("block_id"),
            # A block with nothing to record is out of the figure entirely: under the predicate
            # below it could never be done, and one such block would pin its session under 100%.
            (_PRESCRIBED > 0).label("counts"),
            # A logged set reaches this row only through the caller's OWN prescribed set, and
            # `PUT /api/sessions/{client_uuid}` 404s a prescribed_set_id outside their tree.
            ((_PRESCRIBED > 0) & (_COVERED == _PRESCRIBED)).label("done"),
        )
        .select_from(PlannedSession)
        .join(Microcycle, Microcycle.id == PlannedSession.microcycle_id)
        .join(Plan, Plan.id == Microcycle.plan_id)
        .outerjoin(SessionBlock, SessionBlock.planned_session_id == PlannedSession.id)
        .outerjoin(PrescribedSet, PrescribedSet.session_block_id == SessionBlock.id)
        .outerjoin(LoggedSet, LoggedSet.prescribed_set_id == PrescribedSet.id)
        .where(
            # ⚠️ The token's `user_id` is ANDed with the named plan, never replaced by it: a
            # `plan_id` belonging to somebody else must yield no rows rather than leak one.
            Plan.user_id == user_id,
            *(() if window.plan_id is None else (Plan.id == window.plan_id,)),
            PlannedSession.scheduled_on >= window.start,
            PlannedSession.scheduled_on <= window.end,
        )
        # Both are primary keys, so every other selected column is functionally dependent on
        # them and Postgres needs nothing else in the GROUP BY.
        .group_by(PlannedSession.id, SessionBlock.id)
        # Contiguous per session, which is what makes the truncation below safe to reason about.
        .order_by(PlannedSession.scheduled_on, PlannedSession.id, SessionBlock.id)
        .limit(_COMPLETION_ROWS_MAX)
    )


class _CompletionFold(NamedTuple):
    """One session, accumulating over its own (session x block) rows."""

    scheduled_on: date
    status: SessionStatus
    block_ids: list[int]
    done_block_ids: list[int]


def _fold_sessions(rows: Sequence[Any]) -> dict[int, _CompletionFold]:
    """The statement's block rows, folded to one entry per session in schedule order."""
    folded: dict[int, _CompletionFold] = {}
    for row in rows:
        fold = folded.setdefault(
            row.id, _CompletionFold(row.scheduled_on, SessionStatus(row.status), [], [])
        )
        if row.block_id is None or not row.counts:
            continue
        fold.block_ids.append(row.block_id)
        if row.done:
            fold.done_block_ids.append(row.block_id)
    # ⚠️ The cap counts BLOCK rows, so reaching it can CUT a session in half and understate its
    # `block_count` — a wrong percentage. So the last one goes; insertion order is the ORDER BY.
    if len(rows) == _COMPLETION_ROWS_MAX and folded:
        folded.popitem()
    return folded


@router.get("/completion")
def session_completion(
    window: Annotated[CompletionWindow, Query()],
    principal: CurrentUser,
    session: RequestSession,
    response: Response,
) -> SessionCompletionResponse:
    """How much of each planned session in `from`..`to` actually got done.

    **Partial completion is a DERIVED QUERY, not a column.** `planned_session.status` says
    whether Finish was pressed; this counts the blocks whose every prescribed set is logged,
    which is the only figure that can say WHICH two of three parts — and the rule behind it has
    already been tuned once, which is why no `planned_session` column holds it.

    ⚠️ **An item is DONE OR NOT** (Kilian, #82) — skipped and never-started are the same result —
    so ONE logged set no longer carries a block. That needs no stored item state: the client
    cannot mark an item done without logging its sets (`completeItem` mints every one the block
    prescribes, the clock mints them as the phases run, a skip drops only what was never sent).
    A block that cannot be logged is out of `block_count`, or one would strand its session.

    **Its own endpoint, deliberately.** `GET /api/plans/active` is already the heaviest payload
    in the app and only this screen reads these numbers, so they are fetched beside it rather
    than inside it.

    **One statement, no per-row N+1**, one Neon wake, and read-only: a demo token may call it.
    `skipped` is inferred from `as_of` — nothing in the app writes that status.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    today = _today_utc()
    rows = session.execute(_completion_query(principal.user_id, window)).all()
    return SessionCompletionResponse(
        as_of=today,
        sessions=[
            SessionCompletionOut(
                planned_session_id=planned_session_id,
                scheduled_on=fold.scheduled_on,
                status=fold.status,
                state=_completion_state(fold.status, fold.scheduled_on, today),
                block_count=len(fold.block_ids),
                blocks_done=len(fold.done_block_ids),
                done_block_ids=fold.done_block_ids,
                percent=_percent(len(fold.done_block_ids), len(fold.block_ids)),
            )
            for planned_session_id, fold in _fold_sessions(rows).items()
        ],
    )
