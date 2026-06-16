"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import api_router
from app.core.config import settings

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
