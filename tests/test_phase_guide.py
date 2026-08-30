"""`PHASE_GUIDE` must cover every `Phase`, and nothing else — asserted in BOTH directions.

The copy is authored prose and none of it is restated here; what is guarded is COVERAGE, the
contract `DELIBERATELY_UNPRESCRIBED` gets in `tests/test_exercise_library.py`. A new `Phase`
cannot ship with no explanation on the plan screen, and a stale entry cannot linger as dead copy.

⚠️ Links are checked as a 2-3 item list: a short tuple is legal Python, passes every type check
and renders as a phase with a lone pointer where the copy claims a set of sources. Reachability is
never checked — seventeen fetches would redden the gate on a flaky network.
"""

from dataclasses import replace

from server.domain.vocabulary import PHASE_GUIDE, PLAN_GOAL, GuideLink, Phase, PhaseGuide

_KEYS = tuple(guide.phase.value for guide in PHASE_GUIDE)

# 2-3 per phase is the authored range: one source cannot show a contested claim from both
# sides, and more than three is a reading list rather than a pointer.
MIN_LINKS = 2
MAX_LINKS = 3


def _phases_with_unusable_links(guides: tuple[PhaseGuide, ...]) -> set[Phase]:
    """Every phase whose links fail the contract: outside 2-3, or a blank half."""
    broken: set[Phase] = set()
    for guide in guides:
        if not MIN_LINKS <= len(guide.links) <= MAX_LINKS:
            broken.add(guide.phase)
        for link in guide.links:
            if not link.url.startswith("https://") or not link.label.strip():
                broken.add(guide.phase)
    return broken


def test_every_phase_has_copy_and_no_entry_is_stale() -> None:
    """Set equality, so a missing phase and an orphaned entry both fail."""
    assert set(_KEYS) == {member.value for member in Phase}


def test_the_order_is_the_ENUM_declaration_order() -> None:
    """It is sent as an array and read as one, so its order is display order."""
    assert _KEYS == tuple(member.value for member in Phase)


def test_no_phase_appears_twice() -> None:
    """A duplicate would pass the set comparison above while shadowing one of the two."""
    assert len(_KEYS) == len(set(_KEYS))


def test_no_field_the_screen_renders_is_blank() -> None:
    """An empty string is a blank disclosure on the plan screen, not an absent one."""
    assert PLAN_GOAL.strip()
    for guide in PHASE_GUIDE:
        assert guide.label.strip()
        assert guide.summary.strip()
        assert guide.how_to_train.strip()


def test_every_phase_has_TWO_OR_THREE_usable_links() -> None:
    """The shipped copy, through the same predicate the controls below cripple."""
    assert _phases_with_unusable_links(PHASE_GUIDE) == set()


def test_a_phase_with_ZERO_links_fails() -> None:
    """Positive control for the likeliest accident: the list left empty and nothing complains."""
    stripped = tuple(
        replace(guide, links=()) if guide.phase is Phase.TAPER else guide for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(stripped) == {Phase.TAPER}


def test_a_phase_with_ONE_link_fails() -> None:
    """The lower bound, shown failing: a single link is what the placeholder round shipped."""
    thinned = tuple(
        replace(guide, links=guide.links[:1]) if guide.phase is Phase.DELOAD else guide
        for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(thinned) == {Phase.DELOAD}


def test_a_LABELLESS_or_INSECURE_link_fails() -> None:
    """The other two halves of the same predicate, shown failing rather than assumed. Both
    plants keep TWO links, so what fails is the label or the scheme, not the count arm."""
    labelless = tuple(
        replace(guide, links=(GuideLink(guide.links[0].url, "   "), guide.links[1]))
        if guide.phase is Phase.BASE
        else guide
        for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(labelless) == {Phase.BASE}

    insecure = tuple(
        replace(guide, links=(GuideLink("http://example.com", "Fine words"), guide.links[0]))
        if guide.phase is Phase.POWER
        else guide
        for guide in PHASE_GUIDE
    )
    assert _phases_with_unusable_links(insecure) == {Phase.POWER}


def test_the_comparison_would_notice_a_phase_with_no_copy() -> None:
    """Positive control: a detector that cannot see its own violation is worse than none."""
    crippled = {member.value for member in Phase if member is not Phase.TAPER}
    assert crippled != {member.value for member in Phase}
    assert set(_KEYS) != crippled


def test_the_comparison_would_notice_a_STALE_entry() -> None:
    """The other direction, which a `>=` containment check would have missed."""
    stale = set(_KEYS) | {"anaerobic_capacity"}
    assert stale != {member.value for member in Phase}
