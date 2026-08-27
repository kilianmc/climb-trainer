"""The two "which database am I about to touch?" guards, and the credential rule.
DB-free — pure functions — so they run in the local gate, which matters because the mistakes they
catch are made at a terminal.
⚠️ **The traceback tests are the important ones.** A guard that refuses correctly and leaks the
password while doing it turns a near-miss into a disclosure. The first version took the connection
URL as a **parameter**; pytest renders every frame's arguments and the fixture is session-scoped,
so one failing run printed the production URL **51 times** while the guard's own docstring said
"never the URL". The message was clean; the traceback was not. So both guards take a **host**, and
these tests assert no frame on the raised path holds the credential, locals included —
`--showlocals` is one flag away. Same rule CLAUDE.md draws from `alembic current --verbose`: audit
what a tool prints at its chosen verbosity.
"""

import pytest

from server.db import (
    LOCAL_DB_HOSTS,
    REMOTE_MIGRATION_ENV,
    RemoteDatabaseRefused,
    host_of,
    is_local_host,
    require_local_host,
    require_migration_host,
)

# Obviously fake, and constructed by repetition so it has almost no entropy — gitleaks
# scans this repo's full history and a random-looking string next to a URL is exactly what
# its generic rule looks for. Same convention as `_FAKE_AUTH_SECRET` in conftest.
_FAKE_PASSWORD = "not-a-real-password-" * 2  # noqa: S105
_REMOTE_HOST = "ep-quiet-mountain-12345-pooler.eu-central-1.aws.neon.tech"
_FAKE_REMOTE_URL = f"postgresql://neondb_owner:{_FAKE_PASSWORD}@{_REMOTE_HOST}/neondb"

# Every one of these has to be refused. The first three are the near-misses an
# `endswith`/substring check would wave through; the last two resolve to loopback but are
# not spellings anything here produces, and `None` is the unix-socket case that must fail
# CLOSED rather than read as "no host, therefore local".
NON_LOCAL_HOSTS = (
    _REMOTE_HOST,
    "localhost.evil.com",
    "notlocalhost",
    "127.0.0.1.nip.io",
    "2130706433",
    "::ffff:127.0.0.1",
    None,
)


def test_the_allowlist_is_what_it_claims_to_be() -> None:
    """Non-vacuity: an empty or over-broad allowlist must not read as compliance."""
    assert LOCAL_DB_HOSTS == {"localhost", "127.0.0.1", "::1", "postgres", "db"}
    assert all(is_local_host(host) for host in LOCAL_DB_HOSTS)


@pytest.mark.parametrize("host", NON_LOCAL_HOSTS)
def test_non_local_hosts_are_refused(host: str | None) -> None:
    assert not is_local_host(host)
    with pytest.raises(RemoteDatabaseRefused):
        require_local_host(host, operation="test", remedy="x")


def test_host_of_extracts_the_host_and_nothing_else() -> None:
    assert host_of(_FAKE_REMOTE_URL) == _REMOTE_HOST
    # A unix-socket URL has no host at all, which is the `None` that must fail closed.
    assert host_of("postgresql:///climb_trainer") is None


def _no_credential_anywhere(exc_info: pytest.ExceptionInfo[BaseException]) -> None:
    """Assert the password appears in no frame of the raised traceback, nor the message.

    Locals as well as arguments: `pytest --showlocals` renders them, and a guard that is
    only safe at the default verbosity is a guard that leaks the first time somebody
    debugs a failure.
    """
    assert _FAKE_PASSWORD not in str(exc_info.value)
    for entry in exc_info.traceback:
        rendered = repr(entry.frame.f_locals)
        assert _FAKE_PASSWORD not in rendered, (
            f"the password reached the locals of {entry.name} in {entry.path}. Pass the "
            f"HOST across this boundary, never the URL — see server/db.py::host_of."
        )


def test_the_test_suite_guard_leaks_no_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REMOTE_MIGRATION_ENV, raising=False)
    with pytest.raises(RemoteDatabaseRefused) as exc_info:
        require_local_host(host_of(_FAKE_REMOTE_URL), operation="run the test suite", remedy="x")
    _no_credential_anywhere(exc_info)
    # And it does name the host, which is the whole point of raising at all.
    assert _REMOTE_HOST in str(exc_info.value)


def test_the_migration_guard_leaks_no_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REMOTE_MIGRATION_ENV, raising=False)
    with pytest.raises(RemoteDatabaseRefused) as exc_info:
        require_migration_host(host_of(_FAKE_REMOTE_URL))
    _no_credential_anywhere(exc_info)
    assert _REMOTE_HOST in str(exc_info.value)
    # The message has to point at the sanctioned path, or it just looks like a bug.
    assert "migrate.yml" in str(exc_info.value)


def test_the_credential_detector_can_see_a_leak() -> None:
    """⚠️ Positive control. A detector that cannot see its own violation is worse than none.

    This is the pre-2026-08-21 signature, reconstructed: a function taking the URL. If
    `_no_credential_anywhere` ever stops looking at frame locals, this test goes green and
    the two above become decoration.
    """

    def old_style_guard(url: str) -> None:
        raise RemoteDatabaseRefused("refusing")

    with pytest.raises(RemoteDatabaseRefused) as exc_info:
        old_style_guard(_FAKE_REMOTE_URL)
    with pytest.raises(AssertionError, match="reached the locals of"):
        _no_credential_anywhere(exc_info)


def test_a_local_host_is_allowed_by_both_guards() -> None:
    """The other half: a guard that refuses everything is not a guard, it is an outage."""
    require_local_host("localhost", operation="test", remedy="x")
    require_migration_host("localhost")


def test_the_migration_guard_has_an_opt_in_and_the_suite_guard_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`migrate.yml` exists to migrate production; the test suite never should.

    A flat allowlist on Alembic would have broken the sanctioned path and left the
    unsanctioned one working — which is the asymmetry this pair of guards removes.
    """
    monkeypatch.setenv(REMOTE_MIGRATION_ENV, "1")
    require_migration_host(_REMOTE_HOST)
    with pytest.raises(RemoteDatabaseRefused):
        require_local_host(_REMOTE_HOST, operation="run the test suite", remedy="x")


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "TRUE"])
def test_only_the_exact_opt_in_value_counts(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`== "1"`, not truthiness. `CT_ALLOW_REMOTE_MIGRATION=0` must not open the door."""
    monkeypatch.setenv(REMOTE_MIGRATION_ENV, value)
    with pytest.raises(RemoteDatabaseRefused):
        require_migration_host(_REMOTE_HOST)


def test_the_workflow_sets_the_opt_in_and_nothing_else_does() -> None:
    """The variable is only legitimate in one file. Anywhere else is a bypass.

    `migrate.yml` is read from the DEFAULT branch for `workflow_dispatch` registration, so
    a change to it on `dev` alone is inert until promotion — but the env block is read from
    the checked-out ref, so this assertion is about the file, not about registration.
    """
    from server.settings import ROOT

    workflow = (ROOT / ".github" / "workflows" / "migrate.yml").read_text(encoding="utf-8")
    assert f"{REMOTE_MIGRATION_ENV}: " in workflow, (
        f"{REMOTE_MIGRATION_ENV} is not set in migrate.yml — the sanctioned migration "
        f"path would be refused by its own guard."
    )
    others = [
        path
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
        if path.name != "migrate.yml" and REMOTE_MIGRATION_ENV in path.read_text(encoding="utf-8")
    ]
    assert not others, f"{REMOTE_MIGRATION_ENV} must be set by migrate.yml alone, not {others}"
