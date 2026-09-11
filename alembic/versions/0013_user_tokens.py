"""one-time links for invitations and password resets

Stores only a SHA-256 of each token: the raw value lives in the email and
nowhere else, so a leaked database cannot be replayed into account access.

Revision ID: 0013_user_tokens
Revises: 0012_platform_admin
Create Date: 2026-09-05
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0013_user_tokens"
down_revision = "0012_platform_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001_initial builds from Base.metadata, so a fresh database already has
    # this table. See app/core/migration_utils.py.
    if has_table("user_tokens"):
        return
    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_user_tokens_user_id"), "user_tokens", ["user_id"])
    op.create_index(op.f("ix_user_tokens_token_hash"), "user_tokens", ["token_hash"])


def downgrade() -> None:
    if has_table("user_tokens"):
        op.drop_table("user_tokens")
