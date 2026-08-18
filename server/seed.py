"""Reference-data seed — the grade ladder, and the demo account.

**This is the single seed module: CI, local development and production all call it.**
That is deliberate. A test fixture that seeds its own hand-written rows tests a table
production never has, and the divergence is invisible until a query works in CI and
returns nothing in production.

Idempotent by upsert on the natural keys, so re-running it after a migration or a
ladder edit is safe and cheap.

**It never deletes.** A grade removed from `server/domain/grades.py` stays in the table
rather than being pruned, because user rows will reference `grade.id` (target grade,
ascent grade) and a delete would either violate a foreign key or, worse, cascade into
someone's training history. Retiring a rung is therefore a deliberate migration, not a
side effect of editing a tuple.

The **demo account** is seeded here too. It is deployment fixture data, not user data:
demo-scope tokens carry its id, and that id has to mean the same thing in CI and in
production for the same reason the grade ladder does.

All statements are SQLAlchemy constructs with bound parameters — no string-built SQL
anywhere, per the injection rules in CLAUDE.md. That includes the sequence repair below,
which looks like raw SQL but is `func.setval(...)` with bound values throughout.
"""

from dataclasses import dataclass

from sqlalchemy import func, null, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from server.db import session_scope
from server.domain import grades
from server.models import AppUser, Grade, GradeSystem

# The `.example` TLD is reserved by RFC 2606 and can never be registered, so this
# address is unmistakably not a person's. (`.invalid` would be equally fake but
# `email-validator` rejects it outright, which would make the "the demo account can
# never be logged into" path a 422 instead of exercising the NULL-hash branch.)
# **No real user data is ever seeded into demo** — the rich fake training history the
# demo mount shows off is PR #18's job, and it will be generated, not copied from anyone.
DEMO_USER_EMAIL = "demo@climb-trainer.example"

# **A PINNED id, and therefore part of the data contract** — changing it is a migration,
# not an edit. `POST /api/auth/demo` puts this straight into the token's `sub` so that
# the endpoint can issue a demo token with **zero SQL**; see the route's docstring for
# why that matters (a bot trickling one request a minute at a DB-touching endpoint keeps
# Neon awake around the clock and busts the whole free allowance).
DEMO_USER_ID = 1


class DemoUserSeedError(RuntimeError):
    """The pinned demo id or email is occupied by something that is not the demo account.

    Loud on purpose. The alternative — quietly repointing the demo token at whatever row
    happens to hold id 1, or quietly rewriting a real person's email to the demo address
    — is silent data loss in one direction and a privacy breach in the other.
    """


@dataclass(frozen=True, slots=True)
class SeedResult:
    grade_systems: int
    grades: int


def seed_reference_data(session: Session) -> SeedResult:
    """Upsert every grade system and grade, plus the demo account. Does NOT commit."""
    system_stmt = insert(GradeSystem).values(
        [
            {"key": spec.key.value, "name": spec.name, "discipline": spec.discipline}
            for spec in grades.GRADE_SYSTEMS
        ]
    )
    session.execute(
        system_stmt.on_conflict_do_update(
            index_elements=[GradeSystem.key],
            set_={
                "name": system_stmt.excluded.name,
                "discipline": system_stmt.excluded.discipline,
            },
        )
    )
    # Flush the upsert before reading ids back: the grade rows need `grade_system_id`,
    # and on a first run those ids do not exist yet.
    session.flush()

    id_by_key = {
        key: system_id
        for system_id, key in session.execute(select(GradeSystem.id, GradeSystem.key))
    }

    grade_stmt = insert(Grade).values(
        [
            {
                "grade_system_id": id_by_key[spec.system.value],
                "label": spec.label,
                "ordinal": spec.ordinal,
            }
            for spec in grades.GRADES
        ]
    )
    session.execute(
        grade_stmt.on_conflict_do_update(
            # The natural key. Re-pointing a label at a different rung is the one edit
            # that must propagate, since everything comparable is derived from ordinal.
            #
            # KNOWN SHARP EDGE, left as-is: this handles a conflict on
            # (grade_system_id, label), but `grade` also has a unique constraint on
            # (grade_system_id, ordinal). Swapping two labels' ordinals in one edit
            # therefore raises IntegrityError instead of upserting, because the
            # intermediate state collides on the *other* constraint. That is a loud,
            # correct failure — the fix is a migration, not a cleverer upsert — but do
            # not add a second `on_conflict` here expecting it to cover both.
            index_elements=[Grade.grade_system_id, Grade.label],
            set_={"ordinal": grade_stmt.excluded.ordinal},
        )
    )
    session.flush()

    _seed_demo_user(session)

    return SeedResult(grade_systems=len(grades.GRADE_SYSTEMS), grades=len(grades.GRADES))


def _seed_demo_user(session: Session) -> None:
    """Upsert the demo account at its pinned id. Idempotent, and it never deletes anything.

    `password_hash` is forced back to NULL on every run, not merely defaulted on insert.
    That is the point: a NULL hash is what makes the demo account structurally
    unloggable through `/api/auth/login`, so if anything ever sets one — a stray fixture,
    a manual `UPDATE`, a future bug — the next seed run takes it away again.

    The id is written explicitly, which brings two hazards this function has to close.
    """
    # HAZARD 1: id 1 belongs to somebody real. Only reachable if a registration beat the
    # first seed run on a fresh database (the documented order is migrate -> seed ->
    # deploy). The INSERT below would fail on the primary key anyway — Postgres refuses,
    # so a real row can never be clobbered — but "duplicate key value violates
    # pk_app_user" during a production seed is a terrible message to debug from.
    occupant = session.scalars(select(AppUser).where(AppUser.id == DEMO_USER_ID)).one_or_none()
    if occupant is not None and not occupant.is_demo:
        raise DemoUserSeedError(
            f"app_user.id {DEMO_USER_ID} is reserved for the demo account (DEMO_USER_ID) "
            f"but belongs to a real account ({occupant.email!r}). Demo tokens carry that "
            f"id, so seeding cannot continue. Resolve it deliberately: move the real row "
            f"to a free id, or change DEMO_USER_ID in a migration."
        )

    statement = insert(AppUser).values(
        id=DEMO_USER_ID,
        email=DEMO_USER_EMAIL,
        password_hash=None,
        is_demo=True,
    )
    session.execute(
        # Conflict target stays the EMAIL, not the id. That way a pre-existing demo row
        # is updated in place, while a collision on the *id* is left to raise — the one
        # case where failing is the correct behaviour.
        statement.on_conflict_do_update(
            index_elements=[AppUser.email],
            set_={"password_hash": null(), "is_demo": True},
        )
    )
    session.flush()

    seeded_id = session.scalar(select(AppUser.id).where(AppUser.email == DEMO_USER_EMAIL))
    if seeded_id != DEMO_USER_ID:
        raise DemoUserSeedError(
            f"the demo account exists at id {seeded_id}, not the pinned DEMO_USER_ID "
            f"{DEMO_USER_ID}. Demo tokens would point at the wrong row. This happens on a "
            f"database seeded before the id was pinned: delete the demo row "
            f"({DEMO_USER_EMAIL}) and re-run the seed — it holds no user data."
        )

    _advance_user_id_sequence(session)


def _advance_user_id_sequence(session: Session) -> None:
    """Push `app_user_id_seq` past the explicitly-inserted demo id.

    **Without this, the first real registration collides on the primary key** — an
    explicit `INSERT ... (id) VALUES (1)` does not consume a sequence value, so `nextval`
    still returns 1 and the new user hits `pk_app_user`. The symptom would be a
    mysterious 409 on somebody's very first sign-up (the register handler maps
    `IntegrityError` to "email already registered"), which is about as misleading as an
    error can get.

    Monotonic by construction: the target is the greatest of the current sequence value,
    the largest id present, and `DEMO_USER_ID`, so this can only ever move the sequence
    **forward**. A plain `GREATEST(MAX(id), demo_id)` would *lower* it on a table with
    gaps at the top, and handing out ids that an in-flight transaction has already taken
    is not a class of bug worth risking to save a term.

    No raw SQL: `pg_get_serial_sequence`'s arguments are function *values*, not
    identifiers, so they bind as ordinary parameters.
    """
    sequence = func.pg_get_serial_sequence(AppUser.__tablename__, "id")
    highest_id = select(func.max(AppUser.id)).scalar_subquery()
    session.execute(
        select(
            func.setval(
                sequence,
                func.greatest(
                    func.coalesce(highest_id, 0),
                    func.coalesce(func.pg_sequence_last_value(sequence), 0),
                    DEMO_USER_ID,
                ),
            )
        )
    )


def main() -> None:
    """`uv run python -m server.seed` — run after `alembic upgrade head`.

    Out-of-band against production, for the same reason migrations are: it must never
    race a deploy.
    """
    with session_scope() as session:
        result = seed_reference_data(session)
    print(
        f"seeded {result.grade_systems} grade systems, {result.grades} grades, and the demo account"
    )


if __name__ == "__main__":
    main()
