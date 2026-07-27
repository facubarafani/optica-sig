# CLAUDE.md — SGI Óptica

Guidance for AI assistants and contributors working in this repository.

## What this is

Backend for a **Sistema de Gestión Integral para ópticas** (optics-store ERP),
Argentina. This codebase currently implements the **master-data backbone** only.
Transactional modules are designed (see `docs/ER_DIAGRAM.md`) but not built yet.

## Architecture in one screen

- **Stack**: FastAPI + SQLAlchemy 2.0 (typed) + Alembic + PostgreSQL. Pydantic v2.
- **Layering**: `api/` (routers, thin) → `services/` (business rules) → `models/`
  (SQLAlchemy) ↔ `schemas/` (Pydantic). Shared plumbing lives in `core/`.
- **Generic CRUD**: `app/core/crud.py::CRUDBase` handles list/get/create/update/
  soft-delete for simple master-data entities. Routers compose it; anything with
  business rules (stock, auth, numbering) goes through a dedicated service.

## Non-negotiable conventions

1. **English everywhere in code** (tables, columns, vars). User-facing domain docs
   may be Spanish.
2. **Multi-tenant ready, single-tenant runtime.** Every business table has a
   `company_id` FK (`CompanyMixin`). Queries must always scope by company. The
   active company comes from `settings.DEFAULT_COMPANY_ID` for now; do not hardcode.
3. **No physical deletes** on master data. Use `is_active=False` (`SoftDeleteMixin`).
   `CRUDBase.remove()` soft-deletes; list endpoints filter `is_active=True` by default.
4. **Audit critical changes.** Price, cost, category and stock changes must call
   `services.audit.record_change(...)`. Cost changes additionally append to
   `cost_history`.
5. **Auto-number documents.** Never invent IDs for sales/quotes/work-orders/repairs.
   Use `services.numbering.next_number(db, company_id, key)`.
6. **Money = `Numeric(12, 2)`.** Never float. Quantities = `Numeric(12, 2)` too
   (supports fractional units / adjustments).
7. **Enums = controlled string lists** via `app/models/enums.py`. Add new states
   there, never as free text. SQLAlchemy stores the member **name** in Postgres
   (`INBOUND`, `PRICE_LIST`), so a migration's `server_default` must use the
   name, not the value.
8. **Selling price is resolved, never read off the row.** Use
   `services.pricing.resolve_price()` (or `resolve_prices()` for a list — it
   batches, avoiding N+1). It handles both `pricing_mode`s and the fallback to
   the company's default price list. The sales module must call it rather than
   reimplement the rules.
9. **Bulk import never bypasses business rules.** `services/importer/` routes
   costs through `pricing.change_cost()` and stock through
   `stock.apply_movement()`, both with `commit=False` so a batch is one
   transaction. Adding an import target = one `ImportSpec` in
   `importer/specs.py` + one apply function in `importer/engine.py` + one row
   builder in `importer/exporters.py`; the template, the mapping UI, the
   preview and the export all derive from the spec.
10. **Export and import share the spec, so files round-trip.** An export uses
    the import column layout: export → edit in Excel → re-import updates by
    key instead of duplicating. Keep it that way — if you add a column to a
    spec, both directions get it. `.xlsx` writes real numeric cells (immune to
    locale parsing); `.csv` uses `;` + comma decimals + a UTF-8 BOM, which is
    what Spanish Excel reads and what the importer defaults to.

## Web console (`app/web/index.html`)

Single self-contained file — no build step, no external requests. Two
conventions worth knowing before editing it:

- **Icons** come from an embedded Lucide sprite at the top of `<body>`. Use
  `<svg class="ic"><use href="#i-name"/></svg>` (add `lg` for 18px). Never add
  a CDN link or an icon font: the console must keep working offline and with no
  third-party dependency. To add an icon, paste one more `<symbol>` into the
  sprite.
- **Table columns take a `priority`** (`2` or `3`). Priority 3 hides below
  1460px of viewport, priority 2 below 1250px, so a wide grid degrades by
  showing fewer columns instead of scrolling sideways. Mark anything secondary;
  leave the identifying columns unmarked.
- Row actions: keep at most two labelled buttons and put the rest in the `⋯`
  menu via `openRowMenu(anchor, items)`.

## Adding a new master-data entity (recipe)

1. Model in `app/models/<domain>.py` — extend `Base`, add mixins
   (`TimestampMixin`, `SoftDeleteMixin`, `CompanyMixin` as needed).
2. Register the module import in `app/models/__init__.py` (so metadata sees it).
3. Schemas in `app/schemas/<domain>.py` (`*Create`, `*Update`, `*Read`).
4. Router in `app/api/routers/<domain>.py` using `CRUDBase`; include it in
   `app/api/__init__.py`.
5. Migration: `alembic revision --autogenerate -m "add <entity>"`.
6. Tests in `tests/test_<domain>.py`.

## Database & migrations

- Local DB: `docker compose up -d db`. Connection from `DATABASE_URL`.
- The **initial** migration creates the whole schema from `Base.metadata` (so it
  can never drift from the models). **All subsequent migrations must use
  `--autogenerate`** and be reviewed.
- **Consequence — subsequent migrations must be defensive.** Because `0001` is
  metadata-derived, a *fresh* database is created with today's schema and then
  runs `0002+` against it, while an *existing* database runs them against the
  old schema. Any migration that alters a table already in `0001` must guard
  with `app.core.migration_utils.has_table()` / `has_column()` so both paths
  converge. Skipping this breaks every fresh deploy — see `0002`–`0004`.
- Test both paths before shipping a migration: `upgrade head` on an empty DB,
  and on a copy of the old schema (to exercise the data backfill).
- `alembic/env.py` reads `DATABASE_URL` from the environment, not `alembic.ini`.

## Tests

- `pytest`. Tests use an **in-memory SQLite** engine (see `tests/conftest.py`),
  so they need no Postgres. Keep models portable — avoid Postgres-only column
  types (JSONB, ARRAY); use generic SQLAlchemy types.
- Every service with business logic (stock movements, numbering, auth) must have
  direct unit tests, plus an API-level happy-path test.

## Gotchas

- `passlib[bcrypt]` is pinned with `bcrypt==4.0.1` to avoid the 4.1+ warning noise.
- Stock is **never** mutated directly. Go through `services.stock.apply_movement()`,
  which writes a `stock_movement` row and updates the matching `stock_level`
  atomically.
- Seeding is idempotent-ish: `python -m scripts.seed` assumes an empty/migrated DB.
