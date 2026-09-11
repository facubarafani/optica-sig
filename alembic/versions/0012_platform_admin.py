"""platform identity: provider users and their cross-tenant audit trail

The provider (us) gets its own identity table rather than a flag on ``users``.
A tenant user always carries a company_id; a platform user carries none and
works across every shop. Separate tables mean the two token scopes in
``app.core.deps`` can refuse each other structurally, instead of relying on
every future router remembering a check.

Revision ID: 0012_platform_admin
Revises: 0011_product_variants
Create Date: 2026-09-05
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0012_platform_admin"
down_revision = "0011_product_variants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001_initial builds the schema from Base.metadata, so a database created
    # after this change already has both tables. See app/core/migration_utils.py.
    if not has_table("platform_users"):
        op.create_table(
            "platform_users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(length=150), nullable=False),
            sa.Column("full_name", sa.String(length=150), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
        op.create_index(
            op.f("ix_platform_users_email"), "platform_users", ["email"], unique=False
        )

    if not has_table("platform_audit_log"):
        op.create_table(
            "platform_audit_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("platform_user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("target_user_id", sa.Integer(), nullable=True),
            sa.Column("detail", sa.String(length=500), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["platform_user_id"], ["platform_users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_platform_audit_log_platform_user_id"),
            "platform_audit_log", ["platform_user_id"], unique=False,
        )
        op.create_index(
            op.f("ix_platform_audit_log_action"),
            "platform_audit_log", ["action"], unique=False,
        )
        op.create_index(
            op.f("ix_platform_audit_log_company_id"),
            "platform_audit_log", ["company_id"], unique=False,
        )
        op.create_index(
            op.f("ix_platform_audit_log_created_at"),
            "platform_audit_log", ["created_at"], unique=False,
        )


def downgrade() -> None:
    if has_table("platform_audit_log"):
        op.drop_table("platform_audit_log")
    if has_table("platform_users"):
        op.drop_table("platform_users")
