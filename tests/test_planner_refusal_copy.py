"""The `/plan` screen's copy of the refusal sentences, checked against the server's.

`web/src/plan/blueprint.ts::BLOCKER_MESSAGES` holds five of the six `REFUSAL_MESSAGES`
verbatim, because `usePlanPreview` is `enabled` on the client already knowing the profile is
unplannable — so the sentence must exist before the request that would return it. The
duplication is unavoidable; the two copies drifting is not. No test on either side of the wire
can see one copy reworded. DB-free and Node-free, and it carries a vacuity guard: the parsed
key set must be the five reasons, or a parser that found nothing would agree with everything.
"""

import re
from pathlib import Path
from typing import Final

from server.domain.planner import REFUSAL_MESSAGES, RefusalReason
from server.settings import ROOT

_BLUEPRINT: Final[Path] = ROOT / "web" / "src" / "plan" / "blueprint.ts"
_DECLARATION: Final = "const BLOCKER_MESSAGES: Record<PreviewBlockerReason, string> = {"

# The five the client can see for itself. `CROSS_DISCIPLINE_GRADES` needs the grade ladder and
# stays server-only on purpose — see the module docstring in `blueprint.ts`.
_SHARED: Final[tuple[RefusalReason, ...]] = (
    RefusalReason.NO_TARGET_GRADE,
    RefusalReason.NO_CURRENT_GRADE,
    RefusalReason.SESSIONS_PER_WEEK_UNANSWERED,
    RefusalReason.AVAILABLE_WEEKDAYS_UNANSWERED,
    RefusalReason.NO_AVAILABLE_DAYS,
)

# One entry per two-space-indented `key:`, running to the next one; then every quoted literal in
# it, joined — Prettier splits a long sentence across `+`-concatenated literals and switches
# quote style per literal to avoid escaping, so both forms have to be accepted.
_ENTRY_RE: Final = re.compile(r"^  (\w+):(.*?)(?=^  \w+:|\Z)", re.DOTALL | re.MULTILINE)
_LITERAL_RE: Final = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")


def _web_messages() -> dict[str, str]:
    body = _BLUEPRINT.read_text(encoding="utf-8")
    start = body.index(_DECLARATION) + len(_DECLARATION)
    end = body.index("\n};", start)
    block = body[start:end]

    messages: dict[str, str] = {}
    for key, value in _ENTRY_RE.findall(block):
        parts = [
            re.sub(r"\\(.)", r"\1", single or double)
            for single, double in _LITERAL_RE.findall(value)
        ]
        messages[key] = "".join(parts)
    return messages


def test_the_screen_quotes_exactly_the_five_reasons_it_can_see() -> None:
    """The vacuity guard, and the "did somebody add a sixth" guard, in one assertion."""
    assert sorted(_web_messages()) == sorted(reason.value for reason in _SHARED)


def test_both_copies_of_every_shared_sentence_are_byte_identical() -> None:
    """The point of the file. A reword in one place fails here, naming the sentence."""
    web = _web_messages()
    assert {reason.value: web[reason.value] for reason in _SHARED} == {
        reason.value: REFUSAL_MESSAGES[reason] for reason in _SHARED
    }


def test_the_cross_discipline_sentence_is_not_duplicated_client_side() -> None:
    """It lives in one place, and the `/plan` screen renders the 422's detail verbatim instead.

    Asserted against the whole file rather than the declaration, because the way it would come
    back is somebody pasting it into a component's markup.
    """
    sentence = REFUSAL_MESSAGES[RefusalReason.CROSS_DISCIPLINE_GRADES]
    assert sentence not in _BLUEPRINT.read_text(encoding="utf-8")
