"""FastAPI application entrypoint."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.api import api_router
from app.core.config import settings

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Sistema de Gestión Integral para ópticas (Argentina) — master-data "
        "backbone. Transactional modules are designed in docs/ER_DIAGRAM.md but "
        "not yet implemented."
    ),
)

app.include_router(api_router, prefix="/api")


@app.exception_handler(IntegrityError)
def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Map DB constraint violations (e.g. duplicate unique keys) to 409."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "Integrity constraint violated (duplicate or invalid reference)."},
    )


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


# --- Admin web console (self-contained single-page app) ------------------
# Served same-origin so the browser can call /api/* without CORS. The SPA uses
# hash-based routing, so a single route serves every screen.
# Which console the bare domain opens depends on the host it was asked for:
# admin.<domain> is the provider's front door, anything else is a shop's. Both
# pages stay reachable on both hosts deliberately: impersonation writes the
# tenant token into localStorage and opens /app, which only works because that
# is the same origin (see admin.html). Serving them on separate origins would
# need the handoff rewritten, so the split here is cosmetic, not a boundary.
ADMIN_HOST_LABEL = "admin"


def _is_admin_host(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(":")[0].lower()
    return host.split(".")[0] == ADMIN_HOST_LABEL


@app.get("/", include_in_schema=False)
def root(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/admin" if _is_admin_host(request) else "/app")


@app.get("/app", include_in_schema=False)
def web_console() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# --- Provider admin console ----------------------------------------------
# A separate page, not a section of /app: the tenant console is shipped to every
# optics shop, and the provider screens have no business being in that bundle
# where a permission bug could reveal them. Same origin, same conventions, its
# own file and its own token scope.
@app.get("/admin", include_in_schema=False)
def admin_console() -> FileResponse:
    return FileResponse(WEB_DIR / "admin.html")
