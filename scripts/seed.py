"""Seed an empty (migrated) database with demo master data.

    python -m scripts.seed

Idempotent-ish: safe to re-run on the same DB (looks up by natural keys).

The tenant itself — company, settings, permissions, roles, admin user, branch,
colour palette, price list, cash account, number sequences — is built by
``services.provisioning``, the same code path ``POST /api/admin/tenants`` uses,
so a seeded shop and an onboarded shop are identical. What stays here is the
*demo* data a real shop would never want: suppliers, brands, products, a
customer and some stock.

Also creates the provider (platform) account for the /admin console.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.auth import User
from app.models.branch import Branch
from app.models.company import Company
from app.models.customer import Customer
from app.models.enums import PaymentMethod, StockMovementType, SupplierType
from app.models.product import Brand, Color, Product, ProductModel, ProductType
from app.models.platform import PlatformUser
from app.models.sales import PaymentAccount
from app.models.supplier import Supplier, supplier_brands
from app.schemas.stock import StockMovementCreate
from app.services import platform as platform_service
from app.services import products as products_service
from app.services import provisioning
from app.services import stock as stock_service


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

        # --- the tenant itself, through the same service the admin console
        #     uses. Re-running tops up anything a newer version added (roles
        #     gain new permission codes, defaults gain new rows). ---
        company = db.get(Company, cid)
        if company is None:
            company, admin = provisioning.create_tenant(
                db,
                name="Óptica Demo",
                legal_name="Óptica Demo S.R.L.",
                tax_id="30-12345678-9",
                email="demo@sgi.com",
                currency="ARS",
                admin_email="admin@sgi.com",
                admin_full_name="Administrator",
                admin_password="admin1234",
                company_id=cid,
                commit=False,
            )
        else:
            admin_role, _ = provisioning.ensure_default_roles(db, cid)
            provisioning.provision_company_defaults(db, cid)
            admin = db.execute(
                select(User).where(User.company_id == cid, User.email == "admin@sgi.com")
            ).scalar_one_or_none()
            if admin is None:
                raise SystemExit(
                    "Company exists but its admin user does not — refusing to guess."
                )
        db.flush()

        main_branch = db.execute(
            select(Branch).where(
                Branch.company_id == cid,
                Branch.code == provisioning.DEFAULT_BRANCH_CODE,
            )
        ).scalar_one()
        # Colours come from the starter palette; the demo products pick from it.
        colors = {
            c.name: c
            for c in db.execute(
                select(Color).where(Color.company_id == cid)
            ).scalars()
        }
        # A second branch, so transfers and per-branch stock have something to
        # demonstrate. Provisioning only creates the main one.
        second_branch, _ = get_or_create(
            db, Branch, defaults={"name": "Sucursal Norte"},
            company_id=cid, code="NORTE",
        )

        # --- suppliers ---
        supplier, _ = get_or_create(
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

        # --- product models ("Modelo": shape/style; type is optional) ---
        model_specs = [
            ("Clipper", pt_frames), ("Aviador", pt_frames), ("Redondo", None),
        ]
        models = {}
        for name, ptype in model_specs:
            models[name], _ = get_or_create(
                db, ProductModel,
                defaults={"product_type_id": ptype.id if ptype else None},
                company_id=cid, name=name,
            )
        db.flush()

        # --- suppliers → brands ---
        db.execute(delete(supplier_brands).where(supplier_brands.c.supplier_id == supplier.id))
        db.execute(
            insert(supplier_brands),
            [{"supplier_id": supplier.id, "brand_id": b.id} for b in (brand_a, brand_b)],
        )

        # --- products ---
        # A frame sold in several colours is a *style* plus one article per
        # colour: ARM-001 groups, ARM-001-NEG is what gets counted and sold.
        # LC-001 has no colour split, so it stays a plain article.
        products_spec = [
            ("ARM-001", "Armazón clásico", pt_frames, brand_a, models["Clipper"], ["Negro", "Havana", "Carey"], "AC", "20000"),
            ("SOL-001", "Lente de sol aviador", pt_sun, brand_a, models["Aviador"], ["Dorado", "Plateado"], "AB", "12000"),
            # No colour at all: "transparente" is not a colour a contact lens
            # comes in, it is just what a contact lens is. Plenty of products
            # have no colour, and the empty list is the right way to say so.
            ("LC-001", "Lentes de contacto mensual", pt_contact, brand_b, None, [], "AA", "6000"),
        ]
        # Only the articles get stock — a style holds none of its own.
        created_products: list[Product] = []
        for code, description, ptype, brand, model, color_names, cat_code, cost in products_spec:
            prod, was_new = get_or_create(
                db, Product,
                defaults={
                    "description": description, "product_type_id": ptype.id,
                    "brand_id": brand.id, "model_id": model.id if model else None,
                    "supplier_id": supplier.id,
                    "price_category_code": cat_code, "current_cost": Decimal(cost),
                    "min_stock": Decimal("2"),
                },
                company_id=cid, code=code,
            )
            if not was_new:
                continue
            db.flush()
            # Through sync_variants, exactly like the API: the colours are the
            # declaration, and it decides whether this is a plain article or a
            # style with one article per colour. Seeding must not take a
            # shortcut the application does not have.
            prod.colors = [colors[n] for n in color_names]
            db.flush()
            made = products_service.sync_variants(
                db, prod, company_id=cid, user_id=admin.id, previous_color_ids=[]
            )
            created_products.extend(made or [prod])
        db.flush()

        # --- customer ---
        get_or_create(
            db, Customer,
            defaults={"document_type": "DNI", "document_number": "30111222", "phone": "11-5555-0000"},
            company_id=cid, first_name="Juan", last_name="Pérez",
        )

        # --- payment accounts (where the money lands) ---
        # "Efectivo caja" comes from provisioning; these are demo extras.
        for name, method in [
            ("Santander", PaymentMethod.TRANSFER),
            ("MercadoPago", PaymentMethod.TRANSFER),
            ("Posnet Visa/Master", PaymentMethod.CARD),
        ]:
            get_or_create(
                db, PaymentAccount, defaults={"method": method},
                company_id=cid, name=name,
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

        # Repair the id counter on a database seeded before this ran — an
        # already-stale sequence would break the first tenant onboarded.
        provisioning.resync_company_sequence(db)
        db.commit()

        # --- provider (platform) account for the /admin console ---
        # Separate table, separate token scope: this login cannot touch a
        # shop's data, and a shop's login cannot reach /admin.
        platform_email = settings.platform_admin_email
        platform_password = settings.platform_admin_password
        existing_platform = db.execute(
            select(PlatformUser).where(PlatformUser.email == platform_email)
        ).scalar_one_or_none()
        if existing_platform is not None:
            pass
        elif (
            settings.environment != "local"
            and platform_password in platform_service.INSECURE_DEFAULTS
        ):
            # This account can enter every customer's data. Seeding it with a
            # password that is written down in the repo would be handing that
            # out to anyone who reads the source, so outside a local demo we
            # refuse and point at the CLI instead.
            print(
                "⚠  No se creó la cuenta de plataforma: PLATFORM_ADMIN_PASSWORD "
                f"tiene un valor por defecto y ENVIRONMENT={settings.environment}.\n"
                "   Creala a mano:  python -m scripts.platform_admin create"
            )
            platform_email = None
        else:
            # Local only (the branch above refuses anything else), so the
            # demo password is allowed to be the short well-known one.
            platform_service.create_platform_user(
                db,
                email=platform_email,
                full_name="Plataforma SGI",
                password=platform_password,
                validate=settings.environment != "local",
            )

        print("✅ Seed complete.")
        print("   Company:", company.name, f"(id={cid})")
        print("   Tenant console  /app    →", "admin@sgi.com / admin1234")
        if platform_email:
            print(
                "   Provider console /admin →",
                f"{platform_email} / {platform_password}",
            )
        print(f"   Branches: {main_branch.code}, {second_branch.code}")
        print(f"   Products seeded with stock: {len(created_products)}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
