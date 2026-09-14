"""Bringing a new tenant into being.

Everything a brand-new óptica needs before its first login: the company row,
its settings, the permission catalogue, the two default roles, an admin user,
a branch, a colour palette, a default price list, somewhere for money to land
and the document counters.

This used to live inline in ``scripts/seed.py``. It is a service now because
two callers need it — the seed and ``POST /api/admin/tenants`` — and a tenant
created from the admin console must be indistinguishable from a seeded one.
Anything a shop cannot create for itself through the UI belongs here; demo
products and customers do not, and stayed in the seed.

The whole thing is one transaction (``commit=False`` in spirit, like the sales
and import services): a tenant is either fully provisioned or not created at
all. A half-built company with no roles is worse than no company.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.audit import NumberSequence
from app.models.auth import Permission, Role, User
from app.models.branch import Branch
from app.models.company import Company, CompanySettings
from app.models.enums import PaymentMethod
from app.models.pricing import PriceCategory, PriceList
from app.models.product import Color, ProductType
from app.models.sales import PaymentAccount
from app.services import invitations, numbering, pricing
from app.services import products as products_service


class ProvisioningError(Exception):
    """Raised when a tenant cannot be created."""


# The permission catalogue is global (``permissions`` has no company_id), so
# it is created once and every tenant's roles point at the same rows.
# The code is an identifier and stays English (see CLAUDE.md, rule 1): it is
# what ``can("products:write")`` checks. The text beside it is not an
# identifier, it is the line a shop owner reads when handing out permissions,
# so it goes in Spanish like every other user-facing string.
PERMISSIONS: list[tuple[str, str]] = [
    ("company:read", "Ver la empresa y su configuración"),
    ("company:write", "Editar la empresa y su configuración"),
    ("users:read", "Ver usuarios, roles y permisos"),
    ("users:write", "Administrar usuarios y roles"),
    ("branches:read", "Ver sucursales"),
    ("branches:write", "Administrar sucursales"),
    ("suppliers:read", "Ver proveedores"),
    ("suppliers:write", "Administrar proveedores"),
    ("products:read", "Ver productos y catálogo"),
    ("products:write", "Administrar productos y costos"),
    # Separate from products:write on purpose: a spreadsheet reaches hundreds
    # of products at once (services/importer, the "Activo" column).
    ("products:bulk_delete", "Eliminar productos en masa"),
    ("pricing:read", "Ver precios y listas"),
    ("pricing:write", "Administrar precios y listas"),
    ("stock:read", "Ver stock y movimientos"),
    ("stock:write", "Registrar movimientos de stock"),
    ("customers:read", "Ver clientes"),
    ("customers:write", "Administrar clientes"),
    ("sales:read", "Ver ventas y cuentas pendientes"),
    ("sales:write", "Registrar ventas y pagos"),
]

SALESPERSON_PERMS = {
    "products:read", "pricing:read", "stock:read", "stock:write",
    "customers:read", "customers:write", "branches:read", "suppliers:read",
    "sales:read", "sales:write",
}

# El nombre del rol es un dato que la óptica ve y edita, no un identificador:
# va en castellano. Nada en el código compara contra él (los permisos se
# chequean por código), así que renombrarlo es seguro; lo único que hace falta
# es que las instalaciones que ya existen se renombren, de eso se ocupa 0015.
ADMIN_ROLE = "Administrador"
SALESPERSON_ROLE = "Vendedor"

# A starter palette so the colour dropdown is not empty on day one. These are
# the shades an optics shop actually stocks; the shop edits the list freely.
STARTER_COLORS: list[tuple[str, str]] = [
    ("Negro", "#1a1a1a"), ("Blanco", "#f5f5f5"), ("Gris", "#8a8f98"),
    ("Marrón", "#6b4423"), ("Havana", "#8b5a2b"), ("Carey", "#7a4a1e"),
    ("Dorado", "#c9a227"), ("Plateado", "#b7bcc4"), ("Azul", "#1f4e9c"),
    ("Celeste", "#5fa8e8"), ("Verde", "#2f7a4d"), ("Rojo", "#c02b2b"),
    ("Bordó", "#7b1f2b"), ("Rosa", "#e08fa8"), ("Violeta", "#6b3fa0"),
    ("Transparente", "#e8ecf1"),
]

# ``products.product_type_id`` is NOT NULL, so a shop with an empty type list
# cannot create its first product at all — the field is required and there is
# nothing to pick. These three cover what every óptica sells; the shop renames
# or extends them freely. Brands and models stay out: both are optional on a
# product, so an empty list blocks nothing.
STARTER_PRODUCT_TYPES: list[str] = [
    "Armazones", "Lentes de sol", "Lentes de contacto",
]

# Three rungs so the ladder is usable immediately and obviously editable.
STARTER_PRICES = ["15000", "30000", "50000"]

DEFAULT_BRANCH_CODE = "MAIN"
DEFAULT_BRANCH_NAME = "Casa Central"
DEFAULT_PRICE_LIST = "Lista General"
DEFAULT_CASH_ACCOUNT = "Efectivo caja"


def _get_or_create(db: Session, model, defaults: dict | None = None, **filters):
    obj = db.execute(select(model).filter_by(**filters)).scalar_one_or_none()
    if obj:
        return obj, False
    obj = model(**filters, **(defaults or {}))
    db.add(obj)
    db.flush()
    return obj, True


def resync_company_sequence(db: Session) -> None:
    """Realign Postgres' id counter after a company was inserted with a fixed id.

    The seed pins the demo tenant to ``DEFAULT_COMPANY_ID``. Postgres does not
    advance the sequence for an id it was handed, so the next tenant created
    from the admin console asks for id 1 and collides with the seed. SQLite
    derives the next id from ``MAX(id)``, which is why the test suite cannot
    see this — it is a Postgres-only failure that only appears the first time
    a real tenant is onboarded.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('companies', 'id'), "
            "COALESCE((SELECT MAX(id) FROM companies), 1))"
        )
    )


def ensure_permissions(db: Session) -> dict[str, Permission]:
    """Make sure the global permission catalogue exists, and return it by code."""
    perms: dict[str, Permission] = {}
    for code, name in PERMISSIONS:
        perm, _ = _get_or_create(db, Permission, defaults={"name": name}, code=code)
        # ``defaults`` sólo corre al crear. Sin esto, cambiar el texto de un
        # permiso no llegaba nunca a una base que ya lo tenía: la fila se
        # quedaba con el texto del día que se creó.
        perm.name = name
        perms[code] = perm
    return perms


def ensure_default_roles(db: Session, company_id: int) -> tuple[Role, Role]:
    """Create (or refresh) the two roles every shop starts with.

    Re-running this re-points the roles at the current catalogue, so adding a
    permission code does not leave existing tenants' Administrator role short
    of it.
    """
    perms = ensure_permissions(db)
    admin_role, _ = _get_or_create(
        db, Role, defaults={"description": "Acceso total"},
        company_id=company_id, name=ADMIN_ROLE,
    )
    admin_role.permissions = list(perms.values())
    sales_role, _ = _get_or_create(
        db, Role, defaults={"description": "Atención en el mostrador"},
        company_id=company_id, name=SALESPERSON_ROLE,
    )
    sales_role.permissions = [perms[c] for c in SALESPERSON_PERMS]
    db.flush()
    return admin_role, sales_role


def provision_company_defaults(db: Session, company_id: int) -> Branch:
    """The master data a shop needs before it can sell anything.

    Returns the main branch, which the caller points company settings at.
    """
    # --- branch ---
    branch, _ = _get_or_create(
        db, Branch, defaults={"name": DEFAULT_BRANCH_NAME},
        company_id=company_id, code=DEFAULT_BRANCH_CODE,
    )

    # --- product types (without one, no product can be created) ---
    for type_name in STARTER_PRODUCT_TYPES:
        _get_or_create(db, ProductType, company_id=company_id, name=type_name)
    db.flush()

    # --- colours (each needs the short code that ends up in ARM-001-HAV) ---
    for name, hex_code in STARTER_COLORS:
        color, was_new = _get_or_create(
            db, Color, defaults={"hex_code": hex_code},
            company_id=company_id, name=name,
        )
        if was_new:
            db.flush()
            color.code = products_service.derive_color_code(
                db, name, company_id=company_id
            )
    db.flush()

    # --- default price list + its category ladder ---
    price_list, _ = _get_or_create(
        db, PriceList, defaults={"is_default": True, "currency": "ARS"},
        company_id=company_id, name=DEFAULT_PRICE_LIST,
    )
    db.flush()
    for position, price in enumerate(STARTER_PRICES):
        _get_or_create(
            db, PriceCategory,
            defaults={"price": Decimal(price), "position": position},
            company_id=company_id, price_list_id=price_list.id,
            code=pricing.category_code(position),
        )

    # --- somewhere for money to land ---
    _get_or_create(
        db, PaymentAccount, defaults={"method": PaymentMethod.CASH},
        company_id=company_id, name=DEFAULT_CASH_ACCOUNT,
    )

    # --- document counters (never invent a number without one) ---
    for key in (
        numbering.KEY_SALE, numbering.KEY_QUOTE,
        numbering.KEY_WORK_ORDER, numbering.KEY_REPAIR,
    ):
        _get_or_create(
            db, NumberSequence,
            defaults={
                "prefix": numbering.DEFAULT_PREFIXES.get(key, ""),
                "next_value": 1,
                "padding": 6,
            },
            company_id=company_id, key=key,
        )

    # --- point settings at what we just made ---
    cfg, _ = _get_or_create(db, CompanySettings, company_id=company_id)
    cfg.default_price_list_id = price_list.id
    cfg.default_branch_id = branch.id
    db.flush()
    return branch


def create_tenant(
    db: Session,
    *,
    name: str,
    admin_email: str,
    admin_password: str | None = None,
    admin_full_name: str = "Administrador",
    legal_name: str | None = None,
    tax_id: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    currency: str = "ARS",
    company_id: int | None = None,
    commit: bool = True,
) -> tuple[Company, User]:
    """Create a company and its first admin user, fully set up.

    ``company_id`` is only for the seed, which pins the demo tenant to
    ``DEFAULT_COMPANY_ID``; the admin console lets the database assign one.

    Omit ``admin_password`` to create the owner with no usable password — the
    caller is then responsible for emailing them an invitation.
    """
    if not name.strip():
        raise ProvisioningError("El nombre de la empresa es obligatorio.")

    company = Company(
        name=name.strip(),
        legal_name=legal_name,
        tax_id=tax_id,
        email=email,
        phone=phone,
        address=address,
        currency=currency,
    )
    if company_id is not None:
        company.id = company_id
    db.add(company)
    db.flush()
    if company_id is not None:
        resync_company_sequence(db)

    admin_role, _ = ensure_default_roles(db, company.id)
    branch = provision_company_defaults(db, company.id)

    # The first user is a superuser *within this company*: they must be able to
    # create the rest of the staff without us being involved.
    admin = User(
        company_id=company.id,
        email=admin_email.strip().lower(),
        full_name=admin_full_name.strip() or "Administrador",
        hashed_password="",
        is_superuser=True,
        branch_id=branch.id,
        roles=[admin_role],
    )
    if admin_password:
        admin.hashed_password = hash_password(admin_password)
    else:
        # No password given: the caller is going to email an invitation. The
        # account exists and is listable, but nothing anyone can type opens it
        # until that link is used.
        invitations.set_unusable_password(admin)
    db.add(admin)
    db.flush()

    if commit:
        db.commit()
        db.refresh(company)
        db.refresh(admin)
    return company, admin
