"""give every company a starter set of product types

``products.product_type_id`` is NOT NULL and the console's field is required,
so a company with an empty type list cannot create its first product at all —
there is nothing to pick. ``provision_company_defaults`` now seeds three types
for new tenants; this backfills the ones that already exist, which is every
shop onboarded through /admin before this revision (the seed only ever built
them for the demo company).

Data only — no schema change, so there is nothing for the fresh-vs-existing
convergence rules to guard beyond the tables existing at all.

Revision ID: 0014_starter_product_types
Revises: 0013_user_tokens
Create Date: 2026-09-10
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0014_starter_product_types"
down_revision = "0013_user_tokens"
branch_labels = None
depends_on = None

# Mirrors provisioning.STARTER_PRODUCT_TYPES as of this revision. Copied rather
# than imported on purpose: a migration has to keep doing what it did the day
# it was written, however that constant evolves later.
STARTER_PRODUCT_TYPES = ["Armazones", "Lentes de sol", "Lentes de contacto"]


def upgrade() -> None:
    if not (has_table("companies") and has_table("product_types")):
        return

    bind = op.get_bind()
    # Only companies with *no* types at all. A shop that renamed them, pruned
    # them or built its own set is left alone — the point is to unblock the
    # ones that cannot create a product, not to impose our names on anybody.
    targets = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT c.id FROM companies c "
                " WHERE NOT EXISTS (SELECT 1 FROM product_types pt "
                "                    WHERE pt.company_id = c.id)"
            )
        )
    ]
    if not targets:
        return

    # is_active has a Python-side default only (SoftDeleteMixin), so raw SQL
    # has to supply it; created_at/updated_at do carry a server default, but
    # naming them keeps this insert readable next to the ORM's.
    stmt = sa.text(
        "INSERT INTO product_types "
        "       (company_id, name, is_active, created_at, updated_at) "
        "VALUES (:company_id, :name, :is_active, "
        "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    for company_id in targets:
        for name in STARTER_PRODUCT_TYPES:
            bind.execute(
                stmt, {"company_id": company_id, "name": name, "is_active": True}
            )


def downgrade() -> None:
    """Deliberately a no-op.

    Once a shop has used or renamed these rows there is no way to tell them
    from types it created itself, and deleting one that a product points at
    would fail the RESTRICT anyway. Leaving master data behind is the harmless
    direction.
    """
