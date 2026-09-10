"""`/api/journal` — one diary entry written whole by its uuid, and the entries read back.

The PUT's conflict target is `(user_id, client_uuid)` with `user_id` from the token, so replay
safety and authorisation are the SAME mechanism — the house pattern from `sessions/routes.py`.

⚠️ **The entry is REPLACED whole**, unlike `sessions`' merge: a diary box is submitted whole, so
under merge semantics "I cleared the weight field" would be unexpressible. And the `not_empty`
CHECK is mirrored by a model validator, so an empty entry is a 422 at the edge, never a 500.
⚠️ **The GET's weight series is a TRAILING MEAN, never a raw day-to-day line.**
"""

import enum
import logging
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import (
    CTE,
    ColumnElement,
    Interval,
    Select,
    and_,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DatabaseError, DataError, IntegrityError
from sqlalchemy.orm import Session

from server.auth.deps import CurrentUser, RequestSession
from server.domain.vocabulary import Phase
from server.fields import BodyWeightKg, JournalBody, LookupId, WellbeingScore, bounded_day
from server.models import (
    Activity,
    JournalEntry,
    LoggedSession,
    Mesocycle,
    Microcycle,
    Plan,
    PlannedSession,
    UserProfile,
)

# One definition of "active" in the codebase, not a fourth: `_ACTIVE_STATE` is pinned to
# `uq_plan_one_active_per_user`'s own predicate by `tests/test_plans_persist.py`.
from server.plans.routes import _ACTIVE_STATE

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/journal", tags=["journal"])

# One climber's diary, so a shared-cache entry would hand a stranger their notes and their
# weigh-ins. `private` forbids the CDN, `no-store` the disk — `server/sessions/routes.py`'s rule.
_CACHE_CONTROL: Final = "private, no-store"

# Matched on psycopg3's `Diagnostic.constraint_name`, never on a substring of a driver message.
# The only integrity failure this route can explain to a client.
_SESSION_FK: Final = "fk_journal_entry_logged_session_id_logged_session"

# ⚠️ Both details are FIXED strings with no interpolation. A hand-built message carrying request
# data would bypass `server/app.py::validation_error_handler`'s allowlist entirely.
_NO_SESSION: Final = "No such session."
_NOT_SAVED: Final = "Your journal entry could not be saved."

# Exactly the columns `journal_entry`'s `not_empty` CHECK counts. `entry_date` and
# `logged_session_id` are deliberately absent: a dated entry that says nothing IS the empty row.
_NOT_EMPTY_FIELDS: Final = ("body", "feel", "sleep_quality", "skin", "body_weight_kg")

# Every column a client may write. The `DO UPDATE` sets exactly this tuple, which is what makes
# a resubmission a replacement rather than a merge.
_ENTRY_COLUMNS: Final = ("entry_date", *_NOT_EMPTY_FIELDS, "logged_session_id")


def _not_found(detail: str) -> HTTPException:
    """Absent from this user's own history. Not-yours and not-there get the same answer."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _constraint_name(error: DatabaseError) -> str | None:
    """psycopg3's `Diagnostic.constraint_name` — the ONLY part of the error we may keep."""
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


def _owns_logged_session(session: Session, user_id: int, logged_session_id: int) -> bool:
    """One statement, scoped by the token's `user_id`. A cardio activity's id is a 404 too."""
    return (
        session.scalar(
            select(Activity.id)
            .join(LoggedSession, LoggedSession.activity_id == Activity.id)
            .where(Activity.id == logged_session_id, Activity.user_id == user_id)
        )
        is not None
    )


class JournalEntryRequest(BaseModel):
    """One diary entry, replaced whole by its `client_uuid`. `extra="forbid"`.

    There is no omitted-versus-null distinction here — unlike `SessionLogRequest`, every field is
    sent on every request and an omitted one means cleared, because the box on the summary screen
    submits whole and a merge would make "I emptied the weight field" unexpressible.

    `body_weight_kg` records a **weigh-in and nothing else**. There is no goal weight, target
    weight or BMI field here or anywhere in this schema, and `entry_date` alone is not an entry:
    at least one of `body`, `feel`, `sleep_quality`, `skin` or `body_weight_kg` must be present,
    which is `journal_entry`'s `not_empty` CHECK mirrored so that it lands as a 422.
    """

    model_config = ConfigDict(extra="forbid")

    entry_date: date
    body: JournalBody | None = None
    feel: WellbeingScore | None = None
    sleep_quality: WellbeingScore | None = None
    skin: WellbeingScore | None = None
    body_weight_kg: BodyWeightKg | None = None
    logged_session_id: LookupId | None = None

    @field_validator("entry_date")
    @classmethod
    def _a_plausible_day(cls, value: date) -> date:
        """An entry cannot be dated next month, and backdating is bounded at a year."""
        return bounded_day(value)

    @model_validator(mode="after")
    def _not_an_empty_entry(self) -> "JournalEntryRequest":
        """The `not_empty` CHECK at the edge, over exactly the five columns it names."""
        if all(getattr(self, name) is None for name in _NOT_EMPTY_FIELDS):
            raise ValueError(
                "an entry must carry at least one of body, feel, sleep_quality, skin or "
                "body_weight_kg"
            )
        return self


class JournalEntryResponse(BaseModel):
    """What the server now holds for this entry. **Always 200**, never a conditional 201.

    A replayed PUT must not change the status code, because the client does not branch on it.
    **No user free text is echoed** — `body` is absent, for `SessionLogResponse`'s reason: then
    nothing in this body needs escaping downstream. The scores and the weight are absent for the
    same reason it is: the client already holds what it sent, so echoing it proves nothing.
    """

    id: int
    client_uuid: UUID
    entry_date: date
    logged_session_id: int | None


@router.put("/{client_uuid}")
def write_journal_entry(
    client_uuid: UUID,
    payload: JournalEntryRequest,
    principal: CurrentUser,
    session: RequestSession,
    response: Response,
) -> JournalEntryResponse:
    """Create or replace this climber's diary entry by the uuid their client minted. 200.

    **Two statements**, or one when the entry names no session. A `logged_session_id` outside the
    caller's own history is a 404 identical to the missing case: a caller must not be able to
    learn that a stranger's session exists, let alone hang an entry off it.

    Replay-safe by construction — the conflict target is `(user_id, client_uuid)`, so a retried
    write and a climber who reopens the summary and submits again both end with exactly ONE row.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    if payload.logged_session_id is not None and not _owns_logged_session(
        session, principal.user_id, payload.logged_session_id
    ):
        raise _not_found(_NO_SESSION)

    columns: dict[str, Any] = {name: getattr(payload, name) for name in _ENTRY_COLUMNS}
    statement = pg_insert(JournalEntry).values(
        {"user_id": principal.user_id, "client_uuid": client_uuid, **columns}
    )
    try:
        row = session.execute(
            # ⚠️ A structural security property, exactly as on the sessions route: the conflict
            # target binds `user_id` from the token, so the idempotency key IS the auth scope.
            statement.on_conflict_do_update(
                index_elements=[JournalEntry.user_id, JournalEntry.client_uuid], set_=columns
            ).returning(JournalEntry.id, JournalEntry.entry_date, JournalEntry.logged_session_id)
        ).one()
        # Serialised BEFORE the commit, like `server/plans/routes.py::create_plan`.
        body = JournalEntryResponse(
            id=row.id,
            client_uuid=client_uuid,
            entry_date=row.entry_date,
            logged_session_id=row.logged_session_id,
        )
        session.commit()
    except (DataError, IntegrityError) as error:
        session.rollback()
        name = _constraint_name(error)
        # The session was deleted between the ownership check and the insert. Ownership itself
        # cannot drift — `activity.user_id` never changes — so this is the only race here.
        if name == _SESSION_FK:
            raise _not_found(_NO_SESSION) from error
        # ⚠️ **Never re-raised: input minimisation applies to the LOG.** `str(DataError)` carries
        # the statement AND its bound parameters, i.e. the climber's diary text and body weight.
        _logger.error(
            "journal write failed: constraint=%s user_id=%s", name or "unknown", principal.user_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=_NOT_SAVED
        ) from None
    return body


# --- GET /api/journal — the entries back, and body weight's trailing mean over them ----

# A hard server-side maximum, per CLAUDE.md's rule for list endpoints. In ENTRIES: more than a
# year of writing one every day, and already more points than a trend chart can draw.
_JOURNAL_ROWS_MAX: Final = 500

# Samples per trailing mean, and the floor: a series exists exactly when one full window does.
# SAMPLES not days, so no point is ever one reading; seven is a daily logger's week.
_TREND_WINDOW: Final = 7

# A microcycle covers its own seven days, so an entry's date falls in at most one week of any one
# plan. An interval BIND, never date arithmetic built into the statement.
_WEEK: Final = literal(timedelta(days=7), Interval)

# The precedence tiers, lowest first. The plan the entry's own session belongs to beats the plan
# its date merely falls inside; `_attribution` orders on this first.
_BY_SESSION: Final = 0
_BY_DATE: Final = 1


class JournalQuery(BaseModel):
    """Which entries to read. `plan_id` is OPTIONAL and names the plan the caller means.

    Omitted, the read is this climber's newest entries across everything and the row cap is the
    whole bound: there is no date window, because the diary is drawn newest-first rather than
    over a span. Given, only the entries attributed to that plan come back, so a client asking
    about its active plan does not spend the cap on plans it stood down.

    A `plan_id` belonging to somebody else, or to nothing, yields **no entries rather than a
    404** — `CompletionWindow`'s answer and for its reason: the token's `user_id` is ANDed with
    the named plan, so a caller cannot learn that a stranger's plan exists. `extra="forbid"`.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    plan_id: int | None = None


class EntryPlanOut(BaseModel):
    """Where one entry falls in one plan. **Null attribution is NORMAL** — see `JournalResponse`.

    `phase` is the `Phase` enum value and nothing else: the client already holds the copy for it
    from `GET /api/vocabulary`'s `phase_guide`, and a second display label here is how two
    copies of the same sentence start disagreeing. `week_no` is the plan's own 1-based week.

    ⚠️ **Deterministic when two plans' weeks OVERLAP**, which abandoned plans routinely do: the
    plan reached through the entry's own `logged_session_id` wins, then the ACTIVE plan, then the
    newest by `created_at`, then the highest id. `tests/test_journal_read.py` pins the order.

    ⚠️ **The plan's NAME is not here.** `plan_id` resolves in `JournalResponse.plans`, which
    holds it once: the name is renameable (`PUT /api/plans/{plan_id}/name`), and a renameable
    string carried on every entry as well is two copies that a rename makes disagree.
    """

    plan_id: int
    phase: Phase
    week_no: int


class PlanWeekOut(BaseModel):
    """One week of one plan: the STORED `microcycle.start_date`, never `start + 7 * (n - 1)`.

    `week_no` is the plan's own 1-based week and is sent rather than left to the list index,
    so nothing downstream re-derives which week a tick belongs to.
    """

    week_no: int
    start_date: date


class JournalPlanOut(BaseModel):
    """One plan the returned entries reference, and the weeks its own chart is ruled in.

    ⚠️ **`name` lives HERE and nowhere else on this response** — see `EntryPlanOut`. It is
    user-typed and untrusted on OUTPUT as well as on input: build DOM nodes, never assemble an
    HTML string (CLAUDE.md).

    `weeks` is in week order and carries the dates `microcycle` actually holds, because a
    client that computed them from `start_date` would be re-implementing a scheduling rule —
    and `GET /api/plans/active` reaches only the ACTIVE plan's, so an older plan's chart had
    no ruler at all before this.
    """

    plan_id: int
    name: str
    weeks: list[PlanWeekOut]


class TrendPoint(BaseModel):
    """One point of a smoothed series: the mean of the seven samples ENDING at `entry_date`."""

    entry_date: date
    value: float


class WeightDirection(enum.StrEnum):
    """Which way the smoothed weight series runs. A direction, never a judgement —
    `JournalTrends` holds the rule and `tests/test_journal_read.py` guards the names."""

    UP = "up"
    DOWN = "down"
    STEADY = "steady"


# First smoothed point against the last. Each is already a mean of seven weigh-ins, so what is
# left is hydration and gut content: a few tenths of a kilo, and absolute rather than relative.
_STEADY_BAND_KG: Final = 0.5


class JournalTrends(BaseModel):
    """What this endpoint DERIVES from the weigh-ins: a trailing mean, oldest-first, and which
    way that mean runs. Fewer than seven weigh-ins is **absent rather than a two-point
    pseudo-trend**, and every point is the mean of a FULL window, so the row cap can only
    shorten the series.

    ⚠️ **`body_weight_kg` is a TRAILING MEAN, never a raw day-to-day line**: raw daily weight is
    hydration, food and time of day presented as signal. Seven readings per point, so no point
    is a single weigh-in and no weigh-in can be read back out of the series.

    ⚠️ **`body_weight_direction` is a fact about that series and carries no valence**: the first
    smoothed point against the last, no target, no outcome, and **no copy** — the words are the
    client's. The app never recommends losing weight (CLAUDE.md), so no value here may ever be
    named for one. It is present exactly when the series is.

    ⚠️ **Both are null whenever `show_body_metrics` is off** and nothing is computed for either.
    No goal weight, target weight or BMI, here or ever (`tests/test_schema_no_weight_targets.py`).

    ⚠️ **`feel`, `sleep_quality` and `skin` are NOT smoothed and not here** — a subjective 1-5
    score is not noise, the reading IS the datum, so the client plots the entries (Kilian).
    """

    body_weight_kg: list[TrendPoint] | None
    body_weight_direction: WeightDirection | None


class JournalEntryOut(BaseModel):
    """One entry exactly as stored, and the plan it falls under.

    **`body` IS returned here**, unlike `JournalEntryResponse` — reading entries back is this
    endpoint's whole purpose. ⚠️ **`body` here, and `name` on every `JournalResponse.plans`
    row, are user-typed and untrusted on OUTPUT as well as on input: build DOM nodes, never
    assemble an HTML string** (CLAUDE.md).

    `client_uuid` is returned because the edit path PUTs by it, and that PUT must REPLACE this
    row rather than mint a second one. `body_weight_kg` is returned whatever `show_body_metrics`
    says, because the PUT replaces an entry whole: a client that edited one without the stored
    weigh-in in hand would silently erase it.
    """

    id: int
    client_uuid: UUID
    entry_date: date
    body: str | None
    feel: int | None
    sleep_quality: int | None
    skin: int | None
    body_weight_kg: Decimal | None
    logged_session_id: int | None
    plan: EntryPlanOut | None


class JournalResponse(BaseModel):
    """This climber's diary entries, newest first, with body weight's trailing mean over them.

    `entries` is newest-first, for the list, and is also what the 1-5 chart is drawn from — the
    client orders it itself. `trends` is oldest-first. **An entry whose `plan` is null is
    NORMAL** — dated before any plan existed, or in a gap between two — and the UI says so
    rather than inventing a fallback.

    `plans` is the lookup every returned entry's `plan_id` resolves in: one row per plan the
    entries reference, carrying that plan's name once and its stored week starts in week order,
    so each plan's own chart has a real time axis. Empty when no entry is attributed to a plan.

    `truncated` says the row cap bit and older entries are not shown, so the UI can admit it.

    `has_entries_outside_plan` answers "is there other history to open?" for a plan-scoped read
    and is an EXISTS, never the other entries themselves. It is `false` for an unscoped read,
    where there is no outside.
    """

    entries: list[JournalEntryOut]
    plans: list[JournalPlanOut]
    trends: JournalTrends
    truncated: bool
    has_entries_outside_plan: bool


def _plan_columns(tier: int) -> tuple[Any, ...]:
    """One candidate attribution, plus every column `_attribution` ranks the candidates on."""
    return (
        JournalEntry.id.label("entry_id"),
        Plan.id.label("plan_id"),
        Mesocycle.phase.label("phase"),
        Microcycle.week_no.label("week_no"),
        literal(tier).label("tier"),
        and_(*_ACTIVE_STATE).label("is_active"),
        Plan.created_at.label("created_at"),
    )


def _up_to_plan(leg: Select[Any], user_id: int) -> Select[Any]:
    """The tail both legs share: microcycle -> mesocycle -> plan, scoped by the token's user."""
    return (
        leg.join(Mesocycle, Mesocycle.id == Microcycle.mesocycle_id)
        .join(Plan, Plan.id == Microcycle.plan_id)
        .where(JournalEntry.user_id == user_id, Plan.user_id == user_id)
    )


def _attribution(user_id: int) -> CTE:
    """At most one plan per entry: every candidate either path justifies, ranked, `rank` 1 wins."""
    by_session = (
        select(*_plan_columns(_BY_SESSION))
        .select_from(JournalEntry)
        .join(
            Activity,
            and_(
                Activity.id == JournalEntry.logged_session_id,
                Activity.user_id == JournalEntry.user_id,
            ),
        )
        .join(PlannedSession, PlannedSession.id == Activity.planned_session_id)
        .join(Microcycle, Microcycle.id == PlannedSession.microcycle_id)
    )
    by_date = (
        select(*_plan_columns(_BY_DATE))
        .select_from(JournalEntry)
        .join(
            Microcycle,
            and_(
                Microcycle.start_date <= JournalEntry.entry_date,
                JournalEntry.entry_date < Microcycle.start_date + _WEEK,
            ),
        )
    )
    candidates = union_all(
        _up_to_plan(by_session, user_id), _up_to_plan(by_date, user_id)
    ).subquery()
    return select(
        candidates.c.entry_id,
        candidates.c.plan_id,
        candidates.c.phase,
        candidates.c.week_no,
        func.row_number()
        .over(
            partition_by=candidates.c.entry_id,
            # Tier first, then the plan the climber was actually on. The id is not decoration:
            # two plans created in one transaction share a `created_at` to the microsecond.
            order_by=(
                candidates.c.tier,
                candidates.c.is_active.desc(),
                candidates.c.created_at.desc(),
                candidates.c.plan_id.desc(),
            ),
        )
        .label("rank"),
    ).cte("attribution")


def _winner(attribution: CTE) -> ColumnElement[bool]:
    """The join clause that keeps only the winning candidate of each entry."""
    return and_(attribution.c.entry_id == JournalEntry.id, attribution.c.rank == 1)


def _journal_query(user_id: int, plan_id: int | None) -> Select[Any]:
    """ONE statement for the entries and their attribution, newest first and row-capped."""
    attribution = _attribution(user_id)
    return (
        select(
            JournalEntry.id,
            JournalEntry.client_uuid,
            JournalEntry.entry_date,
            JournalEntry.body,
            JournalEntry.feel,
            JournalEntry.sleep_quality,
            JournalEntry.skin,
            JournalEntry.body_weight_kg,
            JournalEntry.logged_session_id,
            attribution.c.plan_id,
            attribution.c.phase,
            attribution.c.week_no,
        )
        .select_from(JournalEntry)
        .outerjoin(attribution, _winner(attribution))
        .where(
            # ⚠️ The token's `user_id` is ANDed with the named plan, never replaced by it: a
            # plan belonging to somebody else must yield no rows rather than leak one.
            JournalEntry.user_id == user_id,
            *(() if plan_id is None else (attribution.c.plan_id == plan_id,)),
        )
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
        # One MORE than the cap, so `truncated` is exact rather than a false positive on the
        # read that happens to hold exactly `_JOURNAL_ROWS_MAX` entries. The extra row is cut.
        .limit(_JOURNAL_ROWS_MAX + 1)
    )


def _outside_plan_query(user_id: int, plan_id: int) -> Select[Any]:
    """Has this climber an entry the plan-scoped read leaves out? An EXISTS, never the rows."""
    attribution = _attribution(user_id)
    return select(
        select(literal(1))
        .select_from(JournalEntry)
        .outerjoin(attribution, _winner(attribution))
        .where(
            JournalEntry.user_id == user_id,
            or_(attribution.c.plan_id.is_(None), attribution.c.plan_id != plan_id),
        )
        .exists()
    )


def _entry(row: Any) -> JournalEntryOut:
    """One row to one entry. `plan` is present exactly when a candidate won the ranking."""
    return JournalEntryOut(
        id=row.id,
        client_uuid=row.client_uuid,
        entry_date=row.entry_date,
        body=row.body,
        feel=row.feel,
        sleep_quality=row.sleep_quality,
        skin=row.skin,
        body_weight_kg=row.body_weight_kg,
        logged_session_id=row.logged_session_id,
        plan=None
        if row.plan_id is None
        else EntryPlanOut(
            plan_id=row.plan_id,
            phase=Phase(row.phase),
            week_no=row.week_no,
        ),
    )


# Bounded by construction rather than by a LIMIT of its own: the plan ids come from a read
# already capped at `_JOURNAL_ROWS_MAX`, and `plan.week_count` is `CHECK (BETWEEN 1 AND 52)`.
def _plan_weeks_query(user_id: int, plan_ids: Sequence[int]) -> Select[Any]:
    """The named plans and their weeks, in plan then week order, scoped by the token's user."""
    return (
        select(Plan.id, Plan.name, Microcycle.week_no, Microcycle.start_date)
        .select_from(Plan)
        .join(Microcycle, Microcycle.plan_id == Plan.id)
        .where(Plan.user_id == user_id, Plan.id.in_(plan_ids))
        .order_by(Plan.id, Microcycle.week_no)
    )


def _plans(
    session: Session, user_id: int, entries: Sequence[JournalEntryOut]
) -> list[JournalPlanOut]:
    """Every plan the entries reference, with its weeks. ONE statement, or none to issue."""
    plan_ids = sorted({entry.plan.plan_id for entry in entries if entry.plan is not None})
    if not plan_ids:
        return []
    found: dict[int, JournalPlanOut] = {}
    for row in session.execute(_plan_weeks_query(user_id, plan_ids)):
        plan = found.get(row.id)
        if plan is None:
            plan = found[row.id] = JournalPlanOut(plan_id=row.id, name=row.name, weeks=[])
        plan.weeks.append(PlanWeekOut(week_no=row.week_no, start_date=row.start_date))
    return list(found.values())


def _weigh_ins(entries: Sequence[JournalEntryOut]) -> list[tuple[date, float]]:
    """Every weigh-in, OLDEST first — `entries` arrives newest first."""
    return [
        (entry.entry_date, float(entry.body_weight_kg))
        for entry in reversed(entries)
        if entry.body_weight_kg is not None
    ]


def _trend(samples: Sequence[tuple[date, float]]) -> list[TrendPoint] | None:
    """A trailing mean over exactly `_TREND_WINDOW` samples, or None when no full window exists."""
    if len(samples) < _TREND_WINDOW:
        return None
    return [
        TrendPoint(
            entry_date=samples[end - 1][0],
            value=round(
                sum(value for _, value in samples[end - _TREND_WINDOW : end]) / _TREND_WINDOW, 2
            ),
        )
        for end in range(_TREND_WINDOW, len(samples) + 1)
    ]


def _direction(series: Sequence[TrendPoint] | None) -> WeightDirection | None:
    """Present exactly when the series is: a direction with no series behind it is unsourced."""
    if series is None:
        return None
    change = series[-1].value - series[0].value
    if abs(change) < _STEADY_BAND_KG:
        return WeightDirection.STEADY
    return WeightDirection.UP if change > 0 else WeightDirection.DOWN


def _show_body_metrics(session: Session, user_id: int) -> bool:
    """The profile's own flag. No profile row yet means the column's server default, TRUE."""
    stored = session.scalar(
        select(UserProfile.show_body_metrics).where(UserProfile.user_id == user_id)
    )
    return True if stored is None else bool(stored)


@router.get("")
def read_journal(
    query: Annotated[JournalQuery, Query()],
    principal: CurrentUser,
    session: RequestSession,
    response: Response,
) -> JournalResponse:
    """This climber's diary entries, newest first, with body weight's trailing mean over them.

    **Two to four statements**, and no per-row N+1: the profile's `show_body_metrics`, the
    entries with their plan attribution, then one bounded lookup for the referenced plans' weeks
    (only when an entry has a plan) and the EXISTS behind `has_entries_outside_plan` (only for a
    plan-scoped read). Read-only, so a demo token may call it.

    ⚠️ **Attribution is deterministic when plans OVERLAP**, which abandoned plans routinely do —
    `EntryPlanOut` states the order — and an entry attributed to nothing is normal, not an error.

    ⚠️ **The weight series is a trailing mean, never a raw day-to-day line**, and neither it
    nor its direction is computed at all when `show_body_metrics` is off. The per-entry weigh-in
    is still returned: the PUT replaces an entry whole, so a client editing without it would
    erase it.

    ⚠️ **Nothing smooths `feel`, `sleep_quality` or `skin`** — `JournalTrends` says why.
    """
    response.headers["cache-control"] = _CACHE_CONTROL
    show_body_metrics = _show_body_metrics(session, principal.user_id)
    rows = session.execute(_journal_query(principal.user_id, query.plan_id)).all()
    truncated = len(rows) > _JOURNAL_ROWS_MAX
    entries = [_entry(row) for row in rows[:_JOURNAL_ROWS_MAX]]
    series = _trend(_weigh_ins(entries)) if show_body_metrics else None
    return JournalResponse(
        entries=entries,
        plans=_plans(session, principal.user_id, entries),
        trends=JournalTrends(body_weight_kg=series, body_weight_direction=_direction(series)),
        truncated=truncated,
        has_entries_outside_plan=query.plan_id is not None
        and bool(session.scalar(_outside_plan_query(principal.user_id, query.plan_id))),
    )
