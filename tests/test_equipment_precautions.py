"""The gear precautions are AUTHORED in `web/` and their audience is DECIDED in `server/`.

`web/src/library/equipmentPrecautions.ts` holds one string per piece of gear, keyed on
`equipment.key`; `FINGER_LOADING_EQUIPMENT_KEYS` is the rows that load the fingers directly and
therefore owe one, authored once per gear and never per exercise (Kilian). It is NOT
`equipment.description`, whose seeded content is definitions, and it lives in `web/` because a
key the payload already ships needs no column, no wire field and no migration. Neither side can
see the other — `tsc` cannot read Python, `vitest` does not import the domain — so a fourth
finger-loading row would otherwise ship with 12 exercises silent about warming up.
"""

import re
from typing import Final

import pytest
from test_exercise_library import IMPROVISED_EDGE_RE

from server.domain.exercises import FINGER_LOADING_EQUIPMENT_KEYS
from server.domain.vocabulary import EQUIPMENT
from server.settings import ROOT

MANIFEST: Final = ROOT / "web" / "src" / "library" / "equipmentPrecautions.ts"

MAP_BLOCK: Final = r"export const EQUIPMENT_PRECAUTIONS = \{(.*?)\n\} as const satisfies"
# Prettier puts a long value on its own line, so the key and the string may be one line or two.
KEY: Final = re.compile(r"^ {2}([a-z0-9_]+):", re.MULTILINE)
ENTRY: Final = re.compile(r"^ {2}([a-z0-9_]+):[ \n]+'(.*)',$", re.MULTILINE)

# Longer than every seeded `equipment.description` in the library, which is the copy that must
# never end up here: the shortest defensible precaution is a sentence plus its reason.
MIN_PRECAUTION_LENGTH: Final = 120


@pytest.fixture(scope="module")
def precautions() -> dict[str, str]:
    block = re.search(MAP_BLOCK, MANIFEST.read_text(encoding="utf-8"), re.DOTALL)
    assert block is not None, f"EQUIPMENT_PRECAUTIONS is not in {MANIFEST.name} in that shape"
    return dict(ENTRY.findall(block.group(1)))


def test_the_manifest_parses(precautions: dict[str, str]) -> None:
    """The regex above is this guard's only eye: a silent zero-match would pass every arm."""
    block = re.search(MAP_BLOCK, MANIFEST.read_text(encoding="utf-8"), re.DOTALL)
    assert block is not None
    assert set(KEY.findall(block.group(1))) == set(precautions), (
        "a precaution's key parsed but its string did not — an apostrophe in the copy makes "
        "Prettier switch to double quotes, which `ENTRY` above does not read. Reword it."
    )
    assert len(precautions) >= len(FINGER_LOADING_EQUIPMENT_KEYS), (
        f"{len(precautions)} precautions parsed against {len(FINGER_LOADING_EQUIPMENT_KEYS)} "
        f"rows that owe one, so the arms below are reading a map they cannot see whole."
    )


def test_every_FINGER_LOADING_GEAR_ROW_carries_a_precaution(precautions: dict[str, str]) -> None:
    """⚠️ GUARD. The precaution is a property of the GEAR, so a new finger-loading row is a new
    piece of safety copy — and 12 exercises that render nothing is how it ships without one."""
    missing = sorted(FINGER_LOADING_EQUIPMENT_KEYS - set(precautions))
    assert not missing, (
        f"these finger-loading equipment rows have no precaution: {missing}. Every exercise "
        f"requiring one renders `ExerciseDetail`'s 'Before you load' block from "
        f"{MANIFEST.name}, and with no entry there the block is silent — which reads as "
        f"'nothing to say about loading your fingers'. Author one string per row there; it "
        f"needs no column and no migration. Removing the row from "
        f"FINGER_LOADING_EQUIPMENT_KEYS is not the fix: that list is also what the "
        f"improvised-edge safety guard reads."
    )


def test_every_precaution_names_a_real_equipment_row(precautions: dict[str, str]) -> None:
    """A typo'd key is copy nothing can ever render, and no screen reports it."""
    keys = {spec.key for spec in EQUIPMENT}
    assert set(precautions) <= keys, (
        f"{sorted(set(precautions) - keys)} is not an `equipment.key`. The authority is "
        f"server/domain/vocabulary.py."
    )


def test_no_precaution_suggests_improvising_an_edge(precautions: dict[str, str]) -> None:
    """⚠️ SAFETY BOUNDARY, the same matcher the library's `substitution_hint` arm uses: a
    warm-up note is the one other place an improvised edge could be suggested to a reader."""
    for key, text in precautions.items():
        hit = IMPROVISED_EDGE_RE.search(text)
        assert hit is None, (
            f"{key}'s precaution says {hit.group(0)!r}: {text!r}. Nothing in this app may "
            f"suggest improvising a finger edge (CLAUDE.md), and a precaution is read as "
            f"advice. Reword the copy — never delete a stem from IMPROVISED_EDGE_STEMS, which "
            f"is shared with the library's own hint guard. The gear's parts can be named "
            f"without those words: 'the biggest holds on the board' does it."
        )


def test_every_precaution_is_AUTHORED_COPY_and_not_a_DEFINITION(
    precautions: dict[str, str],
) -> None:
    """⚠️ GUARD on the trap this file exists to avoid: `equipment.description` is a DEFINITION
    ("Fixed edges for hanging protocols.") and a definition in a precaution slot warns nobody."""
    descriptions = {spec.key: spec.description for spec in EQUIPMENT}
    for key, text in precautions.items():
        assert text != descriptions.get(key), (
            f"{key}'s precaution is its `equipment.description` verbatim. That column is "
            f"display copy for a checkbox; one column cannot mean two things for different "
            f"rows. Author the warning."
        )
        assert len(text) >= MIN_PRECAUTION_LENGTH and text.endswith("."), (
            f"{key}'s precaution is {len(text)} characters: {text!r}. Under "
            f"{MIN_PRECAUTION_LENGTH} it is a label rather than a precaution — say what to do "
            f"before loading, and why that gear is the one asking."
        )
