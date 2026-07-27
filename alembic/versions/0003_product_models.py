"""products.model (free text) -> product_models entity

Free text meant "Clipper", "clipper" and "clip-on" coexisted and nothing could
be filtered or reported by shape. It is now a managed list, still labelled
"Modelo" in the UI. ``product_type_id`` is optional: a model with no type
applies to every type.

Existing distinct values are promoted to rows before the column is dropped.

Revision ID: 0003_product_models
Revises: 0002_drop_product_name
Create Date: 2026-07-26
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column, has_table

revision = "0003_product_models"
down_revision = "0002_drop_product_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # See app/core/migration_utils.py: a database created by 0001_initial after this
    # change already has the table and the FK column.
    if not has_table("product_models"):
        _create_product_models()
    if not has_column("products", "model_id"):
        op.add_column("products", sa.Column("model_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_products_model_id",
            "products",
            "product_models",
            ["model_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # --- backfill: promote each distinct free-text model to a row -----------
    # Only relevant on a database that still carries the old free-text column.
    if has_column("products", "model"):
        _backfill_models()
        op.drop_column("products", "model")


def _create_product_models() -> None:
    op.create_table(
        "product_models",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("product_type_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
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
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["product_type_id"], ["product_types.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_product_model_name"),
    )
    op.create_index(
        op.f("ix_product_models_company_id"),
        "product_models",
        ["company_id"],
        unique=False,
    )


def _backfill_models() -> None:
    # Free text is exactly why this migration exists: "Clipper", "clipper" and
    # " clipper " were three different values. Collapse them case-insensitively
    # into one row (keeping the alphabetically first spelling) so the managed
    # list does not inherit the mess.
    #
    # The product type is left NULL: the old column carried no type information,
    # and NULL means "applies to every type", which is the safe reading.
    op.execute(
        """
        INSERT INTO product_models (company_id, name, product_type_id, is_active)
        SELECT company_id, MIN(TRIM(model)), CAST(NULL AS INTEGER), true
          FROM products
         WHERE model IS NOT NULL AND TRIM(model) <> ''
         GROUP BY company_id, LOWER(TRIM(model))
        """
    )
    op.execute(
        """
        UPDATE products p
           SET model_id = pm.id
          FROM product_models pm
         WHERE pm.company_id = p.company_id
           AND LOWER(pm.name) = LOWER(TRIM(p.model))
           AND p.model IS NOT NULL AND TRIM(p.model) <> ''
        """
    )


def downgrade() -> None:
    op.add_column("products", sa.Column("model", sa.String(length=120), nullable=True))
    op.execute(
        """
        UPDATE products p
           SET model = pm.name
          FROM product_models pm
         WHERE pm.id = p.model_id
        """
    )
    op.drop_constraint("fk_products_model_id", "products", type_="foreignkey")
    op.drop_column("products", "model_id")
    op.drop_index(op.f("ix_product_models_company_id"), table_name="product_models")
    op.drop_table("product_models")
