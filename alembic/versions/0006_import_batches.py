"""staged bulk-import batches

An upload is staged here so preview and commit work on the same parsed data
without re-uploading, and so there is a history of what was imported.

``headers``/``rows``/``mapping``/``result`` hold JSON in plain Text columns, not
JSONB: the test suite runs on SQLite and the schema must stay portable.

Revision ID: 0006_import_batches
Revises: 0005_product_selling_price
Create Date: 2026-07-26
"""
import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0006_import_batches"
down_revision = "0005_product_selling_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # See app/core/migration_utils.py.
    if has_table("import_batches"):
        return
    op.create_table(
        "import_batches",
        sa.Column("spec_key", sa.String(length=40), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("headers", sa.Text(), nullable=False),
        sa.Column("rows", sa.Text(), nullable=False),
        sa.Column("mapping", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_import_batches_company_id"),
        "import_batches",
        ["company_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_import_batches_company_id"), table_name="import_batches")
    op.drop_table("import_batches")
