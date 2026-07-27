"""product selling price: manual or (price list + category)

Until now a product had no selling price of its own — it was inferred from its
price category against the company's default list, with no way to override
either. Products now carry a mode:

  * MANUAL     -> ``sale_price`` holds the price
  * PRICE_LIST -> ``price_category_id`` is looked up in ``price_list_id``,
                  falling back to the company default when that is NULL

The default is PRICE_LIST with a NULL list, which is exactly the previous
behaviour — existing rows keep resolving the same way.

Revision ID: 0005_product_selling_price
Revises: 0004_supplier_brands
Create Date: 2026-07-26
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column

revision = "0005_product_selling_price"
down_revision = "0004_supplier_brands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # See app/core/migration_utils.py.
    if has_column("products", "pricing_mode"):
        return
    # op.add_column does NOT create the Postgres enum type on its own — it has
    # to exist before the column referencing it. Labels are the enum member
    # names, matching the other enums in this schema (INBOUND, MERCHANDISE…).
    pricing_mode = sa.Enum("MANUAL", "PRICE_LIST", name="pricing_mode")
    pricing_mode.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "products",
        sa.Column(
            "pricing_mode",
            pricing_mode,
            server_default="PRICE_LIST",
            nullable=False,
        ),
    )
    op.add_column(
        "products", sa.Column("sale_price", sa.Numeric(precision=12, scale=2), nullable=True)
    )
    op.add_column("products", sa.Column("price_list_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_products_price_list_id",
        "products",
        "price_lists",
        ["price_list_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_products_price_list_id", "products", type_="foreignkey")
    op.drop_column("products", "price_list_id")
    op.drop_column("products", "sale_price")
    op.drop_column("products", "pricing_mode")
    sa.Enum(name="pricing_mode").drop(op.get_bind(), checkfirst=True)
