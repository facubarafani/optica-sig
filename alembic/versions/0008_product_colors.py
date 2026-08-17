"""colors as master data

``products.color`` was free text, so "Negro", "negro" and "NEGRO" were three
different colours and none of them could carry a swatch. Colours become a
catalogue entity like brands and models, and the product points at one.

Existing free-text values are folded into the new table rather than dropped:
one row per distinct colour per company, matched case-insensitively, keeping
the first spelling seen.

Revision ID: 0008_product_colors
Revises: 0007_price_ladder
Create Date: 2026-08-16
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column, has_table

revision = "0008_product_colors"
down_revision = "0007_price_ladder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # See app/core/migration_utils.py: a database created by 0001_initial after
    # this change already has both the table and the FK column.
    if not has_table("colors"):
        op.create_table(
            "colors",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("hex_code", sa.String(length=7), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "name", name="uq_color_name"),
        )
        op.create_index("ix_colors_company_id", "colors", ["company_id"])

    if not has_column("products", "color_id"):
        op.add_column("products", sa.Column("color_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_products_color_id", "products", "colors",
            ["color_id"], ["id"], ondelete="SET NULL",
        )

    # Only a database that predates this revision still has the text column,
    # and only that database has anything to migrate.
    if has_column("products", "color"):
        op.execute(
            """
            INSERT INTO colors (company_id, name, is_active)
            SELECT p.company_id, MIN(TRIM(p.color)), TRUE
              FROM products p
             WHERE p.color IS NOT NULL AND TRIM(p.color) <> ''
             GROUP BY p.company_id, LOWER(TRIM(p.color))
            """
        )
        op.execute(
            """
            UPDATE products p
               SET color_id = c.id
              FROM colors c
             WHERE c.company_id = p.company_id
               AND LOWER(c.name) = LOWER(TRIM(p.color))
               AND p.color IS NOT NULL
               AND TRIM(p.color) <> ''
            """
        )
        op.drop_column("products", "color")


def downgrade() -> None:
    if not has_column("products", "color"):
        op.add_column("products", sa.Column("color", sa.String(length=60),
                                            nullable=True))
        op.execute(
            """
            UPDATE products p
               SET color = c.name
              FROM colors c
             WHERE c.id = p.color_id
            """
        )
    op.drop_constraint("fk_products_color_id", "products", type_="foreignkey")
    op.drop_column("products", "color_id")
    op.drop_index("ix_colors_company_id", table_name="colors")
    op.drop_table("colors")
