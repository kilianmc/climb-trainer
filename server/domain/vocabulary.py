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


# What a climbing plan can train, in display order: finger strength first, then down the energy
# systems, because that is the order the plan generator presents self-ratings in. A lookup table
# rather than an enum so a row carries display text, and so adding one is a seed insert (#98).
# ⚠️ No key here may collide with a `Phase` value — `tests/test_equipment_vocabulary.py` proves it.
CLIMBING_ASPECTS: Final[tuple[ReferenceSpec, ...]] = (
    ReferenceSpec(
        "finger_strength",
        "Finger strength",
        "Maximum force the fingers can hold, trained with near-maximal short efforts.",
    ),
    ReferenceSpec(
        "general_strength",
        "General strength",
        "Maximum force from the legs, hips and pulling muscles, trained slow and heavy.",
    ),
    ReferenceSpec(
        "power",
        "Power",
        "Force produced fast — the single hard move, and the short burst that ends the "
        "moment you are powered out.",
    ),
    ReferenceSpec(
        "anaerobic_capacity",
        "Anaerobic capacity",
        "Tolerating the burn and clearing it: half-minute bursts, repeated on long rests.",
    ),
    ReferenceSpec(
        "power_endurance",
        "Power endurance",
        "Making hard moves while already pumped — around thirty of them, on rests no "
        "longer than the work.",
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


@dataclass(frozen=True, slots=True)
class GuideLink:
    """One further-reading link: URL and the words the screen renders for it, as ONE record.
    A pair by construction, so a URL can never reach the markup with nothing to click."""

    url: str
    label: str


@dataclass(frozen=True, slots=True)
class PhaseGuide:
    """The UNIVERSAL half of a phase's copy, keyed by the enum: no row, no seed, no migration.
    What a phase *is* never varies by climber; `server/plans/routes.py` derives the plan half."""

    phase: Phase
    label: str
    summary: str
    how_to_train: str
    links: tuple[GuideLink, ...]


# ⚠️ **Describes what THIS generator prescribes, not periodisation in general.** Every claim
# is checkable in `periodisation.py`, and the plan's own numbers are derived, never restated here.
PLAN_GOAL: Final = (
    "Every block is three loading weeks and one unloading week. The blocks run in order — base "
    "first, the strength qualities in the middle, performance last — and a quality is maintained "
    "after its own block rather than previewed before it."
)

# ⚠️ **Authored prose with sourced further reading: 2-3 links a phase, checked by
# `tests/test_phase_guide.py`.** Reword a claim only with a source that still supports it.
PHASE_GUIDE: Final[tuple[PhaseGuide, ...]] = (
    PhaseGuide(
        Phase.BASE,
        "Base",
        "The block that builds the capacity every later block spends — mileage, movement, and "
        "enough aerobic base to recover between hard goes rather than just survive them. It goes "
        "first because it is the slowest thing in the plan to build: a real aerobic adaptation "
        "wants eight weeks or more of honest work.",
        "Volume before intensity. Long, continuous, submaximal climbing, one to three sessions a "
        "week, progressing by adding time before adding difficulty. Finish able to do more than "
        "you did, because climbing a base block to failure costs you the plan, not just the week. "
        "Whether maximum strength belongs inside a base phase is genuinely contested; this plan "
        "gives strength its own block so these weeks stay spent on capacity. Whether a climber "
        "needs heavy lower-body strength at all is contested three ways: one position calls the "
        "deadlift close to the best strength exercise a climber can do, a second caps it low and "
        "would rather you spent the effort on the climbing that mimics it, and a third holds "
        "that its specificity is low and the fatigue it leaves subtracts from climbing. The "
        "squat is the most disputed exercise of the three, so this plan prescribes unilateral "
        "leg work at low volume and asks you to add depth before you add load. Endurance leads "
        "every session here, with technique behind it; general strength and anaerobic capacity "
        "start in this block because they are the two slowest qualities in the plan to "
        "arrive — and power sits last on purpose.",
        (
            GuideLink(
                "https://www.climbstrong.com/resource-posts/third-gear-the-aerobic-energy-system",
                "Climb Strong: the aerobic energy system",
            ),
            GuideLink(
                "https://www.trainingbeta.com/wp-content/uploads/2015/05/1.-Alex-Barrows-Training-Doc-V2-for-training-beta.pdf",
                "Alex Barrows: adaptation times (PDF, §3)",
            ),
            GuideLink(
                "https://trainingforclimbing.com/cameron-horsts-proven-strategy-for-endurance-training/",
                "Eric Hörst: high-volume submaximal climbing",
            ),
        ),
    ),
    PhaseGuide(
        Phase.STRENGTH,
        "Max strength",
        "Maximum strength is the ceiling the rest of your climbing sits under: the most force your "
        "fingers and pulling muscles can produce in a single effort. It matters because it is the "
        "slowest quality in the plan to build and the one that raises everything above it — and "
        "because hand strength tracks climbing ability more closely than almost anything else you "
        "can measure.",
        "High intensity, low volume, full rest. Short maximal efforts — seven to ten seconds on "
        "the fingers — with minutes rather than seconds between them, two or three sessions a "
        "week at most, and always from a rested state rather than tacked onto the end of a "
        "session. Progress by adding load, not repetitions. How much hangboarding a block "
        "warrants is genuinely contested: some coaches program it twice a week as standard, "
        "others hold that you should hangboard only if fingers are your identified weakness. "
        "Fingers lead here — depending on your current grade the plan owes one or two real "
        "hangboard sessions a week, scheduled first in the session rather than behind the "
        "climbing. General strength and anaerobic capacity are high priority through this block "
        "too, and the aerobic work stays high alongside them on purpose: raising your tolerance "
        "for the burn without also raising your ability to clear it is worse than doing "
        "neither.",
        (
            GuideLink(
                "https://strengthclimbing.com/eric-horst-7-53-hangboard-routine/",
                "The 7-53 max-hang protocol, explained",
            ),
            GuideLink(
                "https://stevenlow.org/my-7-5-year-self-assessment-of-climbing-strength-training-and-hangboard/",
                "Steven Low: 7.5 years of strength and hangboard training",
            ),
            GuideLink(
                "https://www.climbstrong.com/resource-posts/tendon-strength-a-primer",
                "Climb Strong: tendons adapt slowly (a primer)",
            ),
        ),
    ),
    PhaseGuide(
        Phase.POWER,
        "Power",
        "Power is force applied fast: the hard single move, the cut-loose, the move you either do "
        "or you don't. It runs on the alactic system, which supplies maximal effort for under "
        "about ten seconds and, given real rest, produces very little fatigue. Training it raises "
        "the hardest move you can do, which is usually what a grade is actually asking.",
        "Three to five moves at genuine 100 percent, then rest until you mean it — minutes, not "
        "seconds. Keep total volume low, arrive rested, and stop when the quality drops instead "
        "of pushing on: one all-out effort does more for power than a pile of moderate attempts. "
        "Getting sweaty and pumped means you have quietly switched to training something else. "
        "Limit boulders lead the session and contact strength sits right behind them, and power "
        "endurance is deliberately absent so the attempts stay maximal. Anaerobic capacity is "
        "kept alive at roughly one session a week rather than dropped, because it takes months "
        "to build and only weeks to lose.",
        (
            GuideLink(
                "https://www.trainingbeta.com/4-keys-to-limit-bouldering/",
                "Matt Pincus: four keys to limit bouldering",
            ),
            GuideLink(
                "https://www.climbstrong.com/resource-posts/optimizing-first-gear-training-the-alactic-energy-system",
                "Climb Strong: the alactic system, and why it costs little",
            ),
        ),
    ),
    PhaseGuide(
        Phase.POWER_ENDURANCE,
        "Power endurance",
        "The ability to keep making hard moves when you are already pumped — typically 20 to 60 "
        "moves with no real rest, which is what most sport routes actually are. It is the quality "
        "that decides whether you fall at the chains having done every move in isolation. It also "
        "comes back within weeks, which is why it sits late in the plan rather than early.",
        "Fixed intensity, fixed rests, and a work duration that matches your route: intervals at "
        "a grade or two below your onsight limit, held at that grade until you fail, rather than "
        "random hard laps. Dropping the intensity to survive the set turns the session into "
        "endurance training under a different name. How hard these sessions should be is "
        "contested — one school argues that training to a searing pump is too intense to build "
        "repeatable capacity, and that the aerobic work underneath matters more. Power endurance "
        "leads here with aerobic endurance immediately behind it, because the capacity underneath "
        "is what lets the next hard session happen two days later. Heavy general strength is "
        "deliberately absent: strength is the quality that holds longest, so it keeps across a "
        "block this short while a heavy session would compete for exactly the recovery these "
        "ones need.",
        (
            GuideLink(
                "https://www.climbing.com/skills/winter-endurance-training/",
                "Power-endurance intervals: setting the grade and the rests",
            ),
            GuideLink(
                "https://gripped.com/indoor-climbing/boost-your-power-endurance-with-bouldering-4x4s/",
                "Bouldering 4x4s, and the choices inside them",
            ),
            GuideLink(
                "https://www.climbstrong.com/resource-posts/fundamentals-of-endurance",
                "Climb Strong: why 'train till pumped' is not capacity training",
            ),
        ),
    ),
    PhaseGuide(
        Phase.PERFORMANCE,
        "Performance",
        "The block where you stop building and start converting. Nothing you add now arrives in "
        "time; what moves the grade is knowing the climb — beta, sequences, rest positions, "
        "clipping stances, when to go. This is the block where the previous ones get spent.",
        "Choose the project deliberately, then treat every attempt as information: work sections, "
        "rehearse the sequences you keep failing, write the beta down, and link progressively "
        "bigger pieces. The attempts are the training, so protect them — over-projecting "
        "produces the same flat, declining performance that over-training does. Limit attempts "
        "and redpoint burns lead this block, with power endurance right behind so stamina is "
        "still trained if that is your weakness. Anaerobic capacity is deliberately absent: the "
        "burn work is the first thing to go once the objective is inside four weeks.",
        (
            GuideLink(
                "https://www.climbing.com/skills/learn-this-redpoint-smarter-to-redpoint-harder/",
                "Redpoint smarter: working the moves and the clips",
            ),
            GuideLink(
                "https://www.trainingbeta.com/matt-pincus-projecting-principles/",
                "Matt Pincus: the principles behind projecting",
            ),
            GuideLink(
                "https://gripped.com/profiles/maximizing-your-late-season-projecting/",
                "Choosing a project you can actually finish this season",
            ),
        ),
    ),
    PhaseGuide(
        Phase.DELOAD,
        "Deload",
        "The fourth week of every block, and the week in which the previous three actually become "
        "fitness. Training is only the stimulus; the adaptation happens in the recovery. A block "
        "with no unload week ends up as accumulated fatigue that looks exactly like a plateau.",
        "Cut the volume roughly in half and keep the intensity honest. Same number of sessions, "
        "shorter, on ground you move well on — a deload is not a week off and not a week to climb "
        "through. How often a climber needs one is contested: sources put it anywhere from every "
        "third week to every eighth, and some would judge it by feel rather than schedule it at "
        "all. This plan fixes it at every fourth week, because a cadence you do not have to judge "
        "is the one you actually take. It is a block in its own right rather than a scaled-down "
        "one: technique and mobility lead at low load, and the qualities that cost the most to "
        "recover from sit last.",
        (
            GuideLink(
                "https://gripped.com/indoor-climbing/training-hard-heres-why-you-need-a-deload-week/",
                "Why you need a deload week",
            ),
            GuideLink(
                "https://stevenlow.org/the-fundamentals-of-bodyweight-strength-training/",
                "Steven Low: recovery weeks (see 'Proper recovery weeks')",
            ),
            GuideLink(
                "https://www.davemacleod.com/blog/rest",
                "Dave MacLeod: rest days — how many, and what's in them",
            ),
        ),
    ),
    PhaseGuide(
        Phase.TAPER,
        "Taper",
        "The final week of the plan, pointed at one thing: arriving fresh. Fatigue hides fitness, "
        "so the taper's whole job is to let the previous months show up on the day. Nothing you "
        "add this week can make you stronger, and plenty can make you tired.",
        "Volume down to roughly half, intensity unchanged or even a touch higher. Keep the short, "
        "sharp, maximal efforts — they cost almost nothing to recover from — and drop the "
        "capacity work that leaves you pumped. Climb on your target style, on ground you already "
        "move well on, and stop before you are tired. There is no isolated finger loading at all "
        "this week, no full power-endurance session, no anaerobic capacity work and no heavy "
        "general strength session — but short maximal efforts are still prescribed.",
        (
            GuideLink(
                "https://www.trainingbeta.com/wp-content/uploads/2015/05/1.-Alex-Barrows-Training-Doc-V2-for-training-beta.pdf",
                "Alex Barrows on tapering (PDF, §3.3)",
            ),
            GuideLink(
                "https://gripped.com/indoor-climbing/how-to-peak-for-outdoor-climbing-trips/",
                "How to peak for an outdoor trip",
            ),
        ),
    ),
)
