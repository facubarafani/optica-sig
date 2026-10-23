"""Every string a request may carry fits the column that stores it.

Postgres refuses an over-long value with DataError, which main.py does not map:
an unhandled 500 instead of a 422 naming the field. The SQLite engine this suite
runs on stores the value whole, so no endpoint test can see the difference. The
schema's max_length is the only guard, and this test holds every request schema
to the columns it writes, so a new field or a resized column cannot drift apart.
"""
from __future__ import annotations

import typing

from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import Column, String

from app.main import app
from app.models.auth import Role, User
from app.models.branch import Branch
from app.models.company import Company, CompanySettings
from app.models.customer import Customer, Prescription, TreatmentHistory
from app.models.invoicing import ArcaIssuer, InvoicingRequest
from app.models.platform import PlatformAuditLog
from app.models.pricing import CostHistory, PriceCategory, PriceList
from app.models.product import Brand, Color, Product, ProductModel, ProductType
from app.models.sales import PaymentAccount, PaymentReminder, Sale, SalePayment
from app.models.stock import StockMovement
from app.models.supplier import Supplier
from app.schemas import (
    auth, branch, company, customer, imports, invoicing, platform, pricing,
    product, sales, stock, supplier,
)

# The table each request schema writes. A string field is held to the column of
# the same name there; COLUMNS names the ones stored under another name.
WRITES: dict[type[BaseModel], type] = {
    auth.RoleCreate: Role,
    auth.RoleUpdate: Role,
    auth.UserCreate: User,
    auth.UserUpdate: User,
    branch.BranchCreate: Branch,
    branch.BranchUpdate: Branch,
    company.CompanyUpdate: Company,
    company.CompanySettingsUpdate: CompanySettings,
    customer.CustomerCreate: Customer,
    customer.CustomerUpdate: Customer,
    customer.PrescriptionCreate: Prescription,
    customer.TreatmentHistoryCreate: TreatmentHistory,
    imports.CodeColorsOptions: CompanySettings,
    imports.CodeColorsRequest: CompanySettings,
    imports.TailDecision: Color,
    invoicing.InvoicingRequestWrite: InvoicingRequest,
    invoicing.TenantInvoicingLink: ArcaIssuer,
    invoicing.TenantInvoicingUpdate: ArcaIssuer,
    invoicing.TenantInvoicingNote: InvoicingRequest,
    platform.ImpersonateRequest: PlatformAuditLog,
    platform.TenantAdminCreate: User,
    platform.TenantCreate: Company,
    platform.TenantUpdate: Company,
    pricing.PriceCategoryCreate: PriceCategory,
    pricing.PriceCategoryUpdate: PriceCategory,
    pricing.PriceListCreate: PriceList,
    pricing.PriceListUpdate: PriceList,
    product.BrandCreate: Brand,
    product.BrandUpdate: Brand,
    product.ColorCreate: Color,
    product.ColorUpdate: Color,
    product.CostUpdate: CostHistory,
    product.ProductCreate: Product,
    product.ProductUpdate: Product,
    product.ProductModelCreate: ProductModel,
    product.ProductModelUpdate: ProductModel,
    product.ProductTypeCreate: ProductType,
    product.ProductTypeUpdate: ProductType,
    product.VariantSpec: Product,
    sales.PaymentAccountCreate: PaymentAccount,
    sales.PaymentAccountUpdate: PaymentAccount,
    sales.PaymentCreate: SalePayment,
    sales.ReminderSend: PaymentReminder,
    sales.SaleCreate: Sale,
    sales.SaleUpdate: Sale,
    stock.StockMovementCreate: StockMovement,
    stock.StockTransferCreate: StockMovement,
    supplier.SupplierCreate: Supplier,
    supplier.SupplierUpdate: Supplier,
}

COLUMNS: dict[tuple[type[BaseModel], str], Column] = {
    (imports.CodeColorsOptions, "separator"): CompanySettings.__table__.c.code_color_separator,
    (imports.CodeColorsRequest, "separator"): CompanySettings.__table__.c.code_color_separator,
    # A tail's colours are created by name when the shop does not have them.
    (imports.TailDecision, "colors"): Color.__table__.c.name,
    (invoicing.TenantInvoicingNote, "note"): InvoicingRequest.__table__.c.provider_note,
    (platform.ImpersonateRequest, "reason"): PlatformAuditLog.__table__.c.detail,
    (platform.TenantCreate, "admin_email"): User.__table__.c.email,
    (platform.TenantCreate, "admin_full_name"): User.__table__.c.full_name,
    (invoicing.TenantInvoicingLink, "commercial_address"):
        InvoicingRequest.__table__.c.commercial_address,
    (invoicing.TenantInvoicingLink, "gross_income_tax"):
        InvoicingRequest.__table__.c.gross_income_tax,
    (invoicing.TenantInvoicingLink, "trade_name"): InvoicingRequest.__table__.c.trade_name,
    (invoicing.TenantInvoicingUpdate, "commercial_address"):
        InvoicingRequest.__table__.c.commercial_address,
    (invoicing.TenantInvoicingUpdate, "gross_income_tax"):
        InvoicingRequest.__table__.c.gross_income_tax,
    (invoicing.TenantInvoicingUpdate, "trade_name"): InvoicingRequest.__table__.c.trade_name,
}

# Fields a validator reduces to a fixed shape that fits, whatever was typed:
# a CUIT keeps its 11 digits ("20-12345678-9" is 13 characters on the way in),
# a swatch becomes #rrggbb. A max_length there would refuse valid input.
SHAPED: set[tuple[type[BaseModel], str]] = {
    (invoicing.InvoicingRequestWrite, "cuit"),
    (invoicing.TenantInvoicingLink, "cuit"),
    (product.ColorCreate, "hex_code"),
    (product.ColorUpdate, "hex_code"),
}

# Request schemas whose strings are never stored as sent: credentials and
# lookups, options that only steer the request, and multipart forms.
NOT_STORED: set[str] = {
    auth.LoginRequest.__name__,
    auth.ForgotPasswordRequest.__name__,
    auth.SetPasswordRequest.__name__,
    platform.PlatformLoginRequest.__name__,
    platform.PasswordReset.__name__,
    imports.ImportOptions.__name__,
    pricing.BulkPriceUpdate.__name__,
    pricing.GeneratePrices.__name__,
    product.InitialStock.__name__,
    sales.SaleItemCreate.__name__,
    "Body_login_form_api_auth_token_post",
    "Body_login_form_api_admin_token_post",
    "Body_upload_api_imports__spec_key__upload_post",
}


def _models_in(annotation, found: set[type[BaseModel]]) -> None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation not in found:
            found.add(annotation)
            for field in annotation.model_fields.values():
                _models_in(field.annotation, found)
        return
    for arg in typing.get_args(annotation):
        _models_in(arg, found)


def _request_schemas() -> set[type[BaseModel]]:
    """Every model an endpoint accepts as its body, nested ones included."""
    found: set[type[BaseModel]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.body_field is not None:
            _models_in(route.body_field.field_info.annotation, found)
    return found


def _text(variant: dict) -> bool:
    return (variant.get("type") == "string" and "enum" not in variant
            and "const" not in variant
            and variant.get("format") not in ("date", "date-time", "binary"))


def _string_fields(schema: type[BaseModel]) -> dict[str, int | None]:
    """Each free-text field (or list of them) and its max_length; None: unbounded."""
    out: dict[str, int | None] = {}
    for name, prop in schema.model_json_schema()["properties"].items():
        variants = prop.get("anyOf", [prop])
        # A Decimal also accepts its digits as a string; that is not text.
        if any(v.get("type") in ("number", "integer") for v in variants):
            continue
        for variant in variants:
            if variant.get("type") == "array":
                variant = variant.get("items", {})
            if _text(variant):
                out[name] = variant.get("maxLength")
                break
    return out


def test_every_request_schema_with_text_is_classified():
    """A new body schema has to say where its strings end up."""
    unclassified = sorted(
        s.__name__ for s in _request_schemas()
        if _string_fields(s) and s not in WRITES and s.__name__ not in NOT_STORED
    )
    assert not unclassified, (
        "Add these to WRITES (with the table they write) or NOT_STORED: "
        f"{unclassified}"
    )


def test_request_strings_fit_their_columns():
    problems = []
    for schema, model in WRITES.items():
        for name, max_length in _string_fields(schema).items():
            if (schema, name) in SHAPED:
                continue
            column = COLUMNS.get((schema, name))
            if column is None:
                column = model.__table__.c.get(name)
            if column is None or not isinstance(column.type, String):
                continue
            size = column.type.length
            if size is None:
                continue
            if max_length is None:
                problems.append(f"{schema.__name__}.{name}: no max_length, column is {size}")
            elif max_length > size:
                problems.append(f"{schema.__name__}.{name}: max_length {max_length} > {size}")
    assert not problems, "\n".join(problems)


def test_the_tables_named_here_exist():
    """A mapping to a column that was renamed would pass silently."""
    for (schema, name), column in COLUMNS.items():
        assert name in schema.model_fields, f"{schema.__name__} has no {name}"
        assert isinstance(column.type, String), f"{column} is not a String"


# --- what the person reads ----------------------------------------------------

def test_an_overlong_sale_note_is_a_422_in_spanish(client, auth_headers,
                                                   product_type_id, branch_id):
    product = client.post(
        "/api/products",
        json={"code": "LEN-1", "product_type_id": product_type_id,
              "pricing_mode": "manual", "sale_price": "1000"},
        headers=auth_headers,
    ).json()
    sale = {"branch_id": branch_id, "items": [{"product_id": product["id"]}],
            "payments": [{"amount": "1000", "method": "cash"}]}

    resp = client.post("/api/sales", json={**sale, "notes": "n" * 501},
                       headers=auth_headers)
    assert resp.status_code == 422, resp.text
    error = resp.json()["detail"][0]
    assert error["loc"][-1] == "notes"
    assert error["msg"] == "Admite como máximo 500 caracteres y tiene 501."

    created = client.post("/api/sales", json={**sale, "notes": "n" * 500},
                          headers=auth_headers)
    assert created.status_code == 201, created.text

    resp = client.put(f"/api/sales/{created.json()['id']}",
                      json={"reminder_note": "r" * 256}, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["msg"] == "Admite como máximo 255 caracteres y tiene 256."


def test_an_overlong_treatment_or_email_is_a_422_in_spanish(client, auth_headers):
    customer = client.post(
        "/api/customers", json={"first_name": "Laura", "last_name": "Giménez"},
        headers=auth_headers,
    ).json()
    resp = client.post(
        f"/api/customers/{customer['id']}/treatments",
        json={"treatment_type": "myopia", "description": "d" * 501},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["msg"] == "Admite como máximo 500 caracteres y tiene 501."

    # Valid as an address, too long for the column: checked after it parses.
    email = "a" * 64 + "@" + "b" * 63 + "." + "c" * 27 + ".com"
    resp = client.put(f"/api/customers/{customer['id']}", json={"email": email},
                      headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["msg"] == "Admite como máximo 150 caracteres y tiene 160."

    resp = client.put(f"/api/customers/{customer['id']}", json={"email": "laura"},
                      headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["msg"] == "No es un email válido."


def test_our_own_validation_messages_arrive_without_pydantic_prefix(client, auth_headers):
    resp = client.post(
        "/api/sales",
        json={"items": [{"product_id": 1}], "discount_type": "amount",
              "discount_value": "-5"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["msg"] == "El descuento no puede ser negativo."

    resp = client.post("/api/products", json={"code": "", "product_type_id": 1},
                       headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["msg"] == "No puede quedar vacío."
