"""payment reminders sent by WhatsApp

``payment_reminders`` holds one row per WhatsApp message a seller opened for a
customer who owes on a sale: the tone, the number it went to, the text, who
and when. See services/payment_reminders.py.

``tone`` is a plain string (ReminderTone), like the invoicing lists: a new tone
is one more message to write, not a migration.

Defensive per CLAUDE.md: 0001 is metadata-derived, so a fresh database already
has the table by the time it lands here.

Revision ID: 0023_payment_reminders
Revises: 0022_card_kinds
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0023_payment_reminders"
down_revision = "0022_card_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if has_table("payment_reminders"):
        return
    op.create_table(
        "payment_reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("tone", sa.String(length=20), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sent_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payment_reminders_company_id"), "payment_reminders",
                    ["company_id"])
    op.create_index(op.f("ix_payment_reminders_sale_id"), "payment_reminders",
                    ["sale_id"])


def downgrade() -> None:
    if has_table("payment_reminders"):
        op.drop_table("payment_reminders")
