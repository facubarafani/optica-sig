"""tarjeta de crédito y de débito, cuotas y recargo por financiación

* ``payment_method`` loses ``CARD`` and gains ``CREDIT_CARD`` and
  ``DEBIT_CARD``: a tarjeta is always one or the other now. Postgres cannot
  drop an enum label, so the type is rebuilt; a ``CARD`` row (payment or
  account) becomes ``CREDIT_CARD``, the closest to a posnet that takes both.
* ``sale_payments.installments`` and ``surcharge_amount``: the cuotas of a
  credit-card payment and the recargo inside its amount.
* ``sales.surcharge_amount``: the sale's recargo, part of its total.
* ``installment_rates``: each account's recargo per number of cuotas.

Defensive per CLAUDE.md: 0001 is metadata-derived, so a fresh database
already has all of this by the time it lands here.

Revision ID: 0022_card_kinds
Revises: 0021_invoicing_requests
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column, has_table

revision = "0022_card_kinds"
down_revision = "0021_invoicing_requests"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(12, 2)
# Enum names, not values (rule 7).
LABELS = ("CASH", "TRANSFER", "CREDIT_CARD", "DEBIT_CARD")
COLUMNS = (("sale_payments", "method"), ("payment_accounts", "method"))


def _has_card_label(bind) -> bool:
    return bind.execute(sa.text(
        "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = 'payment_method' AND e.enumlabel = 'CARD'"
    )).first() is not None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and _has_card_label(bind):
        op.execute("ALTER TYPE payment_method RENAME TO payment_method_old")
        labels = ", ".join(f"'{label}'" for label in LABELS)
        op.execute(f"CREATE TYPE payment_method AS ENUM ({labels})")
        for table, column in COLUMNS:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE payment_method "
                f"USING (CASE {column}::text WHEN 'CARD' THEN 'CREDIT_CARD' "
                f"ELSE {column}::text END)::payment_method"
            )
        op.execute("DROP TYPE payment_method_old")

    if not has_column("sale_payments", "installments"):
        op.add_column("sale_payments", sa.Column("installments", sa.Integer(), nullable=True))
    if not has_column("sale_payments", "surcharge_amount"):
        op.add_column("sale_payments", sa.Column(
            "surcharge_amount", MONEY, server_default="0", nullable=False))
    if not has_column("sales", "surcharge_amount"):
        op.add_column("sales", sa.Column(
            "surcharge_amount", MONEY, server_default="0", nullable=False))

    if not has_table("installment_rates"):
        op.create_table(
            "installment_rates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("installments", sa.Integer(), nullable=False),
            sa.Column("surcharge_percent", sa.Numeric(6, 2), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["account_id"], ["payment_accounts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "installments", name="uq_installment_rate"),
        )
        op.create_index(op.f("ix_installment_rates_company_id"), "installment_rates",
                        ["company_id"])
        op.create_index(op.f("ix_installment_rates_account_id"), "installment_rates",
                        ["account_id"])


def downgrade() -> None:
    # The enum keeps its new labels: which card a CARD row was is lost anyway.
    if has_table("installment_rates"):
        op.drop_table("installment_rates")
    for table, column in (("sales", "surcharge_amount"),
                          ("sale_payments", "surcharge_amount"),
                          ("sale_payments", "installments")):
        if has_column(table, column):
            op.drop_column(table, column)
