"""FastAPI application.

Routing contract, validated in spike S0 — see the repo CLAUDE.md before changing
`vercel.json`: `/api/*` reaches this app with the ORIGINAL path, and anything
unmatched here must return FastAPI's own JSON 404, never the SPA's HTML.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.settings import app_version, get_settings

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
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the same-site refresh cookie
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "authorization"],
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness only — deliberately leaks nothing about the deployment."""
    return {"status": "ok"}
