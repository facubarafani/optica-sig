"""permission to see how the business and each seller are doing

Inicio now comes in two: the owner's, with the whole shop's sales and a table
of how each seller is doing, and the seller's, with their own sales and what
they have to chase. ``reports:read`` decides which one a user gets, and the
shop-wide figures (``GET /api/sales/stats``) now ask for it instead of
``sales:read``. Existing shops grant it to the roles that already manage users
(their Administrador); a Vendedor keeps ``sales:read`` and gets the seller's
Inicio. New shops get it through provisioning, whose admin role holds every
permission.

Defensive per CLAUDE.md: on a fresh database the permissions table exists but
is empty until provisioning runs, so the grant simply finds no roles.

Revision ID: 0024_reports_permission
Revises: 0023_payment_reminders
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0024_reports_permission"
down_revision = "0023_payment_reminders"
branch_labels = None
depends_on = None

CODE = "reports:read"
NAME = "Ver el rendimiento del negocio y de cada vendedor"


def upgrade() -> None:
    if not has_table("permissions"):
        return
    bind = op.get_bind()
    pid = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :code"),
                       {"code": CODE}).scalar()
    if pid is None:
        pid = bind.execute(
            sa.text("INSERT INTO permissions (code, name) VALUES (:code, :name) RETURNING id"),
            {"code": CODE, "name": NAME},
        ).scalar()
    if has_table("role_permissions"):
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT DISTINCT rp.role_id, :pid FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE p.code = 'users:write' AND NOT EXISTS ("
                "  SELECT 1 FROM role_permissions x "
                "  WHERE x.role_id = rp.role_id AND x.permission_id = :pid)"
            ),
            {"pid": pid},
        )


def downgrade() -> None:
    if not has_table("permissions"):
        return
    bind = op.get_bind()
    pid = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :code"),
                       {"code": CODE}).scalar()
    if pid is None:
        return
    if has_table("role_permissions"):
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :pid"),
                     {"pid": pid})
    bind.execute(sa.text("DELETE FROM permissions WHERE id = :pid"), {"pid": pid})
