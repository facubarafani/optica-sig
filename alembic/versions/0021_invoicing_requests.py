"""what a shop declares in its facturación electrónica guide

``invoicing_requests`` holds one row per company: the data the shop enters
while it does its steps at ARCA, and when it sent them. We activate it from
/admin, which creates the ``arca_issuers`` link. See services/invoicing.py.

Defensive per CLAUDE.md: 0001 is metadata-derived, so a fresh database already
has the table by the time it lands here.

Revision ID: 0021_invoicing_requests
Revises: 0020_invoicing
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0021_invoicing_requests"
down_revision = "0020_invoicing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if has_table("invoicing_requests"):
        return
    op.create_table(
        "invoicing_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("cuit", sa.String(length=11), nullable=True),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("iva_condition", sa.String(length=40), nullable=True),
        sa.Column("point_of_sale", sa.Integer(), nullable=True),
        sa.Column("commercial_address", sa.String(length=250), nullable=True),
        sa.Column("gross_income_tax", sa.String(length=60), nullable=True),
        sa.Column("activity_start_date", sa.Date(), nullable=True),
        sa.Column("trade_name", sa.String(length=200), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("provider_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", name="uq_invoicing_request_company"),
    )
    op.create_index(op.f("ix_invoicing_requests_company_id"), "invoicing_requests",
                    ["company_id"])


def downgrade() -> None:
    if has_table("invoicing_requests"):
        op.drop_table("invoicing_requests")
