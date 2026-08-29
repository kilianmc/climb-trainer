"""The closed vocabularies, and the small reference tables that carry display text.

Pure Python: no DB, no clock, no RNG, no I/O — like every module under
`server/domain/`. `server/models.py` wraps the enums below into native Postgres types
and `server/seed.py` upserts the reference tuples; the plan generator and the Pydantic
request models both import from here rather than restating a list of strings.

## Enum or lookup table?

The rule, from CLAUDE.md: **native Postgres enums for closed vocabularies, lookup
tables for anything with attributes or user-facing content.** An enum value is a
machine token that appears in SQL, in JSON and in TypeScript; a lookup row has a name,
a description and an ordering that a designer may want to change without a migration.

So `ActivityKind` is an enum and `climbing_aspect` is a table, even though both look
like "a short list of options" from the outside.

## Why the values are lower_snake_case strings

`StrEnum`, and `server/models.py` passes `values_callable` to every `Enum(...)` so the
**value** ('max_hang') is stored rather than the Python member name ('MAX_HANG'). Get
that wrong once and SCREAMING_CASE ends up in the database, in every JSON payload and
in every hand-written `WHERE` clause. `web/src/api/vocabularies.ts` mirrors these
values by hand until PR #9 generates them from the OpenAPI schema, and
`tests/test_vocabulary_contract.py` is what stops the two drifting.

## Renaming a value is a migration

Every value here is persisted. `ALTER TYPE ... RENAME VALUE` plus a data migration, not
an edit — same contract as `GradeSystemKey` in `server/domain/grades.py`.
"""

import enum
from dataclasses import dataclass
from typing import Final


class ActivityKind(enum.StrEnum):
    """What a logged activity *was*, on the `activity` supertype.

    **`other` is the escape hatch, and it is load-bearing.** Without it, the first kind
    of training nobody anticipated (a yoga class, a swim, a physio appointment) is
    unloggable until someone ships an `ALTER TYPE ... ADD VALUE` migration — so the
    honest options would be "lie about it" or "don't log it", and both corrupt the load
    history that readiness and rest-day logic read.

    Only `climbing` has a subtype row (`logged_session`); see `Activity` in
    `server/models.py` for why that is one table and not five.
    """

    CLIMBING = "climbing"
    CARDIO = "cardio"
    STRENGTH = "strength"
    MOBILITY = "mobility"
    OTHER = "other"


class AscentStyle(enum.StrEnum):
    """How a climb was done.

    **There is deliberately no separate `send` value.** "Send" is the boulderer's word
    for what a rope climber calls a redpoint — one thing, two vernaculars — and storing
    both would mean every "did they top it?" query has to remember to list two values,
    which is exactly the kind of near-duplicate that gets one of them forgotten. The UI
    is free to *label* `REDPOINT` as "Send" on a boulder; the label is display, the
    value is data.

    `ATTEMPT` records work on something not topped. It exists because a projecting
    session is real training load and real history, and a log that can only hold
    successes quietly overstates a climber's level.
    """

    ONSIGHT = "onsight"
    FLASH = "flash"
    REDPOINT = "redpoint"
    TOP_ROPE = "top_rope"
    REPEAT = "repeat"
    ATTEMPT = "attempt"


class ProtocolKind(enum.StrEnum):
    """How an exercise is executed in time — the shape the session player has to drive.

    This is what the protocol compiler (PR #15) turns into a phase timeline, so the
    distinctions here are *timing* distinctions, not muscle-group ones: what the aspect
    trained is lives in `climbing_aspect`, and what it is done on lives in `equipment`.

    `other` for the same reason `ActivityKind.OTHER` exists.
    """

    MAX_HANG = "max_hang"
    REPEATERS = "repeaters"
    INTERVALS = "intervals"
    CIRCUIT = "circuit"
    LIMIT_BOULDER = "limit_boulder"
    STRAIGHT_SETS = "straight_sets"
    LAPS = "laps"
    HOLD = "hold"
    OTHER = "other"


class Phase(enum.StrEnum):
    """A mesocycle's training emphasis.

    `DELOAD` and `TAPER` are phases rather than flags on a week: a deload is a block
    with its own prescriptions (lower volume, same intensity), not a week where the
    normal block is scaled by a multiplier, and treating it as a flag is how deload
    weeks end up accidentally as hard as the weeks around them.
    """

    BASE = "base"
    STRENGTH = "strength"
    POWER = "power"
    POWER_ENDURANCE = "power_endurance"
    PERFORMANCE = "performance"
    DELOAD = "deload"
    TAPER = "taper"


class SessionStatus(enum.StrEnum):
    """Where a *planned* session got to. Never used on a logged one.

    `SKIPPED` and `RESCHEDULED` are distinct on purpose — adherence should not punish
    someone who moved Tuesday to Wednesday the same way it treats a session that never
    happened.
    """

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    RESCHEDULED = "rescheduled"


@dataclass(frozen=True, slots=True)
class ReferenceSpec:
    """One row of a seeded lookup table: a stable key plus display text.

    `key` is the data contract (code matches on it, the seed upserts on it); `name` and
    `description` are display only and may be reworded without a migration.
    """

    key: str
    name: str
    description: str


# The eight things a climbing plan can train. Order IS the display order, and it runs
# roughly finger-strength-first because that is the order the plan generator presents
# self-ratings in. A lookup table rather than an enum: each row carries a name and a
# description that appear in the UI, and adding a ninth aspect must not be a migration.
CLIMBING_ASPECTS: Final[tuple[ReferenceSpec, ...]] = (
    ReferenceSpec(
        "finger_strength",
        "Finger strength",
        "Maximum force the fingers can hold, trained with near-maximal short efforts.",
    ),
    ReferenceSpec(
        "power",
        "Power",
        "Force produced fast — single hard moves, jumps and cuts.",
    ),
    ReferenceSpec(
        "power_endurance",
        "Power endurance",
        "Sustaining hard moves for 20-60 seconds before failing.",
    ),
    ReferenceSpec(
        "endurance",
        "Endurance",
        "Staying on the wall for minutes at a submaximal intensity.",
    ),
    ReferenceSpec(
        "technique",
        "Technique",
        "Movement quality, footwork and body positioning.",
    ),
    ReferenceSpec(
        "core_tension",
        "Core and tension",
        "Transmitting force between hands and feet on steep ground.",
    ),
    ReferenceSpec(
        "antagonist_prehab",
        "Antagonist and prehab",
        "Pushing, rotation and tendon work that keeps the pulling durable.",
    ),
    ReferenceSpec(
        "mobility",
        "Mobility",
        "Range of motion at the hips, shoulders and ankles.",
    ),
)

# ⚠️ **What the user can TRAIN ON — facilities, gear and rock. Not a gear inventory.**
# Kilian's correction, 2026-08-21, after the equipment step turned out to be a dead end for
# an outdoor-only climber: every one of the original fifteen rows was indoor kit or an indoor
# facility, so somebody whose whole practice is real rock had nothing they could honestly
# tick. **A climber without gear is not a climber who cannot train** — they train by
# climbing, and with their own body.
#
# So two things, and the second is the one a reader would otherwise undo:
#
# 1. **Outdoor boulders and outdoor routes are separate rows**, for the same reason
#    `server/domain/grades.py` keeps boulder and rope on disjoint ordinal bands and refuses
#    to convert between them: they are different training stimuli, and the plan generator has
#    to be able to prescribe outdoor route volume without prescribing outdoor bouldering.
# 2. **There is deliberately NO `bodyweight` row.** Everyone has their own body, so a
#    checkbox for it is noise — and a user who forgot to tick it would be back in the "empty
#    set means nothing" hole this change exists to fill. The invariant instead:
#    **an exercise with no `exercise_equipment` rows requires nothing and is always
#    prescribable**, and the library (PR #10) owes enough of them — bodyweight strength,
#    core, mobility, prehab — that a profile with zero equipment still gets a real plan.
#    `tests/test_equipment_vocabulary.py` guards both halves.
#
# The plan generator filters the exercise library by this, so a missing row means a
# prescribed exercise nobody can perform. Order IS display order, and adding a row is a seed
# insert (`_upsert_reference_rows` upserts on `key` and rewrites `sort_order` from the tuple
# position) — never a migration.
EQUIPMENT: Final[tuple[ReferenceSpec, ...]] = (
    ReferenceSpec("bouldering_wall", "Bouldering wall", "An indoor wall climbed without a rope."),
    ReferenceSpec("lead_wall", "Lead wall", "Indoor rope climbing with a belayer."),
    ReferenceSpec("top_rope_wall", "Top rope wall", "Indoor rope climbing on a pre-hung rope."),
    ReferenceSpec("auto_belay", "Auto belay", "Indoor rope climbing without a partner."),
    # Grouped with the places you climb rather than with the hardware, and split by
    # discipline. See the note above.
    ReferenceSpec("outdoor_boulders", "Outdoor boulders", "Bouldering on real rock."),
    ReferenceSpec(
        "outdoor_routes", "Outdoor routes", "Sport or trad routes on real rock, with a rope."
    ),
    ReferenceSpec(
        "system_board",
        "System board or spray wall",
        "Kilter, Tension, Moon, a spray wall, or any other set board you climb on.",
    ),
    ReferenceSpec("campus_board", "Campus board", "Rungs for contact-strength work."),
    ReferenceSpec("hangboard", "Hangboard", "Fixed edges for hanging protocols."),
    ReferenceSpec("no_hang_device", "No-hang device", "Handheld or pin-loaded finger training."),
    ReferenceSpec("pull_up_bar", "Pull-up bar", "A bar to hang and pull on."),
    ReferenceSpec("gymnastic_rings", "Gymnastic rings", "Rings for pulling and pushing work."),
    ReferenceSpec("free_weights", "Free weights", "Dumbbells, barbells or plates."),
    ReferenceSpec("weight_belt", "Weight belt or vest", "A way to add load to a hang or pull-up."),
    ReferenceSpec("resistance_bands", "Resistance bands", "Bands for assistance and prehab."),
    ReferenceSpec("foam_roller", "Foam roller", "Soft-tissue and mobility work."),
    ReferenceSpec("cardio_machine", "Cardio machine", "Bike, rower, treadmill or similar."),
)

# Body areas an injury can sit in. Coarse on purpose: the app is not a diagnosis tool,
# and the only decision it makes from an injury flag is which exercises to withhold
# (`exercise_contraindication`). "Left A2 pulley, grade II" belongs in a note, not in a
# vocabulary this project would then have to maintain.
INJURY_AREAS: Final[tuple[ReferenceSpec, ...]] = (
    ReferenceSpec("fingers", "Fingers", "Pulleys, tendons and joints of the hand."),
    ReferenceSpec("wrist", "Wrist", "Wrist joint and forearm insertions."),
    ReferenceSpec("elbow", "Elbow", "Tendinopathy on either side of the elbow."),
    ReferenceSpec("shoulder", "Shoulder", "Rotator cuff, labrum and shoulder joint."),
    ReferenceSpec("neck", "Neck", "Cervical spine and surrounding muscle."),
    ReferenceSpec("lower_back", "Lower back", "Lumbar spine and surrounding muscle."),
    ReferenceSpec("hip", "Hip", "Hip joint, groin and hip flexors."),
    ReferenceSpec("knee", "Knee", "Knee joint, including meniscus and patellar tendon."),
    ReferenceSpec("ankle", "Ankle", "Ankle joint and Achilles tendon."),
    ReferenceSpec("foot", "Foot", "Plantar fascia, toes and forefoot."),
    ReferenceSpec("other", "Other", "Anything the list above does not cover."),
)


@dataclass(frozen=True, slots=True)
class AscentTagSpec(ReferenceSpec):
    """One taggable fact about a climb. A `ReferenceSpec` plus a picker grouping.

    `category` groups tags in the UI. Five are seeded — `holds`, `angle`, `style`,
    `context`, `conditions` — and the list below is the authority; this docstring is not.
    It is a
    plain string on the row rather than a seventh native enum: nothing queries on it, it
    exists to lay out a picker, and only the seed ever writes it — so it is closed in
    practice without costing an `ALTER TYPE` migration, a TypeScript mirror and a
    contract test.
    """

    category: str


# ⚠️ **Tags are a FIXED vocabulary — reversed 2026-08-21, Kilian's call.**
#
# The earlier design was `ascent.tags text[]` with a GIN index, i.e. free text. It is now
# this table plus the `ascent_tag_link` join. Three reasons, worth keeping because the
# `text[]` version reads as the more flexible design and will otherwise be "restored":
#
# 1. **Free-typed tags are the one input in the product that grows without limit.** The
#    injection rules in CLAUDE.md say prefer CLOSED inputs, and a tag list is a closed set
#    in every real use ('crimpy', 'humid', 'overhang'). An open one also fragments
#    instantly — 'crimp', 'crimps', 'crimpy', 'Crimpy' — so the aggregate query it exists
#    to serve ("what do I send on?") returns four rows for one fact.
# 2. **A lookup table, not a native enum**, per CLAUDE.md's own rule: these carry a
#    display label and a grouping, which is exactly the "attributes or user-facing
#    content" test. Adding a tag is then a seed insert, not an `ALTER TYPE` migration.
# 3. It deletes the two problems the `text[]` version had — an unbounded array write
#    against a 0.5 GB database, and a GIN index nothing else in the schema needed.
ASCENT_TAGS: Final[tuple[AscentTagSpec, ...]] = (
    AscentTagSpec("crimps", "Crimps", "Small edges held with the fingertips.", "holds"),
    AscentTagSpec("slopers", "Slopers", "Rounded holds relying on friction.", "holds"),
    AscentTagSpec("pinches", "Pinches", "Holds squeezed between thumb and fingers.", "holds"),
    AscentTagSpec("pockets", "Pockets", "Holes taking one to three fingers.", "holds"),
    AscentTagSpec("jugs", "Jugs", "Large positive holds.", "holds"),
    AscentTagSpec("slab", "Slab", "Less than vertical.", "angle"),
    AscentTagSpec("vertical", "Vertical", "Around 90 degrees.", "angle"),
    AscentTagSpec("overhang", "Overhang", "Steeper than vertical.", "angle"),
    AscentTagSpec("roof", "Roof", "Horizontal ground.", "angle"),
    AscentTagSpec("dyno", "Dyno", "A jump between holds.", "style"),
    AscentTagSpec("powerful", "Powerful", "Hard individual moves.", "style"),
    AscentTagSpec("technical", "Technical", "Precision over strength.", "style"),
    AscentTagSpec("sustained", "Sustained", "No rest, many moves.", "style"),
    AscentTagSpec("compression", "Compression", "Squeezing between opposing holds.", "style"),
    AscentTagSpec("heel_hooks", "Heel hooks", "Weight taken through a heel.", "style"),
    AscentTagSpec("outdoor", "Outdoor", "On real rock.", "context"),
    AscentTagSpec("board", "Board", "On a system board.", "context"),
    AscentTagSpec("good_conditions", "Good conditions", "Cool, dry, high friction.", "conditions"),
    AscentTagSpec("humid", "Humid", "Damp, low friction.", "conditions"),
    AscentTagSpec("cold", "Cold", "Cold enough to affect the skin.", "conditions"),
)
