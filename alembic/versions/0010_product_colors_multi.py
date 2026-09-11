"""a product comes in several colours (N-N)

``products.color_id`` allowed exactly one, but the same frame is normally
stocked in three or four. The link becomes ``product_colors``, and the single
colour each product already had is carried over as its first row.

Revision ID: 0010_product_colors_multi
Revises: 0009_sales
Create Date: 2026-08-29
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column, has_table

revision = "0010_product_colors_multi"
down_revision = "0009_sales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # See app/core/migration_utils.py: a database created by 0001_initial after
    # this change already has the table and no longer has the column.
    if not has_table("product_colors"):
        op.create_table(
            "product_colors",
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("color_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["color_id"], ["colors.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("product_id", "color_id"),
        )

    # Only a database that predates this revision still has the column, and
    # only that one has anything to carry over.
    if has_column("products", "color_id"):
        op.execute(
            """
            INSERT INTO product_colors (product_id, color_id)
            SELECT id, color_id FROM products WHERE color_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
        # Postgres drops the FK constraint along with the column, and its name
        # differs depending on whether 0001 or 0008 created it.
        op.drop_column("products", "color_id")


def downgrade() -> None:
    if not has_column("products", "color_id"):
        op.add_column("products", sa.Column("color_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_products_color_id", "products", "colors",
            ["color_id"], ["id"], ondelete="SET NULL",
        )
        # One column cannot hold a set: the lowest id wins and the rest are lost.
        op.execute(
            """
            UPDATE products p
               SET color_id = (SELECT MIN(pc.color_id)
                                 FROM product_colors pc
                                WHERE pc.product_id = p.id)
            """
        )
    op.drop_table("product_colors")
