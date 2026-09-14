"""operation journal: what each request changed, for undo and redo

``operations`` is one row per undoable write request; ``operation_changes``
holds each touched row's columns before and after. See services/journal.py.

Defensive per CLAUDE.md: 0001 is metadata-derived, so a fresh database already
has both tables by the time it lands here.

Revision ID: 0018_operation_journal
Revises: 0017_product_multicolor
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.migration_utils import has_table

revision = "0018_operation_journal"
down_revision = "0017_product_multicolor"
branch_labels = None
depends_on = None

# Member names, as SQLAlchemy stores them (CLAUDE.md rule 7). Created up front
# and referenced with create_type=False, as in 0016.
LABELS = ("CREATE", "UPDATE")
ACTION = postgresql.ENUM(*LABELS, name="change_action")


def upgrade() -> None:
    if not has_table("operations"):
        op.create_table(
            "operations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("area", sa.String(length=40), nullable=False),
            sa.Column("method", sa.String(length=10), nullable=False),
            sa.Column("path", sa.String(length=200), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False,
                      server_default=""),
            sa.Column("change_count", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("import_batch_id", sa.Integer(), nullable=True),
            sa.Column("reverts_id", sa.Integer(), nullable=True),
            sa.Column("reverted_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"],
                                    ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reverts_id"], ["operations.id"],
                                    ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reverted_by_id"], ["operations.id"],
                                    ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_operations_company_id"), "operations", ["company_id"])
        op.create_index(op.f("ix_operations_user_id"), "operations", ["user_id"])
        op.create_index(op.f("ix_operations_created_at"), "operations", ["created_at"])

    if not has_table("operation_changes"):
        ACTION.create(op.get_bind(), checkfirst=True)
        op.create_table(
            "operation_changes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("operation_id", sa.Integer(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("entity_type", sa.String(length=40), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("action", postgresql.ENUM(*LABELS, name="change_action",
                                                create_type=False), nullable=False),
            sa.Column("before", sa.Text(), nullable=True),
            sa.Column("after", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["operation_id"], ["operations.id"],
                                    ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_operation_changes_operation_id"),
                        "operation_changes", ["operation_id"])


def downgrade() -> None:
    if has_table("operation_changes"):
        op.drop_table("operation_changes")
    ACTION.drop(op.get_bind(), checkfirst=True)
    if has_table("operations"):
        op.drop_table("operations")
