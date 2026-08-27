"""Every mechanically checkable claim in `CLAUDE.md` must resolve against what it describes.
`CLAUDE.md` is the map every agent reads before touching this repo, and nothing else in the gate
reads it back. A renamed script, a moved file or a reworded heading leaves it wrong, silently, and
a wrong map is worse than no map.

**What it CANNOT catch:** a wrong *reason*, an obsolete threshold, a measured number that has
moved, or prose that is accurate and no longer wise. It proves the paths, scripts, revisions,
headings and env vars still exist — never that the advice attached to them is right. The
highest-value arm is index integrity, and it runs in BOTH directions.
"""

import json
import re
from typing import Final

import pytest

from server.settings import ROOT

CLAUDE_MD: Final = ROOT / "CLAUDE.md"

# Token boundaries include `-`, `.`, `_` and `/`. Without them a token is TRUNCATED and the
# truncation invents failures: `mf-contract.test.ts` splits at the hyphen and the tail
# `contract.test.ts` resolves against nothing, so nine correct lines of documentation read as
# nine bugs. A guard that lands red on correct docs gets disabled in its first week.
TOKEN: Final = re.compile(r"[A-Za-z0-9_./*+-]+")
BACKTICKED: Final = re.compile(r"`([^`\n]+)`")
HEADING: Final = re.compile(r"^(#{2,6})\s+(.*)$")

PATH_PREFIXES: Final = ("server/", "web/", "tests/", "migrations/", "api/", "scripts/", ".github/")

# Paths CLAUDE.md names on purpose that do NOT exist. Each one is a deliberate statement about
# an absence, so it needs a reason rather than a filesystem hit.
ABSENT_PATHS: Final = {
    "web/src/api/vocabularies.ts": (
        "documented as GONE — the hand-written vocabulary mirror retired by PR #9's codegen. "
        "The section exists to stop somebody recreating it."
    ),
}

# The ten env vars this project actually has, written out as LITERALS. A regex over backticked
# `[A-Z_]{4,}` yields sixty-plus tokens including `SELECT`, `EXISTS`, `PATCH`, `NULL`,
# `ERESOLVE` and Python constants like `PUBLIC_ROUTES` — so the arm would be measuring markdown
# capitalisation, not configuration. Each name declares where it is expected to resolve.
ENV_VARS: Final = {
    "DATABASE_URL": ("server/settings.py", ".env.example", ".github/workflows/ci.yml"),
    "DATABASE_URL_UNPOOLED": (
        "server/settings.py",
        ".env.example",
        ".github/workflows/migrate.yml",
    ),
    "CT_TEST_DATABASE_URL": ("package.json", ".env.example", "tests/conftest.py"),
    "AUTH_SECRET": ("server/settings.py", ".env.example"),
    "COOKIE_SECURE": ("server/settings.py", ".env.example"),
    "CORS_ORIGINS": ("server/settings.py", ".env.example", ".github/workflows/ci.yml"),
    "VERCEL": ("server/settings.py", "server/devseed.py"),
    "VERCEL_ENV": ("server/settings.py", "server/devseed.py"),
    "CLIMB_DEV_SEED": ("server/devseed.py",),
}
# The tenth, and it is the odd one out: it is the SHELL's variable, read by `portfolio-shell`,
# and this repo only documents the constraint on its value. Asserted ABSENT here, so the day it
# does appear in this repo the entry has to be re-read rather than quietly satisfied.
EXTERNAL_ENV_VAR: Final = "VITE_CLIMB_REMOTE_URL"

# Only these two can never be indexed. `Stack` and the docs-clean TODO were DELETED rather than
# exempted, and `Repo layout` now has an entry — so a third exemption is a decision, not a habit.
UNINDEXED_SECTIONS: Final = {
    "Overview": "the preamble — it describes the product, it carries no rule to look up",
    "Index — find the rule before you write the code": "the index cannot point at itself",
}

CI_JOBS: Final = ("web", "server", "secrets")


# ---------------------------------------------------------------------------------
# Reading the document
# ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def source() -> str:
    return CLAUDE_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def lines(source: str) -> list[str]:
    return source.splitlines()


def _unfenced(lines: list[str]) -> list[str]:
    """Lines outside ``` fences. Shell snippets would otherwise feed the path arm `$VAR`."""
    kept: list[str] = []
    inside = False
    for line in lines:
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            kept.append(line)
    return kept


def normalise(text: str) -> str:
    """Punctuation and whitespace collapsed, lowercased — so `**bold**` and `—` do not count."""
    kept = [character if character.isalnum() else " " for character in text]
    return " ".join("".join(kept).split()).lower()


def _headings(lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for line in lines:
        match = HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2).strip()))
    return found


def _index_bounds(lines: list[str]) -> tuple[int, int]:
    start = next(i for i, line in enumerate(lines) if line.startswith("## Index"))
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## "))
    return start, end


def _scripts() -> dict[str, str]:
    merged: dict[str, str] = {}
    for manifest in (ROOT / "package.json", ROOT / "web" / "package.json"):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        merged.update({str(k): str(v) for k, v in data["scripts"].items()})
    return merged


# ---------------------------------------------------------------------------------
# The eight arms
# ---------------------------------------------------------------------------------


def test_every_npm_script_it_tells_you_to_run_exists(source: str) -> None:
    """A renamed script leaves the instructions pointing at nothing, and nothing notices."""
    scripts = _scripts()
    named = {
        name.rstrip(".,")
        for name in re.findall(r"npm (?:--prefix web )?run ([A-Za-z0-9:_-]+)", source)
    }
    assert named, "no `npm run` instructions were found at all — the extraction regex is broken"
    missing = sorted(name for name in named if name not in scripts)
    assert not missing, (
        f"CLAUDE.md tells you to run {missing}, which is in neither `package.json`'s nor "
        f"`web/package.json`'s `scripts`. Rename the doc or restore the script."
    )


def test_the_quality_gate_chain_claims_match_the_real_scripts(lines: list[str]) -> None:
    """The `## Quality gate` block claims what each script chains to. Read it back.

    Those three comments are the only place the gate's *order* is written down, and the order is
    load-bearing (issue #26 put `build` before `test`).
    """
    scripts = _scripts()
    start = next(i for i, line in enumerate(lines) if line.startswith("## Quality gate"))
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## "))
    claims = [
        (match.group(1), match.group(2))
        for line in lines[start:end]
        if (match := re.match(r"npm run ([a-z:]+)\s+#\s*(?:==\s*)?(.+)$", line.strip()))
        # A chain claim, not a one-line description of what a script is for.
        if re.search(r"&&|->|→", match.group(2))
    ]
    assert len(claims) >= 3, f"expected the three chain claims in `## Quality gate`, saw {claims}"
    for name, chain in claims:
        actual = scripts[name]
        for step in re.split(r"&&|->|→", chain):
            step = step.strip()
            if not step:
                continue
            assert step in actual, (
                f"CLAUDE.md says `npm run {name}` runs `{step}`, but its script value is "
                f"{actual!r}. The gate's documented order is the only place that order exists."
            )


def test_every_repo_rooted_path_it_names_resolves(lines: list[str]) -> None:
    """86-odd backticked paths. A moved file leaves the map pointing at a hole."""
    named: set[str] = set()
    for line in _unfenced(lines):
        for span in BACKTICKED.findall(line):
            for token in TOKEN.findall(span):
                token = token.rstrip(".,")
                if token.startswith(PATH_PREFIXES):
                    named.add(token)
    assert len(named) > 50, f"only {len(named)} paths extracted — the token regex is too narrow"

    missing: list[str] = []
    for path in sorted(named):
        if path in ABSENT_PATHS:
            continue
        if "*" in path:
            if not list(ROOT.glob(path)):
                missing.append(path)
        elif not (ROOT / path).exists():
            missing.append(path)
    assert not missing, (
        f"CLAUDE.md names {len(missing)} path(s) that do not exist: {missing}. If the absence is "
        f"deliberate, say so in ABSENT_PATHS with a reason; otherwise fix the path."
    )


def test_every_deliberately_absent_path_is_still_absent() -> None:
    """The other direction. A recreated file makes its "this is GONE" section a lie."""
    resurrected = [path for path in ABSENT_PATHS if (ROOT / path).exists()]
    assert not resurrected, (
        f"{resurrected} exist(s) again, but CLAUDE.md documents them as gone. Either the "
        f"section is stale or somebody recreated exactly the file it warns against."
    )


def test_every_test_function_name_it_cites_exists(source: str) -> None:
    """Mixed case deliberately: this repo's guard tests SHOUT the invariant in their names."""
    cited = set(re.findall(r"\btest_[A-Za-z0-9_]+\b(?!\.py)", source))
    assert cited, "no test function names were cited — check the regex before trusting the green"
    defined: set[str] = set()
    for module in (ROOT / "tests").glob("*.py"):
        defined.update(re.findall(r"def (test_[A-Za-z0-9_]+)", module.read_text(encoding="utf-8")))
    missing = sorted(name for name in cited if name not in defined)
    assert not missing, (
        f"CLAUDE.md cites {missing}, which no test in `tests/` defines. A citation of a "
        f"renamed test is how a documented guarantee stops being checkable."
    )


def test_every_alembic_revision_id_it_names_exists(source: str) -> None:
    """A revision id in prose is a promise about what the database has run."""
    named = {
        token
        for span in BACKTICKED.findall(source)
        for token in TOKEN.findall(span)
        if re.fullmatch(r"0\d{3}", token)
    }
    assert named, "no revision ids extracted"
    files = [path.name for path in (ROOT / "migrations" / "versions").glob("*.py")]
    missing = sorted(rev for rev in named if not any(name.startswith(f"{rev}_") for name in files))
    assert not missing, f"CLAUDE.md names revision(s) {missing} with no file in migrations/versions"


def test_the_ci_job_names_it_pins_are_the_real_ones() -> None:
    """CLAUDE.md says these three are required status checks and must never be renamed.

    That claim is only worth anything while the names still match the workflow — a rename with
    the doc left behind is exactly the merge-gate break the section warns about.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    body = workflow.split("\njobs:\n", 1)[1]
    jobs = set(re.findall(r"^  ([a-z][a-z0-9_-]*):", body, re.MULTILINE))
    missing = sorted(job for job in CI_JOBS if job not in jobs)
    assert not missing, (
        f"CLAUDE.md pins the required checks {CI_JOBS}; `ci.yml` defines {sorted(jobs)} and is "
        f"missing {missing}. Renaming a job makes the ruleset wait forever."
    )


def test_the_environment_variables_it_documents_all_resolve() -> None:
    """A curated literal list — see ENV_VARS for why this arm is not regex-driven."""
    unresolved: list[str] = []
    for name, homes in ENV_VARS.items():
        if not any(name in (ROOT / home).read_text(encoding="utf-8") for home in homes):
            unresolved.append(f"{name} (looked in {list(homes)})")
    assert not unresolved, (
        f"{len(unresolved)} documented env var(s) appear in none of their declared homes: "
        f"{unresolved}. Either the variable was renamed or the home moved."
    )


def test_the_shell_owned_variable_is_still_not_read_by_this_repo() -> None:
    """`VITE_CLIMB_REMOTE_URL` belongs to `portfolio-shell`; here it is documentation only.

    If it ever appears in this repo's code, the CLAUDE.md paragraph describing it as the
    shell's setting is no longer the whole story and needs re-reading.
    """
    # `tests/` is excluded: this file names the variable in order to assert its absence.
    found = [
        path.relative_to(ROOT).as_posix()
        for root in ("server", "web/src", "migrations", "scripts")
        for path in (ROOT / root).rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".ts", ".tsx", ".sh", ".mjs"}
        and EXTERNAL_ENV_VAR in path.read_text(encoding="utf-8")
    ]
    assert not found, (
        f"{EXTERNAL_ENV_VAR} is now read by {found}, but CLAUDE.md describes it as a variable "
        f"set in the SHELL. Update that paragraph and move it into ENV_VARS."
    )
    assert EXTERNAL_ENV_VAR in CLAUDE_MD.read_text(encoding="utf-8"), (
        f"{EXTERNAL_ENV_VAR} is no longer documented, so this exemption guards nothing"
    )


# ---------------------------------------------------------------------------------
# Index integrity — both directions, and the highest-value arm here
# ---------------------------------------------------------------------------------
#
# The index is the file's only navigation, and it is anchored by HEADING TEXT rather than by
# line number precisely so that it survives edits. What it does not survive is a REWORDED
# heading, which leaves an entry quoting a section that no longer exists under that name — and
# a reader who cannot find the quoted heading concludes the rule was deleted.
#
# The reverse direction matters just as much: a section nothing points at is a section nobody
# reads, which is the same as not having written it.


def _index_quotes(lines: list[str]) -> list[str]:
    start, end = _index_bounds(lines)
    # Joined with spaces: several entries wrap across lines mid-quote.
    return re.findall(r'"([^"]+)"', " ".join(lines[start:end]))


def test_every_heading_the_index_quotes_resolves(lines: list[str]) -> None:
    """Forward direction. Every quoted string in the index must be a real heading.

    **No prose fallback.** An earlier version also accepted a quote matching verbatim prose
    elsewhere, because the index used to quote bullet openings too. The index is now PURE
    POINTERS, so that case is gone — and a loosening kept past its reason only hides the next
    reworded heading.
    """
    headings = [normalise(text) for _, text in _headings(lines)]
    quotes = _index_quotes(lines)
    assert len(quotes) > 40, f"only {len(quotes)} index quotes extracted — check the bounds"

    unresolved = [
        quote
        for quote in quotes
        if not any(heading.startswith(normalise(quote)) for heading in headings)
    ]
    formatted = "\n".join(f"  {quote!r}" for quote in unresolved)
    assert not unresolved, (
        f"{len(unresolved)} index entry(ies) quote text that is not a heading in this file. "
        f"Either the target was reworded and the index was left behind — re-quote it from the "
        f"section as it now reads — or the entry stopped being a pure pointer:\n{formatted}"
    )


def test_every_section_has_an_index_entry_pointing_into_it(lines: list[str]) -> None:
    """Reverse direction. A `##` section nothing points at is a section nobody finds.

    A section counts as reached when the index quotes it OR any heading nested under it — the
    index deliberately points at the specific rule rather than at the container.
    """
    headings = _headings(lines)
    start, end = _index_bounds(lines)
    outside = normalise(" ".join(lines[:start] + lines[end:]))
    normalised_quotes = [normalise(quote) for quote in _index_quotes(lines)]

    def reached(text: str) -> bool:
        target = normalise(text)
        return any(target.startswith(quote) for quote in normalised_quotes)

    orphans: list[str] = []
    for position, (level, text) in enumerate(headings):
        if level != 2:
            continue
        subtree = headings[position + 1 :]
        for offset, (nested_level, _) in enumerate(subtree):
            if nested_level <= 2:
                subtree = subtree[:offset]
                break
        if reached(text) or any(reached(nested) for _, nested in subtree):
            continue
        if text in UNINDEXED_SECTIONS:
            continue
        orphans.append(text)
    assert not orphans, (
        f"{len(orphans)} `##` section(s) have no index entry pointing anywhere inside them: "
        f"{orphans}. Add an index entry, or record the exemption with a reason in "
        f"UNINDEXED_SECTIONS."
    )
    assert outside, "the document outside the index is empty — the bounds are wrong"


def test_every_recorded_index_exemption_is_still_a_real_section(lines: list[str]) -> None:
    """The exemptions must not outlive the sections they exempt, or the arm silently narrows."""
    present = {text for level, text in _headings(lines) if level == 2}
    stale = sorted(set(UNINDEXED_SECTIONS) - present)
    assert not stale, (
        f"UNINDEXED_SECTIONS exempts {stale}, which no longer exist as `##` headings. Delete "
        f"the exemption — a dead exemption is how the reverse arm quietly stops covering things."
    )


# ---------------------------------------------------------------------------------
# Positive controls — every detector above must be able to see its own violation
# ---------------------------------------------------------------------------------


def test_the_token_regex_keeps_hyphens_dots_underscores_and_slashes() -> None:
    """The trap that produced nine phantom failures against correct documentation."""
    assert TOKEN.findall("`web/src/mf-contract.test.ts`") == ["web/src/mf-contract.test.ts"]
    assert TOKEN.findall("server/auth/*.py") == ["server/auth/*.py"]
    assert TOKEN.findall(".github/dependabot.yml") == [".github/dependabot.yml"]


def test_the_fence_stripper_hides_shell_snippets_from_the_path_arm() -> None:
    """Or `$VAR` and half-written paths from a bash block feed the filesystem check."""
    stripped = _unfenced(["prose `server/db.py`", "```bash", "cd `web/nope`", "```", "after"])
    assert stripped == ["prose `server/db.py`", "after"]


def test_the_heading_matcher_reads_every_level_the_file_uses() -> None:
    """`#####` is real in this file. A `#{2,4}` bound invented failures for the deepest ones."""
    levels = {level for level, _ in _headings(CLAUDE_MD.read_text(encoding="utf-8").splitlines())}
    assert 5 in levels, "expected `#####` headings — if they are gone, narrow HEADING deliberately"
    assert HEADING.match("###### deep") is not None


def test_the_index_forward_arm_would_notice_a_reworded_heading(lines: list[str]) -> None:
    """Positive control on the arm that matters most, using the real document.

    A detector that cannot see its own violation is worse than none: this quotes a heading that
    does not exist and asserts the resolution logic rejects it.
    """
    headings = [normalise(text) for _, text in _headings(lines)]
    invented = "Deployment traps that were renamed by a later PR"
    assert not any(heading.startswith(normalise(invented)) for heading in headings)
    # And the control's counterpart: a heading that IS real must resolve.
    assert any(heading.startswith(normalise("Deployment traps")) for heading in headings)


def test_the_normaliser_ignores_emphasis_and_dashes() -> None:
    """The index writes `**bold**` and em-dashes; the headings do not always agree."""
    assert normalise("⚠️ **The free-text** inventory — ELEVEN fields") == (
        "the free text inventory eleven fields"
    )
