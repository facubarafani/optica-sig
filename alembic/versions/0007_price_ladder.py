"""price categories belong to a list; lists get a currency

Categories used to be company-wide, with ``price_list_items`` assigning one
price per (list, category). They are now the **steps of one list** — a ladder of
codes ``AA``, ``AB``, ``AC``… each holding its own price — so every list decides
how many steps it has. ``price_list_items`` is absorbed into ``price_categories``
and dropped.

Products stop pointing at a category row and carry the **code** instead
(``price_category_code``), which is what lets one product be priced by whichever
list applies.

Data migration
--------------
Old categories are ranked cheapest-first (by their lowest price across all
lists) and handed codes AA, AB, AC… *per company*, so the same old category is
the same code in every list. Each old ``price_list_item`` becomes a step of its
list, keeping its price; the old category name survives in ``description`` so no
labelling is lost. A category nobody priced still gets a code, so products
tagged with it keep a meaningful (if unpriced) value.

Revision ID: 0007_price_ladder
Revises: 0006_import_batches
Create Date: 2026-07-26
"""
from collections import defaultdict
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column, has_table

revision = "0007_price_ladder"
down_revision = "0006_import_batches"
branch_labels = None
depends_on = None

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _code(rank: int) -> str:
    """0 -> "AA", 1 -> "AB", … 675 -> "ZZ". Mirrors services.pricing.category_code."""
    return _LETTERS[rank // 26] + _LETTERS[rank % 26]


def upgrade() -> None:
    # A database created by 0001_initial *after* this change already has the new
    # shape — nothing to do. See app/core/migration_utils.py.
    if has_column("price_categories", "price_list_id"):
        return

    bind = op.get_bind()

    if not has_column("price_lists", "currency"):
        op.add_column(
            "price_lists",
            sa.Column(
                "currency", sa.String(length=3), nullable=False, server_default="ARS"
            ),
        )

    # --- new columns, nullable until the backfill has run ------------------
    op.add_column(
        "price_categories", sa.Column("price_list_id", sa.Integer(), nullable=True)
    )
    op.add_column("price_categories", sa.Column("code", sa.String(length=8), nullable=True))
    op.add_column(
        "price_categories",
        sa.Column(
            "price", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "price_categories",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    if not has_column("products", "price_category_code"):
        op.add_column(
            "products", sa.Column("price_category_code", sa.String(length=8), nullable=True)
        )
    # ``name`` is dropped at the end of this migration, but the new per-list rows
    # are inserted while it is still there — so it has to stop being NOT NULL.
    op.alter_column("price_categories", "name", nullable=True)

    # --- rank the old categories and hand out codes, per company -----------
    old_cats = bind.execute(
        sa.text(
            "SELECT id, company_id, name, description FROM price_categories "
            "ORDER BY company_id, id"
        )
    ).mappings().all()

    items = []
    if has_table("price_list_items"):
        items = bind.execute(
            sa.text(
                "SELECT company_id, price_list_id, price_category_id, price "
                "FROM price_list_items"
            )
        ).mappings().all()

    cheapest: dict[int, Decimal] = {}
    for it in items:
        cid, price = it["price_category_id"], Decimal(it["price"])
        if cid not in cheapest or price < cheapest[cid]:
            cheapest[cid] = price

    by_company: dict[int, list] = defaultdict(list)
    for cat in old_cats:
        by_company[cat["company_id"]].append(cat)

    code_of: dict[int, str] = {}
    for cats in by_company.values():
        # Cheapest first; anything never priced sorts last, then by name.
        cats.sort(
            key=lambda c: (
                c["id"] not in cheapest,
                cheapest.get(c["id"], Decimal("0")),
                (c["name"] or "").lower(),
                c["id"],
            )
        )
        for rank, cat in enumerate(cats):
            if rank < 26 * 26:
                code_of[cat["id"]] = _code(rank)

    # --- one new row per (list, old category) that actually had a price ----
    old_by_id = {c["id"]: c for c in old_cats}
    per_list: dict[int, list] = defaultdict(list)
    for it in items:
        if it["price_category_id"] in code_of:
            per_list[it["price_list_id"]].append(it)

    insert = sa.text(
        """
        INSERT INTO price_categories
            (company_id, price_list_id, code, description, price, position, is_active)
        VALUES
            (:company_id, :price_list_id, :code, :description, :price, :position, TRUE)
        """
    )
    for list_id, list_items in per_list.items():
        list_items.sort(key=lambda i: code_of[i["price_category_id"]])
        for position, it in enumerate(list_items):
            old = old_by_id[it["price_category_id"]]
            name, desc = old["name"], old["description"]
            bind.execute(
                insert,
                {
                    "company_id": it["company_id"],
                    "price_list_id": list_id,
                    "code": code_of[it["price_category_id"]],
                    # Keep the old label — the code alone would lose it.
                    "description": f"{name} · {desc}" if desc else name,
                    "price": it["price"],
                    "position": position,
                },
            )

    # --- point products at the code, then drop the old rows and columns ----
    for old_id, code in code_of.items():
        bind.execute(
            sa.text(
                "UPDATE products SET price_category_code = :code "
                "WHERE price_category_id = :old_id"
            ),
            {"code": code, "old_id": old_id},
        )

    # The company-wide rows are superseded by the per-list ones.
    bind.execute(sa.text("DELETE FROM price_categories WHERE price_list_id IS NULL"))

    op.alter_column("price_categories", "price_list_id", nullable=False)
    op.alter_column("price_categories", "code", nullable=False)
    op.create_index(
        op.f("ix_price_categories_price_list_id"),
        "price_categories",
        ["price_list_id"],
    )
    op.create_foreign_key(
        "price_categories_price_list_id_fkey",
        "price_categories",
        "price_lists",
        ["price_list_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_price_category_name", "price_categories", type_="unique")
    op.create_unique_constraint(
        "uq_price_category_code", "price_categories", ["price_list_id", "code"]
    )
    op.drop_column("price_categories", "name")

    # Dropping the column takes its foreign key with it.
    op.drop_column("products", "price_category_id")
    if has_table("price_list_items"):
        op.drop_table("price_list_items")


def downgrade() -> None:
    """Restore the company-wide shape. Prices survive, per-list nuance does not.

    Categories that existed in several lists collapse back into one row per
    code, so a code priced differently per list keeps only its cheapest price
    as the item rows are rebuilt from the per-list ones.
    """
    if not has_column("price_categories", "price_list_id"):
        return

    bind = op.get_bind()

    op.create_table(
        "price_list_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("price_list_id", sa.Integer(), nullable=False),
        sa.Column("price_category_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_list_id"], ["price_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["price_category_id"], ["price_categories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "price_list_id", "price_category_id", name="uq_price_list_category"
        ),
    )
    op.create_index(
        op.f("ix_price_list_items_company_id"), "price_list_items", ["company_id"]
    )

    steps = bind.execute(
        sa.text(
            "SELECT id, company_id, price_list_id, code, description, price "
            "FROM price_categories ORDER BY company_id, position, id"
        )
    ).mappings().all()

    op.add_column("price_categories", sa.Column("name", sa.String(length=80), nullable=True))

    # One surviving category row per (company, code); the rest become items.
    keeper: dict[tuple[int, str], int] = {}
    for step in steps:
        key = (step["company_id"], step["code"])
        if key not in keeper:
            keeper[key] = step["id"]
            bind.execute(
                sa.text("UPDATE price_categories SET name = :name WHERE id = :id"),
                {"name": step["code"], "id": step["id"]},
            )
    for step in steps:
        bind.execute(
            sa.text(
                "INSERT INTO price_list_items "
                "(company_id, price_list_id, price_category_id, price) "
                "VALUES (:company_id, :price_list_id, :category_id, :price)"
            ),
            {
                "company_id": step["company_id"],
                "price_list_id": step["price_list_id"],
                "category_id": keeper[(step["company_id"], step["code"])],
                "price": step["price"],
            },
        )
    surviving = tuple(keeper.values())
    bind.execute(
        sa.text("DELETE FROM price_categories WHERE id NOT IN :ids").bindparams(
            sa.bindparam("ids", value=surviving or (0,), expanding=True)
        )
    )

    op.add_column(
        "products", sa.Column("price_category_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_products_price_category_id", "products", "price_categories",
        ["price_category_id"], ["id"], ondelete="SET NULL",
    )
    bind.execute(
        sa.text(
            "UPDATE products p SET price_category_id = c.id FROM price_categories c "
            "WHERE c.company_id = p.company_id AND c.name = p.price_category_code"
        )
    )

    op.alter_column("price_categories", "name", nullable=False)
    op.drop_constraint("uq_price_category_code", "price_categories", type_="unique")
    op.create_unique_constraint(
        "uq_price_category_name", "price_categories", ["company_id", "name"]
    )
    op.drop_constraint(
        "price_categories_price_list_id_fkey", "price_categories", type_="foreignkey"
    )
    op.drop_index(op.f("ix_price_categories_price_list_id"), "price_categories")
    op.drop_column("price_categories", "position")
    op.drop_column("price_categories", "price")
    op.drop_column("price_categories", "code")
    op.drop_column("price_categories", "price_list_id")
    op.drop_column("products", "price_category_code")
    op.drop_column("price_lists", "currency")
