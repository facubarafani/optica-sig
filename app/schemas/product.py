from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import PricingMode
from app.schemas.common import SoftDeleteRead


# --- product type ---------------------------------------------------------
class ProductTypeCreate(BaseModel):
    name: str
    description: str | None = None


class ProductTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class ProductTypeRead(SoftDeleteRead):
    name: str
    description: str | None = None


# --- brand ----------------------------------------------------------------
class BrandCreate(BaseModel):
    name: str


class BrandUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class BrandRead(SoftDeleteRead):
    name: str


# --- product model ("Modelo": clipper, aviador, redondo...) ----------------
class ProductModelCreate(BaseModel):
    name: str
    # Optional: leave unset and the model applies to every product type.
    product_type_id: int | None = None


class ProductModelUpdate(BaseModel):
    name: str | None = None
    product_type_id: int | None = None
    is_active: bool | None = None


class ProductModelRead(SoftDeleteRead):
    name: str
    product_type_id: int | None = None


# --- product --------------------------------------------------------------
class ProductBase(BaseModel):
    code: str
    description: str | None = None
    color: str | None = None
    product_type_id: int
    brand_id: int | None = None
    model_id: int | None = None
    supplier_id: int | None = None
    # --- selling price ---
    pricing_mode: PricingMode = PricingMode.PRICE_LIST
    sale_price: Decimal | None = None
    price_list_id: int | None = None
    price_category_id: int | None = None
    current_cost: Decimal = Decimal("0")
    min_stock: Decimal = Decimal("0")


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    code: str | None = None
    description: str | None = None
    color: str | None = None
    product_type_id: int | None = None
    brand_id: int | None = None
    model_id: int | None = None
    supplier_id: int | None = None
    # Pricing fields go through services.pricing.apply_pricing_update so every
    # change lands in change_history (CLAUDE.md rule 4).
    pricing_mode: PricingMode | None = None
    sale_price: Decimal | None = None
    price_list_id: int | None = None
    price_category_id: int | None = None
    min_stock: Decimal | None = None
    is_active: bool | None = None
    # NOTE: current_cost is intentionally excluded — change it via the cost
    # endpoint so the change is audited and written to cost_history.


class ProductRead(SoftDeleteRead, ProductBase):
    # Resolved by services.pricing.resolve_prices — not stored on the row.
    resolved_sale_price: Decimal | None = None
    price_source: str | None = None
    price_reason: str | None = None


class ProductPriceRead(BaseModel):
    """Where a product's selling price comes from."""

    product_id: int
    price: Decimal | None
    source: str
    price_list_id: int | None = None
    reason: str | None = None


class CostUpdate(BaseModel):
    new_cost: Decimal
    note: str | None = None
