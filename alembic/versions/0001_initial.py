"""initial schema — master-data backbone

Creates the full schema directly from ``Base.metadata`` so the initial revision
can never drift from the models. **All subsequent migrations must use
``alembic revision --autogenerate``** and explicit ``op`` calls.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15
"""
from alembic import op

from app.core.database import Base

# Importing the models package populates Base.metadata with every table.
import app.models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
