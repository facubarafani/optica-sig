"""FastAPI application entrypoint."""
from __future__ import annotations

from pathlib import Path

import re

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
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
# The bare marketing domain is the one host whose root is a page rather than a
# redirect: the public landing. Every other host (app., the Render hostname,
# localhost) keeps sending "/" to a console, so a shop that bookmarked the bare
# Render URL still lands where it always did.
LANDING_HOSTS = {"miopticadigital.com.ar", "www.miopticadigital.com.ar"}


def _host(request: Request) -> str:
    return (request.headers.get("host") or "").split(":")[0].lower()


def _is_admin_host(request: Request) -> bool:
    return _host(request).split(".")[0] == ADMIN_HOST_LABEL


@app.get("/", include_in_schema=False)
def root(request: Request) -> Response:
    if _host(request) in LANDING_HOSTS:
        return FileResponse(WEB_DIR / "landing.html")
    return RedirectResponse(url="/admin" if _is_admin_host(request) else "/app")


# The same page under a fixed path, so it can be previewed on any host.
@app.get("/landing", include_in_schema=False)
def landing() -> FileResponse:
    return FileResponse(WEB_DIR / "landing.html")


@app.get("/app", include_in_schema=False)
def web_console() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# Screenshots of ARCA's own screens for the facturación setup guide (Empresa),
# cropped from ARCA's published instructivos: the one thing the console loads
# besides its own file. The type is stated rather than guessed: python:3.12
# (the production image) has no media type for .webp, and a guessed one came
# out text/plain there while 3.13 got it right.
GUIDE_DIR = WEB_DIR / "guia"
GUIDE_IMAGE = re.compile(r"[a-z0-9-]+\.webp")


@app.get("/app/guia/{name}", include_in_schema=False)
def guide_image(name: str) -> FileResponse:
    path = GUIDE_DIR / name
    if not GUIDE_IMAGE.fullmatch(name) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="image/webp")


# --- Provider admin console ----------------------------------------------
# A separate page, not a section of /app: the tenant console is shipped to every
# optics shop, and the provider screens have no business being in that bundle
# where a permission bug could reveal them. Same origin, same conventions, its
# own file and its own token scope.
@app.get("/admin", include_in_schema=False)
def admin_console() -> FileResponse:
    return FileResponse(WEB_DIR / "admin.html")
