"""Ten local test accounts. **DEVELOPMENT ONLY — no workflow invokes this module.**

Not in `server/seed.py` because that module is the *single* seed CI, local development **and
production** all call, so ten accounts whose passwords start with the account's own first name
would land on climb.kilianmc.com.

Three guards, because they answer three different questions. (1) *Am I in CI or a deployment?*
— `CI`, `GITHUB_ACTIONS`, `VERCEL`, `VERCEL_ENV` checked for **presence**, not truthiness
(`CI=` is still CI), because this repo's Actions logs are public and `main()` prints ten
working passwords. (2) *Did anyone ask?* — `CLIMB_DEV_SEED` must be set; guard 1 cannot answer
it, and the gap was real, since `.env` is loaded on import and `server/admin.py` is *designed*
to run against production from a developer's terminal. (3) *Which database?* — `main()` prints
the target **host** (never the URL, user or password) and will not write until it is typed
back. Guards 1 and 2 sit on `seed_dev_users()` too: a public function is one `python -c` away.
**`CLIMB_DEV_SEED` is deliberately NOT in `.env.example`** — in `.env` it is standing
permission. Redirection is the one thing no guard can stop; don't.

Passwords are `<name>` + digits + one special character, never shorter than
`MIN_PASSWORD_LENGTH`, which is **imported** from `server/auth/routes.py` rather than restated:
a seeded password below the floor makes an account `register` and every future reset would
refuse. Digits come from `secrets` and are re-drawn per run, so a re-run rotates all ten. The
print is the only copy of the plaintext — `server/admin.py set-password` chooses a specific one.
"""

import os
import secrets
import string
from collections.abc import Mapping
from typing import Final

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from server.auth.passwords import hash_password
from server.auth.routes import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from server.db import session_scope, target_host_and_database
from server.models import AppUser

# Common first names, lowercased: each one is both the local part of the address and the
# leading part of the password, which is the whole point — they are meant to be typeable
# from memory while testing.
NAMES: Final = (
    "alex",
    "sam",
    "jordan",
    "riley",
    "casey",
    "morgan",
    "taylor",
    "jamie",
    "quinn",
    "avery",
)

# `.example` is reserved by RFC 2606 and can never be registered, so none of these can
# reach a real inbox. It is also what `server/seed.py` uses for the demo account —
# `email-validator` rejects `.invalid` outright, which would make these accounts
# unloggable through `/api/auth/login`. The `dev.` subdomain keeps them visibly distinct
# from `demo@climb-trainer.example`.
EMAIL_DOMAIN: Final = "dev.climb-trainer.example"

# One character from here per password. Kept to punctuation that needs no shell quoting,
# because these get pasted into curl commands.
_SPECIALS: Final = "!#%*+-?@"

# A floor on the random part, so a long first name still gets real entropy rather than
# whatever is left over after the length padding.
_MIN_DIGITS: Final = 4

# Any of these means the process is not a developer's terminal. `CI` is the conventional
# one and GitHub Actions sets both it and `GITHUB_ACTIONS`; the two `VERCEL*` variables
# cover a build or a function invocation.
_NON_LOCAL_ENV_VARS: Final = ("CI", "GITHUB_ACTIONS", "VERCEL", "VERCEL_ENV")

# The deliberate opt-in. Guard 2 in the module docstring: "not CI" is not the same claim as
# "this is a throwaway database", and only a human can make the second one.
OPT_IN_ENV: Final = "CLIMB_DEV_SEED"


class DevSeedRefusedError(RuntimeError):
    """This module was asked to run somewhere its output, or its rows, would not belong."""


def refuse_unless_local_development(environ: Mapping[str, str] | None = None) -> None:
    """Raise unless this is a developer's machine **and** the opt-in is set.

    `environ` exists so the tests can exercise every combination without ever unsetting the
    variables that protect the process they are running in. It defaults to the real one.

    Presence, not truthiness: `name in environ`, never `environ.get(name)`. `CI=` is an empty
    string, is falsy, and is still CI — a guard that can be talked out of refusing by an empty
    value is not a guard.
    """
    env = os.environ if environ is None else environ

    detected = sorted(name for name in _NON_LOCAL_ENV_VARS if name in env)
    if detected:
        raise DevSeedRefusedError(
            f"refusing to run: {', '.join(detected)} is set, so this is CI or a Vercel "
            f"deployment. This module prints ten working passwords to stdout and this "
            f"repository's Actions logs are public. Reference data for CI and production "
            f"is `python -m server.seed`, which deliberately seeds no such accounts."
        )

    if OPT_IN_ENV not in env:
        raise DevSeedRefusedError(
            f"refusing to run: set {OPT_IN_ENV}=1 to confirm the configured database is a "
            f"throwaway development one. `.env` is loaded on import, so a shell that can "
            f"reach production reaches it from here too — and ten accounts whose passwords "
            f"start with the account's own first name must never land there."
        )


def target_host() -> str:
    """The **host** of `DATABASE_URL` and nothing else from it.

    Never the URL, the user or the password: this repository is public and so is a terminal
    transcript pasted into an issue. `server/admin.py` confirms against the same helper.
    """
    return target_host_and_database()[0]


def _confirm_target() -> None:
    """Make the operator name the database. A y/N prompt is muscle memory; typing is not."""
    host = target_host()
    print(f"About to create 10 accounts with printed passwords in the database at: {host}")
    try:
        answer = input(f"Type the host to confirm ({host}): ")
    except EOFError:
        raise DevSeedRefusedError(
            "no terminal to confirm on, so nothing was seeded. This module is interactive on "
            "purpose — see guard 3 in its docstring."
        ) from None
    if answer.strip() != host:
        raise DevSeedRefusedError(f"that is not {host}; nothing was seeded")


def password_for(name: str) -> str:
    """`<name>` + digits + one special character, padded to at least `MIN_PASSWORD_LENGTH`."""
    digit_count = max(_MIN_DIGITS, MIN_PASSWORD_LENGTH - len(name) - 1)
    digits = "".join(secrets.choice(string.digits) for _ in range(digit_count))
    password = f"{name}{digits}{secrets.choice(_SPECIALS)}"
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:  # pragma: no cover
        raise DevSeedRefusedError(
            f"generated a {len(password)}-character password for {name!r}, outside the "
            f"app's own {MIN_PASSWORD_LENGTH}..{MAX_PASSWORD_LENGTH} policy — the account "
            f"would exist but could never be re-created or reset through the API."
        )
    return password


def seed_dev_users(session: Session) -> list[tuple[str, str]]:
    """Upsert the ten accounts with freshly generated passwords. Does NOT commit.

    Returns `(email, plaintext password)` pairs, in `NAMES` order. The plaintext is not
    stored anywhere — argon2id is one way — so this return value is the only copy.

    Idempotent by upsert on the email, and it **replaces** `password_hash` every run: the
    alternative (skip if present) would print passwords that no longer work as soon as
    anyone had used `set-password`. `is_demo` is written explicitly as `False` so one of
    these can never be mistaken for the demo account.

    The environment guards run here too, not only in `main()`: this function is public, and a
    guard that only covers the module's `__main__` path is one `python -c` from being skipped.
    """
    refuse_unless_local_development()

    credentials: list[tuple[str, str]] = []
    for name in NAMES:
        email = f"{name}@{EMAIL_DOMAIN}"
        password = password_for(name)
        statement = insert(AppUser).values(
            email=email, password_hash=hash_password(password), is_demo=False
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[AppUser.email],
                set_={"password_hash": statement.excluded.password_hash, "is_demo": False},
            )
        )
        credentials.append((email, password))
    session.flush()
    return credentials


def main() -> None:
    """`uv run python -m server.devseed` — local only, and it says so if it is not.

    Prints the credentials **once**, to the terminal. There is no `--quiet`, no log file
    and nothing written to disk: the passwords are unrecoverable after this process exits,
    which is the same property the invite codes have.
    """
    refuse_unless_local_development()
    _confirm_target()
    with session_scope() as session:
        credentials = seed_dev_users(session)

    print(f"seeded {len(credentials)} development accounts (passwords shown ONCE):")
    for email, password in credentials:
        print(f"  {email}  {password}")
    print(
        "Re-run this module to rotate all ten, or `python -m server.admin set-password` "
        "to choose one."
    )


if __name__ == "__main__":
    main()
