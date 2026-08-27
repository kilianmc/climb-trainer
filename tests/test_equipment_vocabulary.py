"""The equipment vocabulary must have an honest answer for a climber with no gear.
Not a mirror of the tuple — a constant table earns no test. This asserts a **coverage
property** nothing else in the gate can see and whose absence is invisible until a real user
hits it: if `EQUIPMENT` offers only indoor facilities and hardware, an outdoor-only climber has
nothing they can honestly tick. That shipped once, as a permanently disabled Continue button —
see CLAUDE.md's "Gating a step because its empty answer is unrecordable was a HARD DEAD-END".
**Kilian's correction, 2026-08-21: a climber without gear is not a climber who cannot train**
— they train by climbing, on rock, and with their own body. "No equipment" is a training
modality, not an absence, and this is the half a future tidy-up of the tuple could undo.
DB-free.
"""

from server.domain.grades import Discipline
from server.domain.vocabulary import EQUIPMENT

# The outdoor rows, one per discipline. Split rather than combined for the same reason
# `server/domain/grades.py` keeps boulder and rope on disjoint ordinal bands and refuses to
# convert between them: outdoor bouldering and outdoor route volume are different training
# stimuli, and PR #11's generator has to be able to prescribe one without the other.
OUTDOOR_KEYS = {
    Discipline.BOULDER: "outdoor_boulders",
    Discipline.SPORT: "outdoor_routes",
}


def test_every_discipline_has_an_outdoor_option() -> None:
    """A boulderer and a route climber must each be able to say "on rock"."""
    keys = {spec.key for spec in EQUIPMENT}
    missing = sorted(key for key in OUTDOOR_KEYS.values() if key not in keys)
    assert not missing, (
        f"EQUIPMENT has no row for {missing}. Without one, an outdoor-only climber has "
        f"nothing they can honestly tick on the equipment step — which is how that step "
        f"became a dead end. Add the row to server/domain/vocabulary.py; the seed upserts "
        f"on `key` and picks it up with no migration."
    )


def test_the_outdoor_rows_say_rock_rather_than_wall() -> None:
    """The failure mode is a row that exists but reads as indoor.

    `bouldering_wall`'s description — "any wall climbed without a rope" — is exactly the
    wording that made an outdoor climber tick nothing, so the distinguishing word has to be
    in the copy and not only in the key.
    """
    by_key = {spec.key: spec for spec in EQUIPMENT}
    for key in OUTDOOR_KEYS.values():
        spec = by_key[key]
        text = f"{spec.name} {spec.description}".lower()
        assert "rock" in text, f"{key} does not mention rock: {spec.name} — {spec.description}"


def test_bodyweight_is_NOT_a_row() -> None:
    """Deliberately absent, and this is the guard against it being "helpfully" added.

    Everyone has their own body, so a tickbox for it is noise — and worse, a user who did
    not tick it would land straight back in the hole this whole change exists to fill.
    The invariant that replaces it belongs to the exercise library (PR #10) and the
    generator (PR #11): **an exercise with no `exercise_equipment` rows needs nothing and is
    always prescribable**, and the library must seed enough of them — bodyweight strength,
    core, mobility, prehab — that a profile with zero equipment still gets a real plan.
    """
    keys = {spec.key for spec in EQUIPMENT}
    assert "bodyweight" not in keys, (
        "bodyweight must not be a checkbox — see this test's docstring. An exercise that "
        "requires no equipment is expressed by having no `exercise_equipment` rows."
    )
