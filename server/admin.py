"""Operator CLI for the two things that have no editable cell in the database.

    uv run python -m server.admin create-invite --label "Bob, from the gym"
    uv run python -m server.admin set-password --email bob@example.com

Invoked the same way as `python -m server.seed`, and like it, run **out of band** against
production: neither subcommand belongs in a workflow, and nothing here is idempotent in the
way a seed is.

## Why a CLI is the only way to do either

- `app_user.password_hash` is **argon2id**. There is no plaintext column, so there is no
  cell in the Neon console a password can be typed into, and no SQL statement that could
  set one. Hashing has to happen in a process that has this repository's parameters
  (`server/auth/passwords.py`) — a hash produced with anything else would verify or not
  depending on the library's defaults.
- `invite.code_hash` is **sha256 of a code that only exists in the generating process**.
  Inserting a row by hand would mean inventing a code, hashing it somewhere, and having
  the plaintext pass through that somewhere on the way.

The reverse operations need no secret and therefore no command: revoking an invite is
`UPDATE invite SET revoked_at = now() WHERE label = '...'`, and listing them is a SELECT
that exposes nothing (the codes are hashes). Do not add subcommands for those.

## What this module must never print

**No connection string, ever** — not masked, not a prefix. The repository is public and
so is the terminal scrollback that ends up pasted into an issue. The one secret this module
*does* print is a fresh invite code, once, because that is the only moment it exists.

**The one deliberate exception is the confirmation below: the target host and database
NAME.** That is not a relaxation of the rule — it is the same redaction `server/devseed.py`
does, through the same helper (`server/db.py::target_host_and_database`), and it exists
because the operator cannot confirm a target they are not shown. Never widen it to the
user, the password, the query string or the full URL.

Passwords are read with `getpass` from the terminal, never from `argv`: an argument lands
in shell history, in `ps` output, and in any script that wrapped the command.

## Which database? — the guard this module used to be missing

Both subcommands are documented as run **against production from a developer's terminal**,
and `server/settings.py` loads `.env` on import. So the shell that reaches production
reaches it by default, and a `set-password` meant for a local account silently rewrote a
real one. `server/devseed.py` had target confirmation for exactly this reason and this
module did not, which was the asymmetry: devseed protected the throwaway database while
`admin.py` pointed at the real one unguarded.

So both subcommands print the target and will not act until the operator types the host
back. `--yes` skips the prompt for scripting, and is the only way to skip it — there is no
environment variable, because a variable in `.env` becomes standing permission (the same
reasoning that keeps `CLIMB_DEV_SEED` out of `.env.example`).
"""

import argparse
import getpass
from datetime import timedelta
from typing import Final

from sqlalchemy import select

from server.auth import invites
from server.auth.passwords import hash_password
from server.auth.routes import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, normalise_email
from server.db import session_scope, target_host_and_database
from server.models import AppUser

# A sanity ceiling, not a policy: `max_uses` is a SmallInteger and a per-person invite is
# normally 1. Anything large enough to be interesting is a shared secret, which is exactly
# what issue #35 rejected.
_MAX_USES_CEILING: Final = 20

# Long enough for any real invitation, and short enough that a typo cannot mint something
# effectively permanent by accident.
_MAX_EXPIRY_DAYS: Final = 365


class AdminCommandError(RuntimeError):
    """A refusal the operator can act on. Printed as a message, not a traceback."""


def _bounded_int(value: str, *, minimum: int, maximum: int, what: str) -> int:
    """`argparse` type for a closed integer range — the CLI's edge validation.

    The same rule as the API's Pydantic models: bound the input where it enters, so nothing
    downstream has to wonder. The two CHECK constraints on `invite` are the database's own
    copy of the `max_uses` half.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{what} must be a whole number") from None
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{what} must be between {minimum} and {maximum}")
    return parsed


def _max_uses(value: str) -> int:
    return _bounded_int(value, minimum=1, maximum=_MAX_USES_CEILING, what="--max-uses")


def _expiry_days(value: str) -> int:
    return _bounded_int(value, minimum=1, maximum=_MAX_EXPIRY_DAYS, what="--expires-in-days")


def _label(value: str) -> str:
    label = value.strip()
    if not label:
        raise argparse.ArgumentTypeError("--label must not be empty")
    if len(label) > invites.MAX_LABEL_LENGTH:
        raise argparse.ArgumentTypeError(
            f"--label must be at most {invites.MAX_LABEL_LENGTH} characters"
        )
    return label


def _confirm_target(what: str, *, assume_yes: bool) -> None:
    """Show the target database and make the operator name it. Same shape as `devseed`.

    A y/N prompt is muscle memory; typing the host is not. `--yes` is the only bypass, so a
    scripted run is an explicit decision at the call site rather than an ambient setting.
    """
    host, database = target_host_and_database()
    print(f"About to {what} in the database at: {host} (database {database})")
    if assume_yes:
        print("--yes given, proceeding without confirmation.")
        return
    try:
        answer = input(f"Type the host to confirm ({host}): ")
    except EOFError:
        raise AdminCommandError(
            "no terminal to confirm on, so nothing was changed. Pass --yes to run this "
            "non-interactively."
        ) from None
    if answer.strip() != host:
        raise AdminCommandError(f"that is not {host}; nothing was changed")


def create_invite(
    label: str, max_uses: int, expires_in_days: int | None, *, assume_yes: bool = False
) -> None:
    """Mint one invite and print its code — the only moment the plaintext exists."""
    _confirm_target(f"mint an invite for {label!r}", assume_yes=assume_yes)
    expires_in = None if expires_in_days is None else timedelta(days=expires_in_days)
    with session_scope() as session:
        issued = invites.create(session, label=label, max_uses=max_uses, expires_in=expires_in)

    expiry = (
        "never expires"
        if issued.expires_at is None
        else f"expires {issued.expires_at:%Y-%m-%d %H:%M %Z}"
    )
    print(f"invite {issued.invite_id} for {issued.label!r} — {issued.max_uses} use(s), {expiry}")
    print(f"  code: {issued.code}")
    print(
        "This code is stored only as a sha256 digest and cannot be recovered. Send it to "
        "one person; to withdraw it later, stamp revoked_at on that invite row in the Neon "
        "console."
    )


def _prompt_new_password() -> str:
    """Read and confirm a password from the terminal, and hold it to the app's own policy.

    The bounds are `server/auth/routes.py`'s, imported rather than restated: a password
    outside them would leave an account that works until the first time anyone tried to
    change it through the API.
    """
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat password: "):
        raise AdminCommandError("the two entries did not match; nothing was changed")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise AdminCommandError(
            f"the password must be {MIN_PASSWORD_LENGTH}..{MAX_PASSWORD_LENGTH} characters "
            f"— the app's own policy, so a shorter one would create an account that "
            f"`/api/auth/register` and every future reset would reject."
        )
    return password


def set_password(email: str, *, assume_yes: bool = False) -> None:
    """Replace one account's `password_hash`.

    The prompt and the argon2 run both happen **before** the session is opened, so no
    transaction is held open while a human types and Neon is not kept awake for it. The
    cost is that a mistyped address is only reported afterwards.

    The target confirmation comes **first**, before the password prompt: a wrong database
    should cost nothing to abandon, and being asked to invent a password before being told
    where it is going is how the wrong one gets set.
    """
    normalised = normalise_email(email)
    _confirm_target(f"set the password for {normalised!r}", assume_yes=assume_yes)
    password_hash = hash_password(_prompt_new_password())

    with session_scope() as session:
        user = session.scalars(select(AppUser).where(AppUser.email == normalised)).one_or_none()
        if user is None:
            raise AdminCommandError(f"no account with email {normalised!r}")
        if user.is_demo:
            # A NULL `password_hash` is what makes the demo account structurally unloggable
            # through `/api/auth/login`. Setting one here would break that until the next
            # `python -m server.seed` quietly took it away again.
            raise AdminCommandError(
                f"{normalised!r} is the demo account: its password_hash must stay NULL, "
                f"which is what makes it unloggable through /api/auth/login."
            )
        user.password_hash = password_hash

    print(f"password updated for {normalised}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.admin",
        description="climb-trainer operator commands. Run out of band, never in a workflow.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    invite = subcommands.add_parser(
        "create-invite", help="mint one registration invite and print its code once"
    )
    invite.add_argument("--label", type=_label, required=True, help="who it is for")
    invite.add_argument("--max-uses", type=_max_uses, default=1)
    invite.add_argument(
        "--expires-in-days", type=_expiry_days, default=None, help="omit for no expiry"
    )

    password = subcommands.add_parser(
        "set-password", help="set an existing account's password (prompts; never takes it in argv)"
    )
    password.add_argument("--email", required=True)

    # On both subparsers rather than the root, so `--yes` can only follow a chosen command.
    for subcommand in (invite, password):
        subcommand.add_argument(
            "--yes",
            action="store_true",
            help="skip the target confirmation (for scripts; you are on your own)",
        )

    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "create-invite":
            create_invite(args.label, args.max_uses, args.expires_in_days, assume_yes=args.yes)
        else:
            set_password(args.email, assume_yes=args.yes)
    except AdminCommandError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
