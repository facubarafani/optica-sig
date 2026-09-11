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
| Selling price | Per product: manual price, or price list + category (the product's list overrides the company default). Resolved by `pricing.resolve_price()`. |
| Bulk import | Excel/CSV → column mapping → preview → atomic commit, for products, costs, initial stock and price lists. Downloadable `.xlsx` template. |
| Bulk export | Same four targets to `.xlsx`/`.csv`, using the import column layout — export, edit in Excel, re-import. Respects the on-screen filters. |

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

Two consoles, two logins:

| Console | URL | Seeded login | Who it is for |
|---|---|---|---|
| Gestión (tenant) | `/app` | `admin@sgi.com` / `admin1234` | An óptica's own staff |
| Plataforma (provider) | `/admin` | `owner@sgi.com` / `owner1234` | Us — onboarding and supporting ópticas |

The two use separate identity tables and separate JWT scopes: a shop login
cannot reach `/admin`, and a provider login cannot read a shop's data. Override
the provider credentials with `PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`
anywhere that is not a local demo.

**Provider accounts are created from the CLI, never from a form** — a platform
login can enter any tenant's data, so the authorisation to mint one is shell
access to the server:

```bash
source .venv/bin/activate    # macOS has no bare `python` outside a venv

python -m scripts.platform_admin list                  # who has access (flags demo passwords)
python -m scripts.platform_admin create                # prompts for email, name, password
python -m scripts.platform_admin password you@sgi.com  # rotate
python -m scripts.platform_admin disable ex@sgi.com    # revoke; refuses the last active account
```

Without activating, prefix any of these with the interpreter instead:
`.venv/bin/python -m scripts.platform_admin list`. Either way `DATABASE_URL` is
read from `.env`, so there is nothing to export.

Passwords are never taken as a flag (argv leaks into `ps` and shell history):
type them at the prompt, or pipe them in with `--password-stdin`. Minimum 12
characters, and the repo's demo password is rejected outright.

### Correo

New ópticas and new admins get an **emailed invitation** to choose their own
password, and anyone can use "Olvidé mi contraseña" on the login screen — so you
never handle a customer's credential or field a reset call.

Out of the box `EMAIL_BACKEND=console`, which **prints** the mail (link
included) instead of sending it, so the flow is fully testable with no provider.
Point it at a real one when you have one — see [docs/EMAIL.md](docs/EMAIL.md),
which covers provider setup and the DNS for `miopticadigital.com.ar`.

To see where the domain setup stands at any point, and to send a real test
email through whichever provider is configured:

```bash
python -m scripts.check_dns
EMAIL_BACKEND=resend RESEND_API_KEY=re_... python -m scripts.send_test_email vos@gmail.com
```

From `/admin` you can create a new óptica (which provisions its company,
roles, admin user, branch, colour palette, price list and numbering in one
transaction), suspend one for non-payment, reset a locked-out owner's password,
and open a 30-minute audited support session inside their console.

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
  services/    numbering, audit, stock, pricing, auth business logic
    importer/  bulk import: readers (xlsx/csv), specs, engine, templates
  api/         FastAPI routers + dependency wiring
  web/         single-file Spanish admin console served at /app
alembic/       migration env + revisions
scripts/       seed.py
tests/         pytest suite (per-domain)
docs/          ER_DIAGRAM.md (14 modules), ARCHITECTURE.md
```

See `CLAUDE.md` for contributor conventions and `docs/ARCHITECTURE.md` for the
full design rationale.
