"""ventas: sales, lines, payments and the accounts money lands in

The first transactional module. Shapes follow docs/ER_DIAGRAM.md (SALE /
SALE_ITEM / PAYMENT) plus discounts, the payment account and the promise-to-pay
reminder behind "cuentas pendientes".

All four tables are new, so each guard is a plain has_table: a database created
fresh by 0001 already has them (its schema comes from Base.metadata), while an
existing one gets them here.

Revision ID: 0009_sales
Revises: 0008_product_colors
Create Date: 2026-08-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.migration_utils import has_table

revision = "0009_sales"
down_revision = "0008_product_colors"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(12, 2)

# SQLAlchemy stores enum *names* (CLAUDE.md rule 7), so server defaults and the
# labels below are the names, not the values.
ENUMS = {
    "sale_status": ("QUOTE", "CONFIRMED", "PENDING", "DELIVERED", "CANCELLED"),
    "payment_method": ("CASH", "TRANSFER", "CARD"),
    "discount_type": ("AMOUNT", "PERCENT"),
}


def _enum(name: str) -> postgresql.ENUM:
    """Reference a type that upgrade() has already created.

    Unlike ``op.add_column`` (see 0005), ``op.create_table`` emits its own
    CREATE TYPE for every enum column — so two tables sharing ``discount_type``
    would try to create it twice and the second fails. ``create_type=False``
    says "it exists, just use it", which is why the types are created up front.
    """
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    # Create every shared type once, before any table references it.
    for name, labels in ENUMS.items():
        sa.Enum(*labels, name=name).create(bind, checkfirst=True)
    sale_status = _enum("sale_status")
    payment_method = _enum("payment_method")
    discount_type = _enum("discount_type")

    if not has_table("payment_accounts"):
        op.create_table(
            "payment_accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("method", payment_method, nullable=True),
            sa.Column("notes", sa.String(length=255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "name",
                                name="uq_payment_account_name"),
        )
        op.create_index("ix_payment_accounts_company_id", "payment_accounts",
                        ["company_id"])

    if not has_table("sales"):
        op.create_table(
            "sales",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("number", sa.String(length=20), nullable=False),
            sa.Column("status", sale_status, nullable=False,
                      server_default="CONFIRMED"),
            sa.Column("sold_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column("branch_id", sa.Integer(), nullable=True),
            sa.Column("salesperson_id", sa.Integer(), nullable=True),
            sa.Column("subtotal", MONEY, nullable=False),
            sa.Column("discount_type", discount_type, nullable=True),
            sa.Column("discount_value", MONEY, nullable=True),
            sa.Column("discount_amount", MONEY, nullable=False),
            sa.Column("total", MONEY, nullable=False),
            sa.Column("paid_amount", MONEY, nullable=False),
            sa.Column("balance", MONEY, nullable=False),
            sa.Column("promised_payment_date", sa.Date(), nullable=True),
            sa.Column("reminder_note", sa.String(length=255), nullable=True),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"],
                                    ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["branch_id"], ["branches.id"],
                                    ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["salesperson_id"], ["users.id"],
                                    ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "number", name="uq_sale_number"),
        )
        op.create_index("ix_sales_company_id", "sales", ["company_id"])
        op.create_index("ix_sales_customer_id", "sales", ["customer_id"])
        # The cuentas-pendientes screen sorts and filters on this.
        op.create_index("ix_sales_promised_payment_date", "sales",
                        ["promised_payment_date"])

    if not has_table("sale_items"):
        op.create_table(
            "sale_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("sale_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("quantity", MONEY, nullable=False),
            sa.Column("unit_price", MONEY, nullable=False),
            sa.Column("price_overridden", sa.Boolean(), nullable=False,
                      server_default=sa.text("false")),
            sa.Column("discount_type", discount_type, nullable=True),
            sa.Column("discount_value", MONEY, nullable=True),
            sa.Column("discount_amount", MONEY, nullable=False),
            sa.Column("line_total", MONEY, nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sale_items_company_id", "sale_items", ["company_id"])
        op.create_index("ix_sale_items_sale_id", "sale_items", ["sale_id"])
        op.create_index("ix_sale_items_product_id", "sale_items", ["product_id"])

    if not has_table("sale_payments"):
        op.create_table(
            "sale_payments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("sale_id", sa.Integer(), nullable=False),
            sa.Column("amount", MONEY, nullable=False),
            sa.Column("method", payment_method, nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("reference", sa.String(length=80), nullable=True),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["account_id"], ["payment_accounts.id"],
                                    ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"],
                                    ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sale_payments_company_id", "sale_payments",
                        ["company_id"])
        op.create_index("ix_sale_payments_sale_id", "sale_payments", ["sale_id"])


def downgrade() -> None:
    op.drop_table("sale_payments")
    op.drop_table("sale_items")
    op.drop_table("sales")
    op.drop_table("payment_accounts")
    bind = op.get_bind()
    for name in ENUMS:
        sa.Enum(name=name).drop(bind, checkfirst=True)
