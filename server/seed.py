"""Reference-data seed — the grade ladder, the small vocabularies, and the demo account.

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

from sqlalchemy import Select, func, null, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from server.db import session_scope
from server.domain import grades
from server.domain.vocabulary import (
    ASCENT_TAGS,
    CLIMBING_ASPECTS,
    EQUIPMENT,
    INJURY_AREAS,
    AscentTagSpec,
    ReferenceSpec,
)
from server.models import (
    AppUser,
    AscentTag,
    Base,
    ClimbingAspect,
    Equipment,
    Grade,
    GradeSystem,
    InjuryArea,
    UserProfile,
)

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


# The three key/name/description/sort_order lookup tables, paired with the domain tuples
# that define them. One list rather than three call sites, because the upsert is
# identical and a fourth table should be one line, not one more copy of the block.
#
# **Not the exercise library.** `exercise` and `prescription_template` are *content* —
# names, instructions, media, per-phase prescriptions — authored deliberately rather than
# derived from a tuple, so seeding them belongs with the authoring task, not here. This
# module stays limited to vocabularies small enough to read in one screen.
_REFERENCE_TABLES: tuple[tuple[type[Base], tuple[ReferenceSpec, ...]], ...] = (
    (ClimbingAspect, CLIMBING_ASPECTS),
    (Equipment, EQUIPMENT),
    (InjuryArea, INJURY_AREAS),
    # `ascent_tag` rides the same upsert because `AscentTagSpec` IS a `ReferenceSpec` —
    # the extra `category` column is picked up by `_reference_row` below rather than by a
    # second copy of the block.
    (AscentTag, ASCENT_TAGS),
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    grade_systems: int
    grades: int
    # `(table name, row count)` per lookup table, so `main()` can report what it did
    # without this dataclass growing a field per table. A tuple rather than a dict
    # because the dataclass is frozen, and a frozen dataclass carrying a dict is a
    # dataclass that raises the first time anything tries to hash it.
    reference_rows: tuple[tuple[str, int], ...]


def seed_reference_data(session: Session) -> SeedResult:
    """Upsert every grade system and grade, plus the demo account. Does NOT commit."""
    # `sort_order` is the tuple position, exactly like the four `_REFERENCE_TABLES` — so
    # display order is edited by moving a line in `server/domain/grades.py` rather than by
    # renumbering a column, and it no longer depends on the serial (issue #55, `0006`).
    system_stmt = insert(GradeSystem).values(
        [
            {
                "key": spec.key.value,
                "name": spec.name,
                "discipline": spec.discipline,
                "sort_order": position,
            }
            for position, spec in enumerate(grades.GRADE_SYSTEMS)
        ]
    )
    session.execute(
        system_stmt.on_conflict_do_update(
            index_elements=[GradeSystem.key],
            set_={
                "name": system_stmt.excluded.name,
                "discipline": system_stmt.excluded.discipline,
                "sort_order": system_stmt.excluded.sort_order,
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

    reference_rows = tuple(
        (model.__tablename__, _upsert_reference_rows(session, model, specs))
        for model, specs in _REFERENCE_TABLES
    )

    _seed_demo_user(session)
    _seed_demo_profile(session)

    return SeedResult(
        grade_systems=len(grades.GRADE_SYSTEMS),
        grades=len(grades.GRADES),
        reference_rows=reference_rows,
    )


def _upsert_reference_rows(
    session: Session, model: type[Base], specs: tuple[ReferenceSpec, ...]
) -> int:
    """Upsert one key/name/description/sort_order lookup table. Returns the row count.

    Conflict target is `key`, the natural key — so rewording a name or reordering the
    list propagates, while the surrogate `id` that `user_equipment`, `user_injury`,
    `exercise` and `user_aspect_rating` all point at stays put. **Never deletes**, for
    the same reason the grade ladder never does: a removed row would either violate a
    foreign key or cascade into somebody's profile.

    `sort_order` comes from the tuple's position, so display order is edited by moving a
    line in `server/domain/vocabulary.py` rather than by renumbering a column.
    """
    rows = [_reference_row(spec, position) for position, spec in enumerate(specs)]
    statement = insert(model).values(rows)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["key"],
            # Every column except the conflict target, derived from the row rather than
            # listed — so `ascent_tag.category` is kept up to date without this function
            # knowing that some tables have one.
            set_={column: statement.excluded[column] for column in rows[0] if column != "key"},
        )
    )
    session.flush()
    return len(specs)


def _reference_row(spec: ReferenceSpec, position: int) -> dict[str, object]:
    """One lookup row. `sort_order` is the tuple position; `category` only if present."""
    row: dict[str, object] = {
        "key": spec.key,
        "name": spec.name,
        "description": spec.description,
        "sort_order": position,
    }
    if isinstance(spec, AscentTagSpec):
        row["category"] = spec.category
    return row


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


# The demo profile, as decided with Kilian (2026-08-24). Deployment fixture data, exactly
# like the demo account it hangs off — the demo mount has to show a real plan, and a plan
# needs a plannable profile.
#
# **French 6a now, French 6b target.** A two-rung sport gap, which the periodisation table
# turns into 4 blocks and therefore **16 weeks** — long enough to show a base block, the
# strength/power/power-endurance middle and a performance block with its taper, short enough
# to scroll. `tests/test_plans_api.py` pins the 16 as a guard: a change to the gap table or
# to these two labels must not silently reshape the one plan a portfolio visitor sees.
_DEMO_CURRENT_GRADE_LABEL = "6a"
_DEMO_TARGET_GRADE_LABEL = "6b"

# Monday, Wednesday, Saturday — bits 0, 2 and 5. Three days for three sessions, so the
# weekday chooser has exactly one answer and the demo plan is the same every time.
_DEMO_AVAILABLE_WEEKDAYS = 0b0100101
_DEMO_SESSIONS_PER_WEEK = 3

# One strength and one weakness, and they MUST differ —
# `ck_user_profile_strength_and_weakness_differ`. Endurance as the strength and finger
# strength as the weakness is the ordinary shape of a 6a sport climber, and it is the pair
# that makes the weakness bias visible in the plan: finger strength is prescribable in six
# of the seven phases, so it appears in nearly every session.
_DEMO_STRENGTH_ASPECT_KEY = "endurance"
_DEMO_WEAKNESS_ASPECT_KEY = "finger_strength"


def _seeded_id(session: Session, statement: Select[tuple[int]], what: str) -> int:
    """One id read back out of the seed's own output, or a loud failure.

    Every id below is resolved by its **key or label through the seeded ladder**, never
    hardcoded: a serial follows INSERT order, so a literal id is correct only on the database
    it was read from. A missing row means the vocabulary moved under the demo profile, which
    is a content decision to take deliberately rather than a row to invent.
    """
    found = session.scalar(statement)
    if found is None:
        raise DemoUserSeedError(
            f"the demo profile needs {what}, and the seeded reference data has no such row. "
            f"Either it was renamed in server/domain/, or this seed ran before its own "
            f"reference upserts. Fix the reference to match, or retire the demo profile."
        )
    return int(found)


def _seed_demo_profile(session: Session) -> None:
    """Upsert the demo account's training profile. Idempotent, and it deletes nothing.

    No migration: every column here exists as of `0006`, and this is a row, not a schema
    change. **Zero `user_equipment` rows, exactly like every real user** — issue #54 deleted
    the step that wrote them and `POST /api/plans/preview` assumes the whole vocabulary
    instead, so seeding gear here would make the demo the one account in the system whose
    plan came from a different input than everyone else's.
    """
    current_grade_id = _seeded_id(
        session,
        select(Grade.id)
        .join(GradeSystem, Grade.grade_system_id == GradeSystem.id)
        .where(
            GradeSystem.key == grades.GradeSystemKey.FRENCH.value,
            Grade.label == _DEMO_CURRENT_GRADE_LABEL,
        ),
        f"French {_DEMO_CURRENT_GRADE_LABEL}",
    )
    target_grade_id = _seeded_id(
        session,
        select(Grade.id)
        .join(GradeSystem, Grade.grade_system_id == GradeSystem.id)
        .where(
            GradeSystem.key == grades.GradeSystemKey.FRENCH.value,
            Grade.label == _DEMO_TARGET_GRADE_LABEL,
        ),
        f"French {_DEMO_TARGET_GRADE_LABEL}",
    )
    strength_aspect_id = _seeded_id(
        session,
        select(ClimbingAspect.id).where(ClimbingAspect.key == _DEMO_STRENGTH_ASPECT_KEY),
        f"the {_DEMO_STRENGTH_ASPECT_KEY} aspect",
    )
    weakness_aspect_id = _seeded_id(
        session,
        select(ClimbingAspect.id).where(ClimbingAspect.key == _DEMO_WEAKNESS_ASPECT_KEY),
        f"the {_DEMO_WEAKNESS_ASPECT_KEY} aspect",
    )

    columns = {
        # Derived from the target grade and never accepted from a client, the same rule
        # `PATCH /api/profile` follows: a French target IS a rope goal.
        "primary_discipline": grades.Discipline.SPORT,
        "target_grade_id": target_grade_id,
        "current_grade_id": current_grade_id,
        "sessions_per_week": _DEMO_SESSIONS_PER_WEEK,
        "available_weekdays": _DEMO_AVAILABLE_WEEKDAYS,
        "strength_aspect_id": strength_aspect_id,
        "weakness_aspect_id": weakness_aspect_id,
        "display_name": "Demo climber",
        # The injuries step, answered with "nothing is hurting": a timestamp and no
        # `user_injury` rows is the only way to express that, and without it the demo
        # account reads as a profile that never reached step 4.
        "injuries_reviewed_at": func.now(),
    }
    statement = insert(UserProfile).values({"user_id": DEMO_USER_ID, **columns})
    session.execute(
        # Every column is rewritten on every run, for the same reason `password_hash` is
        # forced back to NULL above: the demo profile is a fixture, so the seed is what
        # defines it and a stray edit is undone by the next run. Nothing is deleted — the
        # demo has no child rows to delete, and `seed.py` never deletes.
        statement.on_conflict_do_update(
            index_elements=[UserProfile.user_id],
            set_={name: statement.excluded[name] for name in columns},
        )
    )
    session.flush()


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
    counts = ", ".join(f"{count} {name}" for name, count in result.reference_rows)
    print(
        f"seeded {result.grade_systems} grade systems, {result.grades} grades, "
        f"{counts}, and the demo account with its plannable profile"
    )


if __name__ == "__main__":
    main()
