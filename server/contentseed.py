"""Content seed — the exercise library. NOT part of `server/seed.py`, deliberately.

`server/seed.py` stops at the vocabularies and says why: `exercise` and
`prescription_template` are **content** — names, instructions, per-phase prescriptions —
authored rather than derived from a tuple, so seeding them belongs with the authoring
task. This is that task's other half. `server/domain/exercises.py` holds the content;
this module writes it.

Run it **after** `server/seed.py`, because it resolves `climbing_aspect`, `equipment` and
`injury_area` **keys** to ids and refuses to continue if one is missing:

    uv run alembic upgrade head
    uv run python -m server.seed
    uv run python -m server.contentseed

`.github/workflows/migrate.yml` runs both, in that order, behind the same `seed` input —
so a production content edit ships by dispatching an `upgrade` run with `seed: true`.

## Idempotent by upsert on `key`, and re-running it is a true no-op

Not "harmless to re-run" — a no-op: the second run's upserts write the same values, and
its reconciliation deletes and inserts nothing. Editing a name, an instruction, a
substitution hint or a prescription and re-running updates in place, so content is
shipped by editing the domain module and dispatching a seed, never by hand-editing rows.

## ⚠️ It DELETES EXERCISES, and here is the whole rule

**Kilian's explicit call: removing a key from `server/domain/exercises.py` must really
delete the exercise, not merely hide it.** Hiding a row he judged weak is not deleting it,
and a library table that only ever grows is a library nobody can curate.

`server/seed.py`'s contract is that the seed **never deletes**, and what that rule protects
is data **something else points at**: a grade or an equipment row is referenced from a
user's profile and their training history, so pruning one would either violate a foreign
key or cascade into somebody's log. Those rows are upserted here too and never deleted.

`exercise` is the one row that can be *either*, and the database already knows which:
`session_block.exercise_id` and `logged_set.exercise_id` are **`NO ACTION`** foreign keys,
so Postgres refuses to delete a referenced exercise rather than cascading into a training
diary. So the seed asks the question first and does the right one of two things — see
`_reconcile_unauthored_exercises`. An unreferenced exercise is **deleted**, with its join
and template rows. A referenced one gets **`retired_at`**, keeps its row, and disappears
from `GET /api/library`: a diary that forgets what you did is worse than a library with one
row too many.

The three tables this module reconciles are a different case, and the difference is
structural, not a judgement call:

- `exercise_equipment` and `exercise_contraindication` are **pure join rows** — a
  composite primary key and nothing else. Nothing can reference one, because there is no
  surrogate id to reference.
- `prescription_template` has a surrogate id, and **nothing in the schema points at it**:
  `session_block` snapshots `protocol_kind` and `prescribed_set` carries its own values
  precisely so that editing the library never rewrites a plan that was already generated
  (see those models in `server/models.py`).

So no user row can be orphaned by these deletes, and they are what makes the module
honest: a content edit can *remove* a requirement — an exercise that no longer needs a
weight belt, a contraindication that was wrong, a phase an exercise should not be
prescribed in — and a seed that only ever inserted would leave the old row behind
forever, silently withholding the exercise from every user with that injury flag.

**Every delete is scoped two ways**: to the three tables above, and to the exercise ids
this module authors. A row belonging to an exercise that is not in
`server/domain/exercises.py` is never touched, so a library the seed does not know about
cannot be pruned by running it.

CLAUDE.md now rules on this case — see the `contentseed.py` bullet under "⚠️ Production data
durability", which states the three-link safety chain as the condition on the exception. This
docstring carries the detail; the rule lives there.

All statements are SQLAlchemy constructs with bound parameters — no string-built SQL, per
the injection rules in CLAUDE.md.
"""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from server.db import session_scope
from server.domain.exercises import EXERCISES, ExerciseSpec
from server.models import (
    ClimbingAspect,
    Equipment,
    Exercise,
    ExerciseContraindication,
    ExerciseEquipment,
    InjuryArea,
    LoggedSet,
    PrescriptionTemplate,
    SessionBlock,
)

# The three lookup tables this module resolves keys against. Column-identical, like the
# `_ReferenceTable` alias in `server/vocabulary/routes.py`.
_LookupTable = type[ClimbingAspect] | type[Equipment] | type[InjuryArea]


class ContentSeedError(RuntimeError):
    """A key in the library has no row in the vocabulary it names.

    Loud on purpose, and it fails **before** any write. The alternative — skipping the
    row, or the exercise — is a library that is quietly missing a requirement or a whole
    exercise, which surfaces much later as a plan prescribing something the user cannot
    do, or as an injury flag that withholds nothing.
    """


@dataclass(frozen=True, slots=True)
class ContentSeedResult:
    exercises: int
    equipment_rows: int
    contraindication_rows: int
    prescriptions: int
    # Join and template rows removed because the content no longer authors them. Reported
    # because a non-zero count on a production run is worth seeing in the job log: it
    # means an exercise stopped requiring something, or stopped being prescribed in a
    # phase. Zero on every re-run of unchanged content.
    removed_rows: int
    # The two halves of "the content dropped a whole exercise". Reported separately and
    # printed by `main()` because they are the two outcomes a curator needs to tell apart
    # on a production run: `deleted_exercises` is gone for good, `retired_exercises` is
    # still in the table because a plan or a logged set points at it. Both zero on a
    # re-run — a deleted row cannot be deleted twice, and `retired_at` is only written
    # where it is still NULL.
    deleted_exercises: int
    retired_exercises: int


def seed_exercise_library(session: Session) -> ContentSeedResult:
    """Upsert the whole library and reconcile its join rows. Does NOT commit."""
    aspect_ids = _ids_by_key(
        session, ClimbingAspect, {spec.aspect_key for spec in EXERCISES}, "climbing_aspect"
    )
    equipment_ids = _ids_by_key(
        session, Equipment, {key for spec in EXERCISES for key in spec.equipment_keys}, "equipment"
    )
    injury_ids = _ids_by_key(
        session,
        InjuryArea,
        {key for spec in EXERCISES for key in spec.contraindication_keys},
        "injury_area",
    )

    exercise_ids = _upsert_exercises(session, aspect_ids)
    _link_progressions(session, exercise_ids)

    removed = 0
    equipment_pairs = [
        (exercise_ids[spec.key], equipment_ids[key])
        for spec in EXERCISES
        for key in spec.equipment_keys
    ]
    removed += _reconcile_join(
        session, ExerciseEquipment, ExerciseEquipment.equipment_id, equipment_pairs, exercise_ids
    )
    contraindication_pairs = [
        (exercise_ids[spec.key], injury_ids[key])
        for spec in EXERCISES
        for key in spec.contraindication_keys
    ]
    removed += _reconcile_join(
        session,
        ExerciseContraindication,
        ExerciseContraindication.injury_area_id,
        contraindication_pairs,
        exercise_ids,
    )
    prescriptions = _upsert_prescriptions(session, exercise_ids)
    removed += _delete_unauthored_prescriptions(session, exercise_ids)
    # Last, and it has to be: it deletes rows in the three tables above, so running it
    # earlier would leave the reconcilers deciding about children of a parent that is
    # about to go.
    deleted, retired, cascaded = _reconcile_unauthored_exercises(session, exercise_ids)

    return ContentSeedResult(
        exercises=len(EXERCISES),
        equipment_rows=len(equipment_pairs),
        contraindication_rows=len(contraindication_pairs),
        prescriptions=prescriptions,
        removed_rows=removed + cascaded,
        deleted_exercises=deleted,
        retired_exercises=retired,
    )


def _ids_by_key(
    session: Session, model: _LookupTable, keys: set[str], vocabulary: str
) -> dict[str, int]:
    """Resolve vocabulary keys to ids, or raise naming every key that is missing.

    All of them in the message, not just the first: a seed run against a database that
    has not been vocabulary-seeded yet should say so once, rather than once per fix.
    """
    if not keys:
        return {}
    found = {
        key: row_id
        for key, row_id in session.execute(
            select(model.key, model.id).where(model.key.in_(keys))
        ).all()
    }
    missing = sorted(keys - found.keys())
    if missing:
        raise ContentSeedError(
            f"{vocabulary} has no row for {missing}. Run `python -m server.seed` first — it "
            f"upserts the vocabularies this library points at — and if a key is genuinely "
            f"new, add it to server/domain/vocabulary.py (a tuple edit, not a migration)."
        )
    return found


def _upsert_exercises(session: Session, aspect_ids: dict[str, int]) -> dict[str, int]:
    """Upsert every exercise on `key` and return the resulting id per key.

    **`media_url` is not written at all** — no column in the values, none in the update —
    because the library does not author one yet, and listing it would mean every seed run
    reset a URL somebody added out of band.

    **The two progression columns ARE written, as NULL.** They cannot be resolved on the
    insert (a forward reference points at an id that does not exist yet), and leaving them
    out of the update would make a *removed* progression pair permanent. So they are
    cleared here and rewritten by `_link_progressions` inside the same transaction.

    **`retired_at` is written as NULL too, and that is what un-retires a key that comes
    back.** An exercise can only be retired while something references it, so its row
    outlives its removal from the content — and re-authoring the same `key` has to
    restore it to the library rather than upsert a row the API still filters out. Omitting
    the column from the update would make retirement permanent for exactly the exercises
    people have already trained.
    """
    statement = insert(Exercise).values(
        [
            {
                "key": spec.key,
                "name": spec.name,
                "climbing_aspect_id": aspect_ids[spec.aspect_key],
                "protocol_kind": spec.protocol_kind,
                "discipline": spec.discipline,
                "instructions": spec.instructions,
                "substitution_hint": spec.substitution_hint,
                "retired_at": None,
                "progression_of_id": None,
                "regression_of_id": None,
            }
            for spec in EXERCISES
        ]
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[Exercise.key],
            set_={
                column: statement.excluded[column]
                for column in (
                    "name",
                    "climbing_aspect_id",
                    "protocol_kind",
                    "discipline",
                    "instructions",
                    "substitution_hint",
                    "retired_at",
                    "progression_of_id",
                    "regression_of_id",
                )
            },
        )
    )
    # Flush before reading ids back: on a first run they do not exist yet.
    session.flush()
    keys = [spec.key for spec in EXERCISES]
    return {
        key: row_id
        for key, row_id in session.execute(
            select(Exercise.key, Exercise.id).where(Exercise.key.in_(keys))
        ).all()
    }


def _link_progressions(session: Session, exercise_ids: dict[str, int]) -> None:
    """Resolve the authored progression/regression keys to ids.

    Only the specs that declare one are updated; `_upsert_exercises` has already set both
    columns to NULL, so a pair removed from the content is cleared rather than kept. The
    two columns are independent and each direction is authored explicitly — see `Exercise`
    in `server/models.py` for why neither can be inferred from the other.

    A key that names no exercise is a `ContentSeedError`, not a silent NULL: a progression
    pointing at a deleted exercise is exactly the kind of dangling reference a browse UI
    would render as an empty link.
    """
    for spec in EXERCISES:
        values: dict[str, int] = {}
        if spec.progression_of_key is not None:
            values["progression_of_id"] = _linked_id(spec, spec.progression_of_key, exercise_ids)
        if spec.regression_of_key is not None:
            values["regression_of_id"] = _linked_id(spec, spec.regression_of_key, exercise_ids)
        if values:
            session.execute(update(Exercise).where(Exercise.key == spec.key).values(**values))
    session.flush()


def _linked_id(spec: ExerciseSpec, key: str, exercise_ids: dict[str, int]) -> int:
    if key not in exercise_ids:
        raise ContentSeedError(
            f"{spec.key!r} names {key!r} as a progression or regression, but no exercise "
            f"has that key. Fix the reference in server/domain/exercises.py."
        )
    return exercise_ids[key]


def _reconcile_join(
    session: Session,
    model: type[ExerciseEquipment] | type[ExerciseContraindication],
    other_column: InstrumentedAttribute[int],
    pairs: list[tuple[int, int]],
    exercise_ids: dict[str, int],
) -> int:
    """Insert the authored join rows, then delete the ones the content dropped.

    Insert-then-delete, both scoped to the authored exercise ids. `DO NOTHING` rather than
    `DO UPDATE`: the composite primary key **is** the whole row, so there is nothing to
    update — a row either exists or it does not. See the module docstring for why deleting
    here does not weaken `server/seed.py`'s "never deletes".
    """
    if pairs:
        statement = insert(model).values(
            [
                {"exercise_id": exercise_id, other_column.key: other_id}
                for exercise_id, other_id in pairs
            ]
        )
        session.execute(statement.on_conflict_do_nothing())
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(model).where(
                model.exercise_id.in_(exercise_ids.values()),
                tuple_(model.exercise_id, other_column).not_in(pairs),
            )
        ),
    )
    session.flush()
    return result.rowcount


def _upsert_prescriptions(session: Session, exercise_ids: dict[str, int]) -> int:
    """Upsert one row per authored (exercise, phase). Returns the row count.

    Conflict target is the `UNIQUE (exercise_id, phase)` on the table, not the surrogate
    id — the pair is the natural key, and it is what lets a prescription be retuned by
    editing the domain module.

    Every nullable column is written on every run, including the ones that are NULL for
    this protocol. That is the point: `reps` and `work_seconds` are independent, so an
    exercise that changes from a timed hold to a rep scheme must have its old
    `work_seconds` cleared, and a partial update would leave both set.
    """
    rows = [
        {
            "exercise_id": exercise_ids[spec.key],
            "phase": prescription.phase,
            "sets": prescription.sets,
            "reps": prescription.reps,
            "work_seconds": prescription.work_seconds,
            "rest_seconds": prescription.rest_seconds,
            "rest_between_sets_seconds": prescription.rest_between_sets_seconds,
            "intensity_pct": prescription.intensity_pct,
            "target_rpe": prescription.target_rpe,
        }
        for spec in EXERCISES
        for prescription in spec.prescriptions
    ]
    statement = insert(PrescriptionTemplate).values(rows)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[PrescriptionTemplate.exercise_id, PrescriptionTemplate.phase],
            set_={
                column: statement.excluded[column]
                for column in (
                    "sets",
                    "reps",
                    "work_seconds",
                    "rest_seconds",
                    "rest_between_sets_seconds",
                    "intensity_pct",
                    "target_rpe",
                )
            },
        )
    )
    session.flush()
    return len(rows)


def _delete_unauthored_prescriptions(session: Session, exercise_ids: dict[str, int]) -> int:
    """Drop templates for a phase the content no longer prescribes an exercise in.

    Not seven rows per exercise: a max hang has no place in a taper week's list. So the
    set of phases an exercise is prescribed in is itself content, and narrowing it has to
    take the old row with it — otherwise the generator keeps reading a prescription nobody
    authored.
    """
    pairs = [
        (exercise_ids[spec.key], prescription.phase)
        for spec in EXERCISES
        for prescription in spec.prescriptions
    ]
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(PrescriptionTemplate).where(
                PrescriptionTemplate.exercise_id.in_(exercise_ids.values()),
                tuple_(PrescriptionTemplate.exercise_id, PrescriptionTemplate.phase).not_in(pairs),
            )
        ),
    )
    session.flush()
    return result.rowcount


def _reconcile_unauthored_exercises(
    session: Session, exercise_ids: dict[str, int]
) -> tuple[int, int, int]:
    """Delete every exercise the content no longer authors — or retire it, if it is used.

    Returns `(deleted, retired, cascaded_child_rows)`.

    ⚠️ **Referencedness is decided by a QUERY, never by catching the foreign-key
    error.** A failed statement aborts the whole Postgres transaction, and this module runs
    inside one `session_scope()`, so a caught `IntegrityError` would poison every statement
    after it — the seed would report success having written nothing. One correlated
    `EXISTS` per side, in a single round trip with the id list, answers it before anything
    is written. (If a concurrent write makes the delete fail anyway, the transaction rolls
    back and the run fails loudly. That is the correct outcome: nothing here is worth
    papering over, and the next run will re-decide with fresh facts.)

    ⚠️ **`session_block.exercise_id` is deliberately UNINDEXED, so this EXISTS
    seq-scans it — a STATED DECISION, not an oversight.** CLAUDE.md used to justify the
    missing index on the grounds that "the seed never deletes `exercise`", which this function
    made false; it now carries the replacement argument instead: **the scan is fine, and no
    index should be added.** It runs only on a seed dispatch (a rare, manual,
    out-of-band admin operation), only for exercises the content has *dropped* — zero
    rows on virtually every run, so the query is usually skipped entirely — and
    `session_block` is small (~30 blocks per generated plan). Against a 0.5 GB budget the
    index would cost write amplification and storage on every plan generated, forever, to
    save milliseconds on an operation nobody performs in the request path. CLAUDE.md's own
    "do not complete the set" rule points the same way. `logged_set.exercise_id` *is*
    indexed already, for unrelated reasons, so that half is cheap for free.

    The delete order is children before parent, explicitly, rather than relying on the
    `ON DELETE CASCADE` on the three child tables: it makes the row count reportable and it
    keeps the behaviour readable without going to the DDL. The progression pointers are
    nulled first because they are self-referential `NO ACTION` keys — an *unauthored*
    exercise can still point at another unauthored one, and `_upsert_exercises` only clears
    the pointers of rows the content authors.
    """
    authored = set(exercise_ids.values())
    stale = session.execute(
        select(
            Exercise.id,
            or_(
                select(1).where(SessionBlock.exercise_id == Exercise.id).exists(),
                select(1).where(LoggedSet.exercise_id == Exercise.id).exists(),
            ).label("referenced"),
        ).where(Exercise.id.not_in(authored))
    ).all()
    deletable = [row.id for row in stale if not row.referenced]
    referenced = [row.id for row in stale if row.referenced]

    cascaded = 0
    if deletable:
        for pointer in (Exercise.progression_of_id, Exercise.regression_of_id):
            session.execute(update(Exercise).where(pointer.in_(deletable)).values({pointer: None}))
        for child in (PrescriptionTemplate, ExerciseContraindication, ExerciseEquipment):
            cascaded += cast(
                "CursorResult[Any]",
                session.execute(delete(child).where(child.exercise_id.in_(deletable))),
            ).rowcount
        session.execute(delete(Exercise).where(Exercise.id.in_(deletable)))
        session.flush()

    retired = 0
    if referenced:
        # `retired_at IS NULL` in the predicate, so a re-run rewrites nothing and reports
        # zero. The timestamp is the moment the library stopped offering it, and rewriting
        # it on every seed would lose that.
        retired = cast(
            "CursorResult[Any]",
            session.execute(
                update(Exercise)
                .where(Exercise.id.in_(referenced), Exercise.retired_at.is_(None))
                .values(retired_at=func.now())
            ),
        ).rowcount
        session.flush()

    return len(deletable), retired, cascaded


def main() -> None:
    """`uv run python -m server.contentseed` — run after `python -m server.seed`.

    Out-of-band against production, for the same reason migrations and the reference seed
    are: it must never race a deploy.
    """
    with session_scope() as session:
        result = seed_exercise_library(session)
    print(
        f"seeded {result.exercises} exercises, {result.equipment_rows} equipment "
        f"requirements, {result.contraindication_rows} contraindications and "
        f"{result.prescriptions} prescription templates "
        f"({result.removed_rows} stale rows removed, "
        f"{result.deleted_exercises} exercises deleted, "
        f"{result.retired_exercises} retired because a plan or a log still points at them)"
    )


if __name__ == "__main__":
    main()
