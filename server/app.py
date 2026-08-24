"""FastAPI application.

Routing contract, validated in spike S0 — see the repo CLAUDE.md before changing
`vercel.json`: `/api/*` reaches this app with the ORIGINAL path, and anything
unmatched here must return FastAPI's own JSON 404, never the SPA's HTML.

**Authentication is deny-by-default and is wired here, once**, as an application-level
dependency. Registering it per-router would fail open the first time someone forgot;
registering it here means a new endpoint is protected unless its `(method, path)` is
added to `PUBLIC_ROUTES` in `server/auth/deps.py`, in a diff a reviewer sees.
"""

from typing import Final

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.auth.deps import enforce_auth
from server.auth.routes import router as auth_router
from server.library.routes import router as library_router
from server.plans.routes import router as plans_router
from server.profile.routes import router as profile_router
from server.security_headers import SecurityHeadersMiddleware
from server.settings import app_version, get_settings
from server.vocabulary.routes import router as vocabulary_router

settings = get_settings()

# OpenAPI is a map of the attack surface; keep it off in production.
_docs_enabled = not settings.is_production

app = FastAPI(
    title="climb-trainer API",
    # Never hardcode this — it comes from the root package.json. See app_version().
    version=app_version(),
    docs_url="/api/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _docs_enabled else None,
    # Nothing here uses OAuth2 in Swagger, and the default registers an extra route at
    # `/docs/oauth2-redirect` — outside `/api/*`, so it could never be reached through
    # Vercel's rewrite anyway. Removing it keeps the registered route table equal to the
    # routes that actually exist, which is what the enumeration test walks.
    swagger_ui_oauth2_redirect_url=None,
    # The deny-by-default gate. See server/auth/deps.py.
    dependencies=[Depends(enforce_auth)],
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the same-site refresh cookie
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "authorization"],
    )

# Swagger UI loads its assets from the jsdelivr CDN, which the API's `default-src 'none'`
# would block. Derived from the configured docs URLs, not literals, so it follows
# `_docs_enabled`: both are None in production, making this set empty there.
_CSP_EXEMPT_PATHS = frozenset(p for p in (app.docs_url, app.openapi_url) if p is not None)

# Added last, so it is the outermost middleware (`add_middleware` prepends) and also
# covers the preflight responses CORS answers itself. It writes only its own header
# names, never `Access-Control-*` or `Vary`.
app.add_middleware(SecurityHeadersMiddleware, csp_exempt_paths=_CSP_EXEMPT_PATHS)


# The only keys of a Pydantic error that ever reach a client. Everything else is dropped —
# see the handler below.
_SAFE_VALIDATION_KEYS: Final = frozenset({"type", "loc", "msg"})


@app.exception_handler(RequestValidationError)
def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422s must never echo the request back. FastAPI's default one does.

    **This is a credential leak, not a tidiness issue.** Every entry in
    `RequestValidationError.errors()` carries `input`, and FastAPI serialises it: a password
    below `MIN_PASSWORD_LENGTH` comes back in the response body, and a *missing* field — a
    `register` call with no `invite_code` — has `input` set to the **whole body**, so the
    plaintext password is returned to the caller and into whatever logged the response. It
    reaches the browser's network panel, any proxy in between, and any error reporter the
    client grows later.

    So the handler is an **allowlist, not a redaction pass**: `type`, `loc` and `msg` are kept
    and everything else is discarded, which means a future Pydantic version adding another
    value-bearing key cannot leak through it. `ctx` goes too — it is where the bounds live
    (`{"min_length": 12}`), and the password policy is not something a 422 needs to publish.
    (`url` never gets this far: FastAPI 0.141 already drops it. Which is the argument for an
    allowlist — if that ever changes, nothing here has to be edited to keep up.)

    `web/src/api/client.ts::detailMessage` reads `msg` out of this array, so the client's
    copy is unaffected. Registered on the app rather than per-route because the leak is a
    property of the framework's default, not of any one endpoint.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": [
                {key: value for key, value in error.items() if key in _SAFE_VALIDATION_KEYS}
                for error in exc.errors()
            ]
        },
    )


app.include_router(auth_router)
app.include_router(library_router)
app.include_router(plans_router)
app.include_router(profile_router)
app.include_router(vocabulary_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness only — deliberately leaks nothing about the deployment.

    Public (listed in `PUBLIC_ROUTES`) and DB-free: a health check that queried the
    database would restart Neon's five-minute awake window on every probe.
    """
    return {"status": "ok"}
