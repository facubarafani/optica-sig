"""Seed an empty (migrated) database with demo master data.

    python -m scripts.seed

Idempotent-ish: safe to re-run on the same DB (looks up by natural keys).
Creates: company + settings, permission catalogue, admin & salesperson roles,
an admin user, two branches, catalog data, a price list with prices, a few
products with stock, one customer, and the document number sequences.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.audit import NumberSequence
from app.models.auth import Permission, Role, User
from app.models.branch import Branch
from app.models.company import Company, CompanySettings
from app.models.customer import Customer
from app.models.enums import StockMovementType, SupplierType
from app.models.pricing import PriceCategory, PriceList, PriceListItem
from app.models.product import Brand, Product, ProductType
from app.models.supplier import Supplier
from app.schemas.stock import StockMovementCreate
from app.services import numbering, stock as stock_service

PERMISSIONS: list[tuple[str, str]] = [
    ("company:read", "View company & settings"),
    ("company:write", "Edit company & settings"),
    ("users:read", "View users, roles, permissions"),
    ("users:write", "Manage users & roles"),
    ("branches:read", "View branches"),
    ("branches:write", "Manage branches"),
    ("suppliers:read", "View suppliers"),
    ("suppliers:write", "Manage suppliers"),
    ("products:read", "View products & catalog"),
    ("products:write", "Manage products & costs"),
    ("pricing:read", "View prices & lists"),
    ("pricing:write", "Manage prices & lists"),
    ("stock:read", "View stock levels & movements"),
    ("stock:write", "Create stock movements"),
    ("customers:read", "View customers"),
    ("customers:write", "Manage customers"),
]

SALESPERSON_PERMS = {
    "products:read", "pricing:read", "stock:read", "stock:write",
    "customers:read", "customers:write", "branches:read", "suppliers:read",
}


def get_or_create(db: Session, model, defaults: dict | None = None, **filters):
    obj = db.execute(select(model).filter_by(**filters)).scalar_one_or_none()
    if obj:
        return obj, False
    obj = model(**filters, **(defaults or {}))
    db.add(obj)
    db.flush()
    return obj, True


def run() -> None:
    db = SessionLocal()
    try:
        cid = settings.default_company_id

        # --- company + settings ---
        company = db.get(Company, cid)
        if company is None:
            company = Company(
                id=cid, name="Óptica Demo", legal_name="Óptica Demo S.R.L.",
                tax_id="30-12345678-9", currency="ARS", email="demo@sgi.com",
            )
            db.add(company)
            db.flush()
        get_or_create(db, CompanySettings, company_id=cid)

        # --- permissions ---
        perms: dict[str, Permission] = {}
        for code, name in PERMISSIONS:
            p, _ = get_or_create(db, Permission, defaults={"name": name}, code=code)
            perms[code] = p

        # --- roles ---
        admin_role, _ = get_or_create(
            db, Role, defaults={"description": "Full access"},
            company_id=cid, name="Administrator",
        )
        admin_role.permissions = list(perms.values())
        sales_role, _ = get_or_create(
            db, Role, defaults={"description": "Sales floor staff"},
            company_id=cid, name="Salesperson",
        )
        sales_role.permissions = [perms[c] for c in SALESPERSON_PERMS]

        # --- admin user (superuser) ---
        admin, created = get_or_create(
            db, User,
            defaults={
                "full_name": "Administrator",
                "hashed_password": hash_password("admin1234"),
                "is_superuser": True,
            },
            company_id=cid, email="admin@sgi.com",
        )
        if created:
            admin.roles = [admin_role]

        # --- branches ---
        main_branch, _ = get_or_create(
            db, Branch, defaults={"name": "Casa Central", "address": "Av. Siempre Viva 123"},
            company_id=cid, code="MAIN",
        )
        second_branch, _ = get_or_create(
            db, Branch, defaults={"name": "Sucursal Norte"},
            company_id=cid, code="NORTE",
        )

        # --- suppliers ---
        get_or_create(
            db, Supplier,
            defaults={"supplier_type": SupplierType.MERCHANDISE, "email": "ventas@distrib.com"},
            company_id=cid, name="Distribuidora Óptica SA",
        )
        get_or_create(
            db, Supplier, defaults={"supplier_type": SupplierType.LABORATORY},
            company_id=cid, name="Laboratorio Cristal",
        )
        get_or_create(
            db, Supplier, defaults={"supplier_type": SupplierType.WORKSHOP},
            company_id=cid, name="Taller Express",
        )

        # --- catalog: product types & brands ---
        pt_frames, _ = get_or_create(db, ProductType, company_id=cid, name="Armazones")
        pt_sun, _ = get_or_create(db, ProductType, company_id=cid, name="Lentes de sol")
        pt_contact, _ = get_or_create(db, ProductType, company_id=cid, name="Lentes de contacto")
        brand_a, _ = get_or_create(db, Brand, company_id=cid, name="RayBan")
        brand_b, _ = get_or_create(db, Brand, company_id=cid, name="Vulk")

        # --- price categories + list ---
        cat_a, _ = get_or_create(db, PriceCategory, company_id=cid, name="A")
        cat_b, _ = get_or_create(db, PriceCategory, company_id=cid, name="B")
        cat_c, _ = get_or_create(db, PriceCategory, company_id=cid, name="C")
        price_list, _ = get_or_create(
            db, PriceList, defaults={"is_default": True},
            company_id=cid, name="Lista General",
        )
        db.flush()
        for cat, price in [(cat_a, "50000"), (cat_b, "30000"), (cat_c, "15000")]:
            get_or_create(
                db, PriceListItem, defaults={"price": Decimal(price)},
                company_id=cid, price_list_id=price_list.id, price_category_id=cat.id,
            )
        # point company settings at the default list
        cfg = db.execute(
            select(CompanySettings).where(CompanySettings.company_id == cid)
        ).scalar_one()
        cfg.default_price_list_id = price_list.id
        cfg.default_branch_id = main_branch.id

        # --- products ---
        products_spec = [
            ("ARM-001", "Armazón clásico negro", pt_frames, brand_a, cat_a, "20000"),
            ("SOL-001", "Lente de sol aviador", pt_sun, brand_a, cat_b, "12000"),
            ("LC-001", "Lentes de contacto mensual", pt_contact, brand_b, cat_c, "6000"),
        ]
        created_products: list[Product] = []
        for code, name, ptype, brand, cat, cost in products_spec:
            prod, was_new = get_or_create(
                db, Product,
                defaults={
                    "name": name, "product_type_id": ptype.id, "brand_id": brand.id,
                    "price_category_id": cat.id, "current_cost": Decimal(cost),
                    "min_stock": Decimal("2"),
                },
                company_id=cid, code=code,
            )
            if was_new:
                created_products.append(prod)
        db.flush()

        # --- customer ---
        get_or_create(
            db, Customer,
            defaults={"document_type": "DNI", "document_number": "30111222", "phone": "11-5555-0000"},
            company_id=cid, first_name="Juan", last_name="Pérez",
        )

        # --- document number sequences ---
        for key in (numbering.KEY_SALE, numbering.KEY_QUOTE, numbering.KEY_WORK_ORDER, numbering.KEY_REPAIR):
            get_or_create(
                db, NumberSequence,
                defaults={"prefix": numbering.DEFAULT_PREFIXES.get(key, ""), "next_value": 1, "padding": 6},
                company_id=cid, key=key,
            )

        db.commit()

        # --- initial stock via the stock service (writes movements + levels) ---
        for prod in created_products:
            stock_service.apply_movement(
                db,
                StockMovementCreate(
                    product_id=prod.id, branch_id=main_branch.id,
                    movement_type=StockMovementType.INBOUND, quantity=Decimal("10"),
                    reference="SEED", note="Initial stock",
                ),
                company_id=cid, user_id=admin.id,
            )

        print("✅ Seed complete.")
        print("   Company:", company.name, f"(id={cid})")
        print("   Admin login: admin@sgi.com / admin1234")
        print(f"   Branches: {main_branch.code}, {second_branch.code}")
        print(f"   Products seeded with stock: {len(created_products)}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
