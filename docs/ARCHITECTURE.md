# SGI Óptica — Architecture

This document explains how the backend is structured and *why*. It complements
`CLAUDE.md` (contributor rules) and `docs/ER_DIAGRAM.md` (data model).

## 1. Scope of this session

Implemented: the **master-data backbone** — everything other modules depend on.

- Configuration: `company`, `company_settings`
- Auth & RBAC: `user`, `role`, `permission` (+ JWT login)
- Branches, Suppliers
- Product family: product types, brands, products, cost history, stock levels,
  stock movements
- Pricing: price categories, price lists, price list items
- Customers: customers, prescriptions, treatment history
- Cross-cutting infra: change history (audit) + auto-numbering

Out of scope (designed in the ER diagram, not built): sales, cash, customer
current accounts, external work, repairs, payables, reports/dashboard, bulk
import, print/export.

## 2. Stack & layering

```
Request
  │
  ▼
app/api/routers/*          ← HTTP layer: validation, status codes, permissions
  │   (thin; delegates)
  ▼
app/services/*             ← business rules (stock, pricing, auth, numbering, audit)
  │
  ▼
app/models/* (SQLAlchemy)  ↔  app/schemas/* (Pydantic v2)
  │
  ▼
app/core/database.py       ← engine + session
PostgreSQL
```

- **Routers** are intentionally thin. Simple master-data entities are served by a
  generic factory (`app/api/crud_router.py`) so there's one tested implementation
  of list/get/create/update/soft-delete. Entities with rules (products/cost,
  pricing/bulk, stock, users/roles) have bespoke routers.
- **Services** own invariants that must hold regardless of caller: stock can only
  change through `services.stock`, costs through `services.pricing.change_cost`,
  document numbers through `services.numbering`.
- **`core/`** holds cross-cutting plumbing: settings, DB session, security
  (bcrypt + JWT), dependencies (current user / company / permission), and
  `CRUDBase`.

## 3. Key decisions

### Multi-tenant ready, single-tenant runtime
Every business table carries `company_id` (`CompanyMixin`) and queries always
scope by it. For the MVP a single company is assumed; the active company is
derived from the authenticated user (`deps.get_company_id`), with
`settings.DEFAULT_COMPANY_ID` used at login. Turning on true multi-tenancy later
means resolving the tenant (subdomain/header) instead of a constant — no schema
change required.

### Soft deletes
Master data uses `is_active` (`SoftDeleteMixin`). `CRUDBase.remove()` flips the
flag; list endpoints hide inactive rows unless `include_inactive=true`. History
is preserved, matching the spec ("eliminación lógica").

### Audit / change history
`change_history` stores `(entity_type, entity_id, field_name, old_value,
new_value, user, timestamp)`. Critical changes call `services.audit.record_change`
within the same unit of work (so the audit row commits atomically with the
change). Cost changes additionally append to `cost_history`.

### Auto-numbering
`number_sequence` holds one counter per (company, key). `services.numbering
.next_number` consumes it atomically (`SELECT ... FOR UPDATE` on Postgres; no-op
on SQLite used by tests). Keys/prefixes for the future transactional docs are
predefined (`sale`→`V-`, `quote`→`P-`, `work_order`→`OT-`, `repair`→`AR-`).

### Stock integrity
`stock_level` is a cache of on-hand quantity per (product, branch); the source of
truth is the `stock_movement` ledger. `services.stock.apply_movement` writes the
movement, updates the level, snapshots `resulting_quantity`, and records an audit
entry — all in one transaction. Outbound below zero is rejected unless
`company_settings.allow_negative_stock` is on. Transfers post two `transfer`
movements (out of source, into destination).

### Money & quantities
All monetary and quantity columns are `Numeric(12, 2)` — never floats — to avoid
rounding drift. Schemas use `Decimal`.

### Controlled value lists
Every "state"/"type" field is a DB-backed `Enum` defined in `app/models/enums.py`
(supplier type, movement type, treatment type, plus sale/external-work statuses
reserved for the transactional modules).

## 4. Auth & RBAC

- Login (`POST /api/auth/login`, JSON; or `/api/auth/token`, OAuth2 form for
  Swagger) returns a JWT carrying `sub` (user id) and `company_id`.
- `permission` is a global catalogue of codes like `products:write`. `role` is
  per-company and maps to permissions; `user` maps to roles.
- Endpoints declare `require_permission("<area>:<read|write>")`. Superusers
  (`is_superuser`) bypass checks (`permission_codes == {"*"}`).

## 5. Database & migrations

- Local Postgres via `docker-compose`. `DATABASE_URL` configures app + Alembic
  (read in `alembic/env.py`, not from `alembic.ini`).
- The **initial** migration builds the schema from `Base.metadata` so it cannot
  drift from the models on day one. Every later migration must be generated with
  `alembic revision --autogenerate` and reviewed.

## 6. Testing

- `pytest` runs against in-memory SQLite (`tests/conftest.py`) with the FastAPI
  `get_db` dependency overridden and a per-test fresh schema + minimal seed
  (company, permission catalogue, superuser). No Postgres needed for CI.
- Coverage spans auth, RBAC enforcement, soft delete, products + audited cost
  changes, category-based pricing + bulk update, the stock service (levels,
  ledger, negative-stock guard, transfers), customers/prescriptions/treatments,
  and the numbering/audit services.
- Because tests use SQLite, models avoid Postgres-only types. Keep it that way.

## 7. Conventions

See `CLAUDE.md` for the full list and the "add a new entity" recipe. Highlights:
English code, Spanish domain docs; thin routers; services own invariants; never
mutate stock or cost outside their services; never bypass numbering.

## 8. Suggested next steps (transactional layer)

1. **Sales** (`sale`, `sale_item`, `payment`) — consumes numbering (`sale`,
   `quote`), drives stock outbound via `services.stock`, supports deposits/seña.
2. **Cash** (`cash_register_session`, `cash_movement`) — payments impact the open
   session.
3. **Customer current accounts** — debt entries from sales, collection tracking.
4. **External work / repairs** — derive from sales, link to lab/workshop
   suppliers, drive payables.
5. **Payables**, then **reports/dashboard**, **bulk import**, **print/export**.
