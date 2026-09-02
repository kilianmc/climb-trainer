"""`README.md` is the pitch and nothing else, and no prose may live in two files at once.

Markdown is this gate's blind spot: `ruff`, `tsc`, `mypy` and `test_comment_budget.py` all read
source only, so the trim that cut README from 229 lines to 46 could be undone by one "the README
is missing a Getting started section" edit with nothing going red.

**What it CANNOT catch:** whether the prose is true, or a duplicate INSIDE `CLAUDE.md`. Whether
that file's *citations* of README still land is the sibling arm in `test_claude_md_claims.py`,
which already owns every claim it makes.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from server.settings import ROOT

README: Final = ROOT / "README.md"
CLAUDE: Final = ROOT / "CLAUDE.md"

# Every other section was deleted because CLAUDE.md carried the same facts WITH the reasons.
# Adding a row is a decision about where docs live, not a formatting tweak.
ALLOWED_SECTIONS: Final = ("What it does", "Stack")

# A cap, not a target: 46 lines when written. The slack is for editing the pitch, never for a
# new section, which ALLOWED_SECTIONS refuses independently anyway.
README_MAX_LINES: Final = 60

# Roughly one wrapped line of prose: long enough that two files cannot collide on a short
# technical phrase, short enough to catch a copied sentence.
SHINGLE_WORDS: Final = 10

# EMPTY BY DESIGN: README was clean when this was written, so there is no backlog, no ratchet,
# and every hit is a regression rather than a legacy row.
DUPLICATION_ALLOWLIST: Final[tuple[str, ...]] = ()

_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)


def _sections(text: str) -> list[str]:
    return [m.group(1).strip() for m in _HEADING.finditer(text)]


def _prose_words(text: str) -> list[str]:
    """Markdown stripped down to the words a reader would actually say out loud."""
    text = _FENCE.sub(" ", text)
    text = re.sub(r"`[^`]*`", " ", text)  # inline code: names, not prose
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # keep link text, drop the target
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return text.split()


def _shingles(words: list[str]) -> dict[str, int]:
    """Every SHINGLE_WORDS-long run, mapped to where it starts, so failures can quote it."""
    return {
        " ".join(words[i : i + SHINGLE_WORDS]): i
        for i in range(max(0, len(words) - SHINGLE_WORDS + 1))
    }


def test_readme_carries_only_the_pitch() -> None:
    found = _sections(README.read_text())
    assert tuple(found) == ALLOWED_SECTIONS, (
        f"README.md sections are {found}, expected {list(ALLOWED_SECTIONS)}.\n"
        "README is the shop window: the pitch and the stack list, nothing operational. "
        "Anything else belongs in CLAUDE.md next to the reason it exists — see its master map. "
        "If a section really does belong in README, add it to ALLOWED_SECTIONS in the same PR."
    )


def test_readme_does_not_creep_back() -> None:
    lines = len(README.read_text().splitlines())
    assert lines <= README_MAX_LINES, (
        f"README.md is {lines} lines, cap is {README_MAX_LINES}. It was cut to 46 on purpose; "
        "growth this large is a section coming back under a heading level the other arm misses."
    )


def test_readme_and_claude_md_share_no_prose() -> None:
    readme_words = _prose_words(README.read_text())
    claude_shingles = _shingles(_prose_words(CLAUDE.read_text()))
    shared = sorted(
        run
        for run in _shingles(readme_words)
        if run in claude_shingles and run not in DUPLICATION_ALLOWLIST
    )
    assert not shared, (
        f"{len(shared)} run(s) of {SHINGLE_WORDS}+ words appear in BOTH README.md and "
        "CLAUDE.md. Delete the README copy — CLAUDE.md is the file agents are told to read "
        "before editing, so it wins every tie:\n"
        + "\n".join(f"  - ...{run}..." for run in shared[:10])
    )


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_the_guarded_files_exist(path: Path) -> None:
    """Renaming either file must break this suite loudly rather than silently pass on nothing."""
    assert path.is_file(), f"{path.name} is missing; this suite guards it and cannot run blind."
