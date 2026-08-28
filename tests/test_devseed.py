"""`server/devseed.py` must never run where its output, or its rows, would not belong.
The module prints ten working passwords to stdout and writes ten name-derived accounts to whatever
`DATABASE_URL` points at. Both are "must never happen" invariants no feature test would exercise.
⚠️ **Every case passes an explicit mapping** rather than monkeypatching the real environment (one
exception only *sets* a variable). An earlier version built its negative control by deleting `CI`,
`GITHUB_ACTIONS`, `VERCEL` and `VERCEL_ENV` — a live grenade the moment someone extended it to call
`main()` inside CI, printing ten passwords into a public Actions log. **A test must not disarm the
guard it is testing.** No database: the guards fire before anything connects, and a Postgres
fixture would confine this to CI, the one place it must stop the module dead.
"""

from typing import cast

import pytest
from sqlalchemy.orm import Session

from server import devseed
from server.auth.routes import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

# Enough to satisfy the opt-in, so a refusal in these cases can only come from the marker.
_OPTED_IN = {devseed.OPT_IN_ENV: "1"}


@pytest.mark.parametrize("marker", devseed._NON_LOCAL_ENV_VARS)
@pytest.mark.parametrize("value", ["true", "1", ""])
def test_a_ci_or_vercel_marker_refuses_even_when_its_value_is_empty(
    marker: str, value: str
) -> None:
    """Presence, not truthiness. `CI=` is falsy and is still CI.

    This is the difference between `name in environ` and `environ.get(name)`, and it is the
    whole reason the parametrisation includes the empty string.
    """
    with pytest.raises(devseed.DevSeedRefusedError, match=marker):
        devseed.refuse_unless_local_development({**_OPTED_IN, marker: value})


def test_the_opt_in_is_required_even_on_a_clean_machine() -> None:
    """An absent CI marker is not the claim "this is a throwaway database".

    `.env` is loaded on import and `server/admin.py` is designed to be pointed at production
    from a developer's terminal, so without this the same shell would seed ten name-derived
    accounts into production and pass every other check.
    """
    with pytest.raises(devseed.DevSeedRefusedError, match=devseed.OPT_IN_ENV):
        devseed.refuse_unless_local_development({"PATH": "/usr/bin"})


def test_it_permits_an_opted_in_local_environment() -> None:
    """The negative control. Without it, a guard that always raised would pass everything above.

    Note what it does NOT do: unset anything. The mapping is local to this call.
    """
    devseed.refuse_unless_local_development({**_OPTED_IN, "PATH": "/usr/bin"})


def test_the_default_argument_really_reads_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring, proved without ever unsetting a marker.

    Only ADDS variables, so it behaves the same on a laptop and inside CI (where the message
    names the CI markers too). A `refuse_unless_local_development()` that defaulted to an empty
    mapping would refuse for the opt-in instead, and `match` would fail.
    """
    monkeypatch.setenv(devseed.OPT_IN_ENV, "1")
    monkeypatch.setenv("VERCEL_ENV", "production")

    with pytest.raises(devseed.DevSeedRefusedError, match="VERCEL_ENV"):
        devseed.refuse_unless_local_development()


def test_seed_dev_users_is_guarded_too_and_not_only_main() -> None:
    """A public function whose only guard is in `main()` is one `python -c` from being skipped.

    The refusal runs before the session is touched, so the null session below is never
    dereferenced — and if the guard is ever removed from this function, that is exactly what
    makes the test fail rather than pass quietly.
    """
    with pytest.raises(devseed.DevSeedRefusedError):
        devseed.seed_dev_users(cast(Session, None))


def test_target_host_never_returns_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """The confirmation prompt prints this, so it is the one string that must stay clean.

    A public repository plus a terminal transcript pasted into an issue is the whole threat.
    """
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://neondb_owner:sup3r-s3cret@ep-x-pooler.example.tech/neondb"
    )

    host = devseed.target_host()

    assert host == "ep-x-pooler.example.tech"
    assert "sup3r-s3cret" not in host
    assert "neondb_owner" not in host


def test_every_generated_password_satisfies_the_app_own_policy() -> None:
    """`<name>` + digits + one special character, and never below the registration floor.

    A shorter one would be an account `POST /api/auth/register` could not have created and
    no reset could restore — it would work until the first time anyone tried to change it.
    """
    for name in devseed.NAMES:
        password = devseed.password_for(name)
        assert password.startswith(name)
        assert MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH, password
        assert password[-1] in devseed._SPECIALS
        assert password[len(name) : -1].isdigit(), password

    # Randomised per user, so two runs do not produce the same credential.
    assert devseed.password_for("alex") != devseed.password_for("alex")
