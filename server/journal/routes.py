"""`PUT /api/journal/{client_uuid}` — one diary entry, written once however often it is sent.

The conflict target is `(user_id, client_uuid)` with `user_id` from the token, so replay safety
and authorisation are the SAME mechanism — the house pattern from `sessions/routes.py`.

⚠️ **The entry is REPLACED whole**, unlike `sessions`' merge: a diary box is submitted whole, so
under merge semantics "I cleared the weight field" would be unexpressible. And the `not_empty`
CHECK is mirrored by a model validator, so an empty entry is a 422 at the edge, never a 500.
"""

import logging
from datetime import date
from typing import Any, Final
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DatabaseError, DataError, IntegrityError
from sqlalchemy.orm import Session

from server.auth.deps import CurrentUser, RequestSession
from server.fields import BodyWeightKg, JournalBody, LookupId, WellbeingScore, bounded_day
from server.models import Activity, JournalEntry, LoggedSession

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
