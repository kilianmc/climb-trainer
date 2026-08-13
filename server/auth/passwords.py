"""argon2id password hashing.

## The profile is OWASP's, NOT the library's defaults

`m=46 MiB, t=1, p=1` — the first of OWASP's recommended argon2id configurations. The
deviation that matters is **`p=1`**: `argon2-cffi` defaults to `p=4`, and four lanes
only buy anything on four cores. A Vercel serverless function has **1 vCPU**, so `p=4`
there is four lanes time-slicing one core — identical work, more scheduling, worse
latency, and no extra resistance. Setting it explicitly also means the hash cost stops
depending on whatever the library's defaults happen to be after an upgrade.

Memory cost is expressed in **KiB** by `argon2-cffi`, hence `46 * 1024`.

## Timing is part of the security boundary

A login that returns fast for an unknown email and slow for a known one is an account
enumeration oracle — it tells an attacker which addresses are registered, which is
exactly the input a credential-stuffing run wants. `verify_dummy()` exists so the
unknown-email path pays the same argon2 cost as the wrong-password path. It is not
optional politeness; without it the generic 401 in `routes.py` is cosmetic.

## Parameter migration

`needs_rehash()` exposes argon2's rehash signal. `routes.py` acts on it during login,
where the plaintext is available and the request is already committing a row, so
raising the cost parameters later is a no-downtime change that migrates users as they
sign in. Nothing rehashes outside login — there is nowhere else the plaintext exists.
"""

import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP argon2id profile #1. See the module docstring before changing any number:
# every one of these is a deliberate departure from the library default.
_HASHER = PasswordHasher(
    time_cost=1,
    memory_cost=46 * 1024,  # KiB -> 46 MiB
    parallelism=1,  # 1 vCPU on Vercel; more lanes is pure latency here
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Return the encoded argon2id hash (algorithm and parameters included in the string)."""
    return _HASHER.hash(password)


def verify_password(encoded_hash: str, password: str) -> bool:
    """`True` iff `password` matches. Never raises for a wrong password or a bad hash.

    A malformed stored hash is treated as "does not match" rather than a 500: it is a
    data problem, and a 500 on a login attempt is itself an information leak.
    """
    try:
        return _HASHER.verify(encoded_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(encoded_hash: str) -> bool:
    """Whether `encoded_hash` was produced with weaker parameters than the current profile."""
    try:
        return _HASHER.check_needs_rehash(encoded_hash)
    except InvalidHashError:
        # Unparseable: it cannot be verified either, so there is nothing to migrate.
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A throwaway hash of a random string, computed once per process.

    Random rather than a constant so no hash of a known plaintext is ever baked into a
    public repository. Lazy rather than module-level so importing this module — which
    `server.app` does on every cold start — does not pay a 46 MiB argon2 run.
    """
    return _HASHER.hash(secrets.token_urlsafe(32))


def verify_dummy() -> None:
    """Burn one argon2 verification so the unknown-email path costs what a real one does.

    Caveat, accepted deliberately: the *first* call in a fresh process also pays for
    building the dummy hash, so one request per cold start is measurably slower. That
    is noise against Neon's wake latency and a cold Python start, and the alternative —
    hashing at import — would slow every cold start instead of one unlucky login.
    """
    try:
        _HASHER.verify(_dummy_hash(), "")
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass
