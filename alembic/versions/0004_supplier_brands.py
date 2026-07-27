"""supplier <-> brands (N-N)

Lets the product form show only the brands the chosen supplier actually
provides, instead of every brand in the company.

Revision ID: 0004_supplier_brands
Revises: 0003_product_models
Create Date: 2026-07-26
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0004_supplier_brands"
down_revision = "0003_product_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # See app/core/migration_utils.py.
    if has_table("supplier_brands"):
        return
    op.create_table(
        "supplier_brands",
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("supplier_id", "brand_id"),
    )


def downgrade() -> None:
    op.drop_table("supplier_brands")
