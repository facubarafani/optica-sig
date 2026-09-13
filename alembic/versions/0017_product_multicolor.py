"""products.multicolor: a bicolour article is one article

Until now two colours on a plain product always meant a style to split into
one article per colour. The flag says the colours describe a single article
instead (a bicolour frame), which is sold and stocked as itself.

Defensive per CLAUDE.md: a fresh database already has the column from 0001.

Revision ID: 0017_product_multicolor
Revises: 0016_code_colors
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column

revision = "0017_product_multicolor"
down_revision = "0016_code_colors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_column("products", "multicolor"):
        op.add_column(
            "products",
            sa.Column("multicolor", sa.Boolean(), server_default=sa.false(),
                      nullable=False),
        )


def downgrade() -> None:
    if has_column("products", "multicolor"):
        op.drop_column("products", "multicolor")
