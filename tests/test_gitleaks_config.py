""".gitleaks.toml must EXTEND the default ruleset, never replace it.
One line — `useDefault = true` under `[extend]` — is the difference between "adds one allowlist"
and "deletes every secret-detection rule gitleaks has", and the `secrets` job goes green either
way. That fail-open shape is why this is a test and not a comment. Nothing here restates the
allowlist or its regex; it asserts the two properties whose absence is silent — the ruleset is
extended, and the allowlist is scoped by line CONTENT rather than by path.
⚠️ **`paths` must stay ABSENT.** `gitleaks-action@v3` runs gitleaks 8.24.3, whose allowlist struct
has no condition field and therefore ORs its criteria — so a `paths` entry would allowlist the
whole of the machine-generated `web/src/api/schema.ts` for every rule, and a real credential
committed there would be reported by nothing. DB-free; the scanner is not a project dependency, so
what can be checked here is the config it will read.
"""

import re
import tomllib

from server.settings import ROOT

CONFIG = ROOT / ".gitleaks.toml"


def _config() -> dict[str, object]:
    assert CONFIG.is_file(), f"{CONFIG} is missing — the secrets job needs it, see its header"
    with CONFIG.open("rb") as handle:
        return tomllib.load(handle)


def test_the_default_ruleset_is_EXTENDED_not_replaced() -> None:
    """The whole point. Without this, a green `secrets` job means nothing at all."""
    extend = _config().get("extend")
    assert isinstance(extend, dict), "[extend] is missing from .gitleaks.toml"
    assert extend.get("useDefault") is True, (
        "`useDefault = true` is missing. A gitleaks config without it REPLACES the default "
        "ruleset, so every built-in rule is gone and the scanner passes everything."
    )


def test_the_allowlist_is_scoped_by_line_content_and_not_by_path() -> None:
    """`paths` is a fail-open on the gitleaks version CI runs. See the module docstring."""
    allowlist = _config().get("allowlist")
    assert isinstance(allowlist, dict), "[allowlist] is missing from .gitleaks.toml"

    assert "paths" not in allowlist, (
        "`paths` allowlists an entire FILE on gitleaks 8.24.3 (its allowlist criteria are "
        "OR'd, with no condition field), which would hide a real credential committed into "
        "the generated API types. Scope by line content instead."
    )
    assert allowlist.get("regexTarget") == "line", (
        "`regexTarget` must be `line`: the default target is the matched secret, so a regex "
        "on the digest alone would allowlist any 64-hex secret anywhere in the repo."
    )

    regexes = allowlist.get("regexes")
    assert isinstance(regexes, list) and regexes, "[allowlist] declares no regexes"


def test_the_allowlist_matches_the_generated_header_and_nothing_looser() -> None:
    """Positive AND negative control on the regex itself, using real header lines.

    A detector that cannot see its own subject is worse than none — and an allowlist that
    matches more than its subject is worse still, so both directions are asserted here.
    """
    allowlist = _config()["allowlist"]
    assert isinstance(allowlist, dict)
    regexes = allowlist["regexes"]
    assert isinstance(regexes, list)
    pattern = re.compile(str(regexes[0]))
    digest = "e58a5e17eee54e12fb58cf2ce94a99bd8c5249ff29b045ce0c800e5edbd0380e"

    assert pattern.search(f" * openapi-sha256: {digest}")
    assert pattern.search(f" * types-sha256: {digest}")

    # The lines it must NOT cover: anything that is not one of those two headers.
    assert not pattern.search(f" * some-token: {digest}")
    assert not pattern.search(f'const apiKey = "{digest}";')
    assert not pattern.search(" * aws_access_key_id = AKIA" + "Q7WZXY3M4TNPRS6K")


def test_the_generated_header_still_carries_both_digests() -> None:
    """The allowlist and the file it exempts have to keep describing each other.

    If the header format is ever changed to appease a scanner — a shorter digest, a split
    line, a dropped label — this fails, and the codegen freshness guard it protects
    (`tests/test_vocabulary_contract.py`) is the thing that would quietly stop being
    checkable.
    """
    header = (ROOT / "web" / "src" / "api" / "schema.ts").read_text(encoding="utf-8")[:2000]
    allowlist = _config()["allowlist"]
    assert isinstance(allowlist, dict)
    regexes = allowlist["regexes"]
    assert isinstance(regexes, list)
    pattern = re.compile(str(regexes[0]), re.MULTILINE)

    matched = pattern.findall(header)
    assert len(matched) == 2, (
        f"expected the generated header to carry both `openapi-sha256` and `types-sha256` "
        f"on their own lines; the allowlist regex matched {len(matched)} line(s)"
    )
