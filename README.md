# SGI Óptica — Sistema de Gestión Integral

Backend foundation for an optics-store management system (Argentina). This first
session delivers the **master-data backbone** end-to-end: models, schemas, CRUD
routers, services, migrations, seed data and tests. Transactional modules (sales,
cash, current accounts, external work, repairs, reports, dashboard, bulk import,
print/export) are designed in the ER diagram but **out of scope** for now.

## Stack

- **FastAPI** + **SQLAlchemy 2.0** (typed `Mapped` models) + **Alembic**
- **PostgreSQL** (via `docker-compose` for local dev)
- **Pydantic v2** schemas, **JWT** auth with role/permission RBAC
- **pytest** suite (runs on in-memory SQLite — no DB needed for tests)

## Key design decisions

| Decision | Implementation |
|----------|----------------|
| Multi-tenant ready | `company` table + `company_id` FK on every business row. Single-tenant for MVP via `DEFAULT_COMPANY_ID`. |
| English naming | All tables/columns/code in English; domain docs in Spanish. |
| Soft delete | `is_active` flag (no physical deletes) on master data. |
| Audit / change history | `change_history` table + `record_change()` service. |
| Auto-numbering | `number_sequence` table + `next_number()` service (sales, quotes, work orders, repairs). |

## Quick start

```bash
# 1. Boot Postgres
docker compose up -d db

# 2. Install deps (use a virtualenv)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure env
cp .env.example .env

# 4. Run migrations
alembic upgrade head

# 5. Seed demo data (company, admin user, roles, sample catalog)
python -m scripts.seed

# 6. Run the API
uvicorn app.main:app --reload
# Docs at http://localhost:8000/docs
```

Login with the seeded admin: `admin@sgi.com` / `admin1234`.

## Tests

```bash
pytest          # uses in-memory SQLite, no Postgres required
```

## Layout

```
app/
  core/        config, db session, security (JWT/bcrypt), deps, base CRUD
  models/      SQLAlchemy 2.0 models (one module per domain)
  schemas/     Pydantic v2 request/response schemas
  services/    numbering, audit, stock, auth business logic
  api/         FastAPI routers + dependency wiring
alembic/       migration env + initial revision
scripts/       seed.py
tests/         pytest suite (per-domain)
docs/          ER_DIAGRAM.md (14 modules), ARCHITECTURE.md
```

See `CLAUDE.md` for contributor conventions and `docs/ARCHITECTURE.md` for the
full design rationale.
