"""Access-token verification — the rejections, not the happy path.

Every test here forges a token that a naive `jwt.decode(token, key)` would accept. That
is the point: JWT's failure modes are all *acceptance* failures, and each one below is a
documented attack rather than a hypothetical.

Pure — no database — so the local gate runs them. `AUTH_SECRET` comes from the autouse
fixture in `conftest.py`.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from server.auth.tokens import (
    ALGORITHM,
    ISSUER,
    TOKEN_TYPE,
    USER_TOKEN_TTL,
    InvalidAccessTokenError,
    decode_access_token,
    issue_access_token,
)
from server.settings import auth_secret


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "42",
        "scope": "user",
        "typ": TOKEN_TYPE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + USER_TOKEN_TTL,
    }
    claims.update(overrides)
    return claims


def test_a_freshly_issued_token_round_trips_to_its_principal() -> None:
    issued = issue_access_token(42, "user")
    principal = decode_access_token(issued.token)
    assert (principal.user_id, principal.scope) == (42, "user")
    assert issued.expires_in == int(USER_TOKEN_TTL.total_seconds())


def test_an_unsigned_token_is_rejected() -> None:
    """`alg: none`. The classic forgery: strip the signature, claim it was never needed.

    `algorithms=["HS256"]` in `decode_access_token` is what stops it — without that
    argument PyJWT would consider the algorithm the *token* names.
    """
    forged = jwt.encode(_claims(), key="", algorithm="none")
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(forged)


# PyJWT warns that the key is short for SHA-512. That is the forgery's problem, not
# ours — the point of the test is that the pinned algorithm list refuses the token.
@pytest.mark.filterwarnings("ignore:The HMAC key is")
def test_a_token_signed_with_a_different_hmac_algorithm_is_rejected() -> None:
    """Algorithm confusion: same secret, different `alg`, so the signature verifies
    under a permissive verifier and the pinned list is the only thing refusing it."""
    forged = jwt.encode(_claims(), auth_secret(), algorithm="HS512")
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(forged)


def test_a_token_signed_with_the_wrong_secret_is_rejected() -> None:
    forged = jwt.encode(_claims(), "a-different-key-of-sufficient-length", algorithm=ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(forged)


def test_a_tampered_signature_is_rejected() -> None:
    """Flip one character of the signature; everything else is byte-identical."""
    header, payload, signature = issue_access_token(42, "user").token.split(".")
    swapped = ("B" if signature[0] != "B" else "C") + signature[1:]
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(f"{header}.{payload}.{swapped}")


def test_an_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(minutes=1)
    expired = jwt.encode(_claims(iat=past - timedelta(hours=3), exp=past), auth_secret(), ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(expired)


def test_a_token_with_no_expiry_is_rejected_rather_than_treated_as_eternal() -> None:
    """`require=[...]` in the decoder. An absent claim must never mean "no limit"."""
    claims = _claims()
    del claims["exp"]
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(jwt.encode(claims, auth_secret(), ALGORITHM))


def test_a_token_of_another_type_is_rejected() -> None:
    """The confused-deputy guard: a future refresh/verification JWT must not be usable
    as an access token just because it is correctly signed by the same key."""
    forged = jwt.encode(_claims(typ="refresh"), auth_secret(), ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(forged)


def test_a_token_from_another_issuer_is_rejected() -> None:
    forged = jwt.encode(_claims(iss="portfolio-shell"), auth_secret(), ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(forged)


def test_an_unknown_scope_is_rejected() -> None:
    """Scope is a closed vocabulary; `admin` must not become a valid one by assertion."""
    forged = jwt.encode(_claims(scope="admin"), auth_secret(), ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(forged)
