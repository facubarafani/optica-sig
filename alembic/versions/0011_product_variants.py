"""a product is a style; its colours are variants with their own codes

The same frame is sold in several colours, and each colour is its own article:
its own code, its own stock, its own line on a sale. ``products.parent_id``
links a colour back to the style it belongs to, in the same table — everything
that references a product (stock, movements, sale lines, cost history) keeps
working without knowing the family exists.

``colors.code`` is the short tag that ends up inside a variant's code
(ARM-001 + HAV -> ARM-001-HAV). Existing colours get one derived from their
name, exactly as services.products.derive_color_code would.

Revision ID: 0011_product_variants
Revises: 0010_product_colors_multi
Create Date: 2026-08-29
"""
import re
import unicodedata

import sqlalchemy as sa

from alembic import op
from app.core.migration_utils import has_column

revision = "0011_product_variants"
down_revision = "0010_product_colors_multi"
branch_labels = None
depends_on = None


def _derive_codes(bind) -> None:
    """Give every existing colour a free short tag, longest-stable-first.

    Mirrors services.products.derive_color_code: three letters, lengthening
    before numbering, so "Negro"/"Negro mate" become NEG and NEGR. Done in
    Python rather than SQL because the collision rule is the same rule the
    application uses, and it must not drift.
    """
    rows = bind.execute(
        sa.text("SELECT id, company_id, name FROM colors ORDER BY company_id, id")
    ).fetchall()
    taken: dict[int, set[str]] = {}
    for cid, company_id, name in rows:
        folded = unicodedata.normalize("NFKD", name or "")
        base = re.sub(
            r"[^A-Za-z0-9]", "",
            "".join(c for c in folded if not unicodedata.combining(c)),
        ).upper()
        if not base:
            continue
        used = taken.setdefault(company_id, set())
        code = None
        for size in range(3, min(len(base), 8) + 1):
            if base[:size] not in used:
                code = base[:size]
                break
        if code is None:
            stem = base[:6]
            for n in range(2, 100):
                if f"{stem}{n}" not in used:
                    code = f"{stem}{n}"
                    break
        if code is None:
            continue
        used.add(code)
        bind.execute(
            sa.text("UPDATE colors SET code = :code WHERE id = :id"),
            {"code": code, "id": cid},
        )


def upgrade() -> None:
    # See app/core/migration_utils.py: a database created by 0001_initial after
    # this change already has both columns.
    if not has_column("products", "parent_id"):
        op.add_column("products", sa.Column("parent_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_products_parent_id", "products", "products",
            ["parent_id"], ["id"], ondelete="RESTRICT",
        )
        op.create_index("ix_products_parent_id", "products", ["parent_id"])

    fresh = has_column("colors", "code")
    if not fresh:
        op.add_column("colors", sa.Column("code", sa.String(length=8), nullable=True))
        op.create_unique_constraint("uq_color_code", "colors", ["company_id", "code"])
    # A fresh database has the column but no rows; an existing one has rows
    # that predate it. Backfilling both is harmless and keeps the paths equal.
    _derive_codes(op.get_bind())


def downgrade() -> None:
    op.drop_constraint("uq_color_code", "colors", type_="unique")
    op.drop_column("colors", "code")
    op.drop_index("ix_products_parent_id", table_name="products")
    op.drop_constraint("fk_products_parent_id", "products", type_="foreignkey")
    # Variants become ordinary standalone products rather than vanishing.
    op.drop_column("products", "parent_id")
