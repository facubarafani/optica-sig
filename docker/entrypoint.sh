#!/usr/bin/env sh
# Startup sequence for the SGI Óptica container.
#  1. Apply DB migrations (always — safe & idempotent).
#  2. Seed demo data only when SEED_ON_START=true (set it true on the FIRST
#     deploy, then flip to false so later deploys don't re-run it).
#  3. Launch uvicorn (replaces PID 1 via exec so signals/shutdown work).
set -e

echo "[entrypoint] alembic upgrade head…"
alembic upgrade head

if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "[entrypoint] SEED_ON_START=true → seeding demo data…"
  python -m scripts.seed || echo "[entrypoint] seed step failed or already seeded — continuing"
fi

echo "[entrypoint] starting uvicorn on :${PORT:-8000} (workers=${WEB_CONCURRENCY:-2})…"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}"
