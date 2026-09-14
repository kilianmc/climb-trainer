"""The icon map is written down in three places and nothing else in the gate holds them together.

`web/src/library/exerciseIcons.ts` names slugs and keys; the slices live in
`web/public/exercise-icons/`; the keys belong to `server/domain/`. A slug with no file is a broken
`<img>`, which fails SILENTLY — a `src` is a string, so `tsc`, ESLint and `build` stay green. A
key the library does not have is worse: the icon never appears and the exercise falls through to
the placeholder as if that were deliberate. Neither side can see the other — `tsc` cannot read
Python, `pytest` does not run the bundler — and the generator is deliberately not part of
`build`. DB-free, committed files only, so it holds in a clean clone.
"""

import re
from typing import Final

import pytest

from server.domain.exercises import EXERCISES
from server.domain.vocabulary import CLIMBING_ASPECTS
from server.settings import ROOT

MANIFEST: Final = ROOT / "web" / "src" / "library" / "exerciseIcons.ts"
SLICE_DIR: Final = ROOT / "web" / "public" / "exercise-icons"

# `slug: 'x',` inside ICON_SLICES, and `key: 'slug',` inside either map object.
SLUG: Final = re.compile(r"^\s*slug: '([a-z0-9-]+)',$", re.MULTILINE)
ENTRY: Final = re.compile(r"^\s*([a-z0-9_]+): '([a-z0-9-]+)',$", re.MULTILINE)
MAP_BLOCK: Final = r"export const {name} = \{{(.*?)\n\}} as const satisfies"

# Shortest defensible sentence about a drawing, so an empty or stub `alt` is not authored text.
MIN_ALT_LENGTH: Final = 20


@pytest.fixture(scope="module")
def source() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def _map(source: str, name: str) -> dict[str, str]:
    block = re.search(MAP_BLOCK.format(name=name), source, re.DOTALL)
    assert block is not None, f"{name} is not in {MANIFEST.name} in the expected shape"
    return {key: slug for key, slug in ENTRY.findall(block.group(1))}


def test_the_manifest_parses(source: str) -> None:
    """The regexes above are the whole guard's eyes; a silent zero-match would pass everything."""
    assert len(SLUG.findall(source)) >= 16
    assert len(_map(source, "ASPECT_ICONS")) >= 7
    assert len(_map(source, "EXERCISE_ICONS")) >= 15


def test_every_slug_has_a_committed_slice(source: str) -> None:
    declared = set(SLUG.findall(source))
    emitted = {path.stem for path in SLICE_DIR.glob("*.webp")}
    assert declared - emitted == set(), (
        "declared with no file — run `npm --prefix web run images:icons`"
    )
    assert emitted - declared == set(), "orphaned slice — delete it or add it to ICON_SLICES"


def test_every_mapped_slug_is_declared(source: str) -> None:
    declared = set(SLUG.findall(source))
    for name in ("ASPECT_ICONS", "EXERCISE_ICONS"):
        assert set(_map(source, name).values()) <= declared, f"{name} points at no such slice"


def test_every_exercise_key_is_in_the_library(source: str) -> None:
    keys = {spec.key for spec in EXERCISES}
    assert set(_map(source, "EXERCISE_ICONS")) <= keys, (
        "EXERCISE_ICONS names an exercise server/domain/exercises.py does not have"
    )


def test_every_aspect_key_is_in_the_vocabulary(source: str) -> None:
    keys = {spec.key for spec in CLIMBING_ASPECTS}
    assert set(_map(source, "ASPECT_ICONS")) <= keys, (
        "ASPECT_ICONS names an aspect server/domain/vocabulary.py does not have"
    )


def test_every_slice_has_authored_alt_text(source: str) -> None:
    alts = re.findall(r"^\s*alt: '(.*)',$", source, re.MULTILINE)
    assert len(alts) == len(SLUG.findall(source)), "a slice is missing its `alt`"
    for alt in alts:
        assert len(alt) >= MIN_ALT_LENGTH and alt.endswith("."), f"stub alt text: {alt!r}"
