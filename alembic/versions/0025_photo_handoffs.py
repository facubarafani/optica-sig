"""photos on their way from a phone to the PC (the receta scanner)

``photo_handoffs`` holds a photo for the minutes between the phone uploading it
and the PC fetching it: the PC deletes the row as soon as it has the photo,
and anything older than half an hour is swept. See services/handoffs.py.

Defensive per CLAUDE.md: 0001 is metadata-derived, so a fresh database already
has the table by the time it lands here.

Revision ID: 0025_photo_handoffs
Revises: 0024_reports_permission
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0025_photo_handoffs"
down_revision = "0024_reports_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if has_table("photo_handoffs"):
        return
    op.create_table(
        "photo_handoffs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("photo", sa.LargeBinary(), nullable=True),
        sa.Column("photo_type", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_photo_handoffs_company_id"), "photo_handoffs", ["company_id"])


def downgrade() -> None:
    if has_table("photo_handoffs"):
        op.drop_table("photo_handoffs")
