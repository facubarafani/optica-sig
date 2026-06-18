# syntax=docker/dockerfile:1
# Production image for SGI Óptica (FastAPI + uvicorn, serves the /app SPA too).
# Multi-arch: python:3.12-slim has native linux/arm64 wheels, so this builds and
# runs unchanged on Oracle Cloud Ampere (ARM) and on x86 VMs alike.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2

WORKDIR /app

# Dependencies first (better layer caching). All deps ship binary wheels for
# arm64 + x86, so no compiler/system build deps are needed.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source (tests/docs/.env excluded via .dockerignore)
COPY . .

# Run as an unprivileged user
RUN adduser --disabled-password --gecos "" appuser \
 && chmod +x docker/entrypoint.sh \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Container-level health check (Coolify/compose use it to gate "healthy")
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.getenv('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/health').status==200 else 1)"

# entrypoint: alembic upgrade head -> (optional) seed -> uvicorn
ENTRYPOINT ["./docker/entrypoint.sh"]
