#!/usr/bin/env bash
# SessionStart hook: boot the local Postgres container and run migrations so the
# dev DB is always ready. Designed to be safe & non-blocking — if Docker isn't
# available it prints a note and exits 0 (never fails the session).
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0

if ! command -v docker >/dev/null 2>&1; then
  echo "[sgi] Docker not found — skipping DB boot. Start Postgres manually if needed."
  exit 0
fi

echo "[sgi] Starting Postgres (docker compose up -d db)..."
if ! docker compose up -d db >/dev/null 2>&1; then
  echo "[sgi] Could not start the db container — skipping migrations."
  exit 0
fi

# Wait (up to ~30s) for the container healthcheck to report healthy.
for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' sgi_postgres 2>/dev/null || echo starting)"
  [ "$status" = "healthy" ] && break
  sleep 1
done

# Prefer the project virtualenv's alembic if present.
if [ -x ".venv/bin/alembic" ]; then
  ALEMBIC=".venv/bin/alembic"
elif command -v alembic >/dev/null 2>&1; then
  ALEMBIC="alembic"
else
  echo "[sgi] alembic not installed (no .venv) — DB is up; run 'pip install -r requirements.txt' then 'alembic upgrade head'."
  exit 0
fi

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://sgi:sgi@localhost:5432/sgi}"
echo "[sgi] Applying migrations (alembic upgrade head)..."
"$ALEMBIC" upgrade head >/tmp/sgi_alembic.log 2>&1 \
  && echo "[sgi] Database ready." \
  || { echo "[sgi] Migration failed (see /tmp/sgi_alembic.log):"; tail -5 /tmp/sgi_alembic.log; }

exit 0
