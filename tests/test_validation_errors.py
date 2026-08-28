"""A 422 must not hand the request back, because the request contains a password.
FastAPI's default `RequestValidationError` handler serialises `input` for every error. On `POST
/api/auth/register` that leaks two ways round: a password below `MIN_PASSWORD_LENGTH` comes back as
the `input` of its own error, and a **missing** field — no `invite_code`, exactly what an
out-of-date client sends — has `input` set to the *whole body*, so the password returns even though
nothing was wrong with it. `server/app.py::validation_error_handler` keeps `type`/`loc`/`msg` and
drops everything else.
**No database, deliberately**: validation fails before the handler runs, so this executes in
the local gate rather than only in CI, where a leak regression would be found by its victim.
"""

import pytest
from fastapi.testclient import TestClient

from server.app import app

# Distinctive, and chosen so neither can appear in a Pydantic message by coincidence: the
# short one must not contain "short", or `{"type": "string_too_short"}` matches it and the
# assertion passes for the wrong reason.
_VALID_LENGTH_PASSWORD = "correct-horse-battery"
_TOO_SHORT_PASSWORD = "Tr0ub4dor"

client = TestClient(app, base_url="https://climb.kilianmc.com", raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        (
            "a missing invite_code, whose `input` is the ENTIRE body",
            {"email": "leak@example.com", "password": _VALID_LENGTH_PASSWORD},
        ),
        (
            "a password below the floor, whose `input` is the password itself",
            {
                "email": "leak@example.com",
                "password": _TOO_SHORT_PASSWORD,
                "invite_code": "a-code",
            },
        ),
        (
            "an unknown extra field, rejected by extra='forbid'",
            {
                "email": "leak@example.com",
                "password": _VALID_LENGTH_PASSWORD,
                "invite_code": "a-code",
                "is_demo": True,
            },
        ),
    ],
)
def test_a_422_never_echoes_the_submitted_password(label: str, payload: dict[str, object]) -> None:
    response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 422, f"{label}: {response.text}"
    body = response.text
    for secret in (_VALID_LENGTH_PASSWORD, _TOO_SHORT_PASSWORD):
        assert secret not in body, (
            f"{label}: the 422 body contains the submitted password. It reaches the browser's "
            f"network panel, every proxy in between and anything that logs a response body. "
            f"Body was: {body}"
        )


def test_a_422_still_says_which_field_and_why() -> None:
    """The negative control: stripping `input` must not have made the 422 useless.

    `web/src/api/client.ts::detailMessage` joins the `msg` values, and
    `web/src/auth/messages.ts` shows its own copy for a 422 — but a developer reading a failed
    request needs `loc` to be there. Without this, a handler returning `{"detail": []}` would
    pass every assertion above.
    """
    response = client.post(
        "/api/auth/register",
        json={"email": "leak@example.com", "password": _VALID_LENGTH_PASSWORD},
    )
    errors = response.json()["detail"]

    assert [error["loc"] for error in errors] == [["body", "invite_code"]]
    assert errors[0]["type"] == "missing"
    assert errors[0]["msg"]


def test_the_allowlist_drops_ctx_as_well_as_input() -> None:
    """`ctx` is a separate leak and needs its own case, on an error that actually HAS one.

    Only some error types carry it: `missing` does not, `string_too_short` does
    (`{"min_length": 12}`). A key-set assertion written against a *missing* field therefore
    passes with `ctx` in the allowlist — measured, so this test exists rather than an extra
    line on the one above. What `ctx` leaks is the password policy, not a credential, which is
    why it is asserted apart from the password checks and not folded into them.
    """
    response = client.post(
        "/api/auth/register",
        json={
            "email": "leak@example.com",
            "password": _TOO_SHORT_PASSWORD,
            "invite_code": "a-code",
        },
    )
    errors = response.json()["detail"]

    assert [error["type"] for error in errors] == ["string_too_short"]
    assert set(errors[0]) == {"type", "loc", "msg"}, (
        "the allowlist let a key through: `input` is the password itself, `ctx` is the policy."
    )

    # Measured, because it changes what this test can prove: FastAPI 0.141 already drops
    # Pydantic's `url` before the handler runs (`errors()` yields ctx/input/loc/msg/type only),
    # so adding "url" to the allowlist is a no-op today and this assertion cannot catch it.
    # That is an argument FOR the allowlist rather than against it — a redaction pass would
    # have to be edited when upstream starts sending a key again; an allowlist would not.
