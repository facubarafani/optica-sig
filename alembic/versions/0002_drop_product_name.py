"""drop products.name

In practice the code and the name were almost always the same value, so the
name was pure double typing on every alta. The code is now the product's
identification and ``description`` carries the detail.

Anything that was *not* redundant is moved into ``description`` (when empty)
rather than silently dropped.

Revision ID: 0002_drop_product_name
Revises: 0001_initial
Create Date: 2026-07-26
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column

revision = "0002_drop_product_name"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A database created by 0001_initial *after* this change never had the
    # column — nothing to do. See app/core/migration_utils.py.
    if not has_column("products", "name"):
        return
    op.execute(
        """
        UPDATE products
           SET description = name
         WHERE description IS NULL
           AND name IS DISTINCT FROM code
        """
    )
    op.drop_column("products", "name")


def downgrade() -> None:
    # Re-add nullable, backfill from code, then enforce NOT NULL — adding a
    # NOT NULL column straight away would fail on a non-empty table.
    op.add_column("products", sa.Column("name", sa.String(length=180), nullable=True))
    op.execute("UPDATE products SET name = code WHERE name IS NULL")
    op.alter_column("products", "name", nullable=False)
