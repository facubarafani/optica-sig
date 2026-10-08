"""facturación electrónica: the link to arca-api and the comprobantes issued

``arca_issuers`` maps a company to the arca-api issuer it invoices as;
``invoices`` holds each factura and nota de crédito a sale gets. Three columns
feed them: the buyer's IVA condition (A or B), the alícuota per product type,
and the punto de venta per branch. See services/invoicing.py.

The enum-like columns are plain strings (IvaCondition, IvaRate, InvoiceType,
InvoiceStatus), like currency: ARCA's lists grow, and a Postgres enum would
make each new value a migration.

Defensive per CLAUDE.md: 0001 is metadata-derived, so a fresh database already
has the tables and columns by the time it lands here.

Revision ID: 0020_invoicing
Revises: 0019_bulk_delete_permission
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_column, has_table

revision = "0020_invoicing"
down_revision = "0019_bulk_delete_permission"
branch_labels = None
depends_on = None

COLUMNS = (
    ("customers", sa.Column("iva_condition", sa.String(length=40), nullable=True)),
    ("product_types", sa.Column("iva_rate", sa.String(length=8), nullable=True)),
    ("branches", sa.Column("point_of_sale", sa.Integer(), nullable=True)),
)


def upgrade() -> None:
    for table, column in COLUMNS:
        if has_table(table) and not has_column(table, column.name):
            op.add_column(table, column)

    if not has_table("arca_issuers"):
        op.create_table(
            "arca_issuers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("issuer_id", sa.String(length=40), nullable=False),
            sa.Column("cuit", sa.String(length=11), nullable=False),
            sa.Column("legal_name", sa.String(length=200), nullable=False),
            sa.Column("iva_condition", sa.String(length=40), nullable=False),
            sa.Column("point_of_sale", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", name="uq_arca_issuer_company"),
            sa.UniqueConstraint("issuer_id", name="uq_arca_issuer_issuer"),
        )
        op.create_index(op.f("ix_arca_issuers_company_id"), "arca_issuers",
                        ["company_id"])

    if not has_table("invoices"):
        op.create_table(
            "invoices",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("sale_id", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("credited_invoice_id", sa.Integer(), nullable=True),
            sa.Column("arca_issuer_id", sa.String(length=40), nullable=False),
            sa.Column("idempotency_key", sa.String(length=100), nullable=False),
            sa.Column("request_body", sa.Text(), nullable=False),
            sa.Column("point_of_sale", sa.Integer(), nullable=False),
            sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column("arca_invoice_id", sa.String(length=40), nullable=True),
            sa.Column("number", sa.Integer(), nullable=True),
            sa.Column("formatted_number", sa.String(length=20), nullable=True),
            sa.Column("issue_date", sa.Date(), nullable=True),
            sa.Column("cae", sa.String(length=20), nullable=True),
            sa.Column("cae_due_date", sa.Date(), nullable=True),
            sa.Column("error", sa.String(length=1000), nullable=True),
            sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["credited_invoice_id"], ["invoices.id"],
                                    ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"],
                                    ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "idempotency_key", name="uq_invoice_key"),
        )
        op.create_index(op.f("ix_invoices_company_id"), "invoices", ["company_id"])
        op.create_index(op.f("ix_invoices_sale_id"), "invoices", ["sale_id"])
        op.create_index(op.f("ix_invoices_status"), "invoices", ["status"])


def downgrade() -> None:
    if has_table("invoices"):
        op.drop_table("invoices")
    if has_table("arca_issuers"):
        op.drop_table("arca_issuers")
    for table, column in COLUMNS:
        if has_column(table, column.name):
            op.drop_column(table, column.name)
