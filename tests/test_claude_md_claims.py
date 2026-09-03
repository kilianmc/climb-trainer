"""Every mechanically checkable claim in `CLAUDE.md` must resolve against what it describes.
`CLAUDE.md` is the tripwire list every agent reads before touching this repo, and nothing else in
the gate reads it back. A renamed script, a moved file or a dropped env var leaves it wrong,
silently, and a wrong map is worse than no map.

**What it CANNOT catch:** a wrong *reason*, an obsolete threshold, or prose that is accurate and
no longer wise. It proves the paths, scripts, env vars, CI job names and README citations still
exist — never that the advice is right. The reasoning now lives in the frozen archive, which
nothing reads back at all: treat anything quoted from it as unverified until checked.
"""

import json
import re
import shutil
import subprocess
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
        "The tripwire exists to stop somebody recreating it."
    ),
}

# 19 paths are extracted today; the floor only has to be high enough to catch a broken regex.
PATH_FLOOR: Final = 15

# Curated LITERALS, not a regex: backticked `[A-Z_]{4,}` also yields `NULL`, `TIMESTAMPTZ` and
# `PUBLIC_ROUTE_IDS`, so the arm would measure markdown capitalisation, not configuration.
ENV_VARS: Final = {
    "DATABASE_URL": ("server/settings.py", ".env.example", ".github/workflows/ci.yml"),
    "DATABASE_URL_UNPOOLED": (
        "server/settings.py",
        ".env.example",
        ".github/workflows/migrate.yml",
    ),
    "CT_TEST_DATABASE_URL": ("package.json", ".env.example", "tests/conftest.py"),
    "AUTH_SECRET": ("server/settings.py", ".env.example"),
}
# The odd one out: it is the SHELL's variable, read by `portfolio-shell`, and this repo only
# documents the constraint on its value. Asserted ABSENT here, so it cannot be quietly satisfied.
EXTERNAL_ENV_VAR: Final = "VITE_CLIMB_REMOTE_URL"

CI_JOBS: Final = ("web", "server", "secrets")


# Reading the document.


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


def _scripts() -> dict[str, str]:
    merged: dict[str, str] = {}
    for manifest in (ROOT / "package.json", ROOT / "web" / "package.json"):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        merged.update({str(k): str(v) for k, v in data["scripts"].items()})
    return merged


# The arms.


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


GIT: Final = shutil.which("git")


def _is_gitignored(path: str) -> bool:
    """Ignored build artifacts are absent from a clean checkout and from CI, so presence on
    disk cannot be the only oracle. A typo is neither present nor ignored, so it still fails."""
    if GIT is None:  # pragma: no cover - git is present in CI and in any clone
        return False
    # Both forms: `.gitignore` uses directory-only patterns (`node_modules/`, `dist/`) and
    # check-ignore cannot tell an ABSENT path is a directory, so the bare form misses in CI.
    return any(
        subprocess.run(  # noqa: S603
            (GIT, "check-ignore", "-q", candidate), cwd=ROOT, check=False
        ).returncode
        == 0
        for candidate in (path, path.rstrip("/") + "/")
    )


def test_every_repo_rooted_path_it_names_resolves(lines: list[str]) -> None:
    """Backticked repo-rooted paths. A moved file leaves a tripwire pointing at a hole."""
    named: set[str] = set()
    for line in _unfenced(lines):
        for span in BACKTICKED.findall(line):
            for token in TOKEN.findall(span):
                token = token.rstrip(".,")
                if token.startswith(PATH_PREFIXES):
                    named.add(token)
    assert len(named) > PATH_FLOOR, (
        f"only {len(named)} paths extracted — the token regex is too narrow"
    )

    missing: list[str] = []
    for path in sorted(named):
        if path in ABSENT_PATHS:
            continue
        if "*" in path:
            if not list(ROOT.glob(path)):
                missing.append(path)
        elif not (ROOT / path).exists() and not _is_gitignored(path):
            missing.append(path)
    assert not missing, (
        f"CLAUDE.md names {len(missing)} path(s) that do not exist: {missing}. If the absence is "
        f"deliberate, say so in ABSENT_PATHS with a reason; otherwise fix the path."
    )


def test_every_deliberately_absent_path_is_still_absent() -> None:
    """The other direction. A recreated file makes its "this is GONE" tripwire a lie."""
    resurrected = [path for path in ABSENT_PATHS if (ROOT / path).exists()]
    assert not resurrected, (
        f"{resurrected} exist(s) again, but CLAUDE.md documents them as gone. Either the "
        f"tripwire is stale or somebody recreated exactly the file it warns against."
    )


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


def test_the_environment_variables_it_documents_all_resolve(source: str) -> None:
    """A curated literal list — see ENV_VARS for why this arm is not regex-driven."""
    unnamed = sorted(name for name in ENV_VARS if name not in source)
    assert not unnamed, f"ENV_VARS lists {unnamed}, which CLAUDE.md no longer names. Drop them."
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

    If it ever appears in this repo's code, the CLAUDE.md tripwire describing it as the
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
        f"set in the SHELL. Update that tripwire and move it into ENV_VARS."
    )
    assert EXTERNAL_ENV_VAR in CLAUDE_MD.read_text(encoding="utf-8"), (
        f"{EXTERNAL_ENV_VAR} is no longer documented, so this exemption guards nothing"
    )


# Pointers into README fail the same way a path does, and were invisible until PR #72: the trim
# to 46 lines left three sentences citing sections README no longer has.


def test_every_readme_section_this_file_cites_resolves(lines: list[str]) -> None:
    """Every italicised section name next to a `README.md` mention must be a README heading."""
    readme_headings = {
        normalise(text) for _, text in _headings((ROOT / "README.md").read_text().splitlines())
    }
    text = "\n".join(lines)
    cited: list[str] = []
    dangling: list[str] = []
    for mention in re.finditer(r"README\.md", text):
        # Bold stripped first, or `**Module docstrings**` reads as one italic run.
        window = text[mention.end() : mention.end() + 200].replace("**", "")
        for match in re.finditer(r"\*([^*\n]+)\*", window):
            name = match.group(1).strip()
            cited.append(name)
            if normalise(name) not in readme_headings:
                dangling.append(name)
    assert cited, (
        "CLAUDE.md cites no README section at all, so this arm is green over an empty set. "
        "Either name the pitch sections next to the `README.md` mention, or delete this arm."
    )
    assert not dangling, (
        f"This file cites README.md sections that do not exist: {sorted(set(dangling))}. "
        f"README.md has only {sorted(readme_headings)} and is deliberately just the pitch. "
        "Either the content moved here and the pointer should be replaced by the content, or "
        "the citation is stale — see 'Where things live'."
    )


# Positive controls — every detector above must be able to see its own violation.


def test_the_token_regex_keeps_hyphens_dots_underscores_and_slashes() -> None:
    """The trap that produced nine phantom failures against correct documentation."""
    assert TOKEN.findall("`web/src/mf-contract.test.ts`") == ["web/src/mf-contract.test.ts"]
    assert TOKEN.findall("server/auth/*.py") == ["server/auth/*.py"]
    assert TOKEN.findall(".github/dependabot.yml") == [".github/dependabot.yml"]


def test_the_fence_stripper_hides_shell_snippets_from_the_path_arm() -> None:
    """Or `$VAR` and half-written paths from a bash block feed the filesystem check."""
    stripped = _unfenced(["prose `server/db.py`", "```bash", "cd `web/nope`", "```", "after"])
    assert stripped == ["prose `server/db.py`", "after"]


def test_the_normaliser_ignores_emphasis_and_dashes() -> None:
    """The citations write `**bold**` and em-dashes; the headings do not always agree."""
    assert normalise("⚠️ **The free-text** inventory — ELEVEN fields") == (
        "the free text inventory eleven fields"
    )
