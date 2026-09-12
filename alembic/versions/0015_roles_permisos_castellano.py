"""roles and permission labels in Spanish

The permission *code* stays English: it is the identifier ``can()`` checks.
What changes here is the text beside it and the two default role names, which
a shop owner reads and edits. New tenants already get them in Spanish from
``services.provisioning``; this brings along the ones already created.

Defensive per CLAUDE.md: a fresh database runs 0001 (metadata-derived) and then
lands here with the tables present but empty, so every statement has to be a
no-op when there is nothing to rename.

Revision ID: 0015_roles_permisos_castellano
Revises: 0014_starter_product_types
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.migration_utils import has_table

revision = "0015_roles_permisos_castellano"
down_revision = "0014_starter_product_types"
branch_labels = None
depends_on = None


# code -> (texto en castellano, texto anterior en inglés)
PERMISSIONS: dict[str, tuple[str, str]] = {
    "company:read": ("Ver la empresa y su configuración", "View company & settings"),
    "company:write": ("Editar la empresa y su configuración", "Edit company & settings"),
    "users:read": ("Ver usuarios, roles y permisos", "View users, roles, permissions"),
    "users:write": ("Administrar usuarios y roles", "Manage users & roles"),
    "branches:read": ("Ver sucursales", "View branches"),
    "branches:write": ("Administrar sucursales", "Manage branches"),
    "suppliers:read": ("Ver proveedores", "View suppliers"),
    "suppliers:write": ("Administrar proveedores", "Manage suppliers"),
    "products:read": ("Ver productos y catálogo", "View products & catalog"),
    "products:write": ("Administrar productos y costos", "Manage products & costs"),
    "pricing:read": ("Ver precios y listas", "View prices & lists"),
    "pricing:write": ("Administrar precios y listas", "Manage prices & lists"),
    "stock:read": ("Ver stock y movimientos", "View stock levels & movements"),
    "stock:write": ("Registrar movimientos de stock", "Create stock movements"),
    "customers:read": ("Ver clientes", "View customers"),
    "customers:write": ("Administrar clientes", "Manage customers"),
    "sales:read": ("Ver ventas y cuentas pendientes", "View sales & pending accounts"),
    "sales:write": ("Registrar ventas y pagos", "Register sales & payments"),
}

# (nombre anterior, nombre nuevo, descripción anterior, descripción nueva)
ROLES = [
    ("Administrator", "Administrador", "Full access", "Acceso total"),
    ("Salesperson", "Vendedor", "Sales floor staff", "Atención en el mostrador"),
]


def _rename(codes_or_roles: str, forward: bool) -> None:
    bind = op.get_bind()
    if codes_or_roles == "permissions":
        for code, (es, en) in PERMISSIONS.items():
            bind.execute(
                sa.text("UPDATE permissions SET name = :new WHERE code = :code AND name = :old"),
                {"new": es if forward else en, "old": en if forward else es, "code": code},
            )
        return
    for old_name, new_name, old_desc, new_desc in ROLES:
        # Sólo se renombra el rol que quedó tal como lo creó el sistema. Si una
        # óptica ya lo renombró a mano, ese nombre es de ella y no se toca.
        bind.execute(
            sa.text(
                "UPDATE roles SET name = :new_name, description = :new_desc "
                "WHERE name = :old_name"
            ),
            {
                "new_name": new_name if forward else old_name,
                "new_desc": new_desc if forward else old_desc,
                "old_name": old_name if forward else new_name,
            },
        )


def upgrade() -> None:
    if has_table("permissions"):
        _rename("permissions", forward=True)
    if has_table("roles"):
        _rename("roles", forward=True)


def downgrade() -> None:
    if has_table("roles"):
        _rename("roles", forward=False)
    if has_table("permissions"):
        _rename("permissions", forward=False)
