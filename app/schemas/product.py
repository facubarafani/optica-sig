from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

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


# --- product --------------------------------------------------------------
class ProductBase(BaseModel):
    code: str
    name: str
    description: str | None = None
    model: str | None = None
    color: str | None = None
    product_type_id: int
    brand_id: int | None = None
    supplier_id: int | None = None
    price_category_id: int | None = None
    current_cost: Decimal = Decimal("0")
    min_stock: Decimal = Decimal("0")


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    model: str | None = None
    color: str | None = None
    product_type_id: int | None = None
    brand_id: int | None = None
    supplier_id: int | None = None
    price_category_id: int | None = None
    min_stock: Decimal | None = None
    is_active: bool | None = None
    # NOTE: current_cost is intentionally excluded — change it via the cost
    # endpoint so the change is audited and written to cost_history.


class ProductRead(SoftDeleteRead, ProductBase):
    pass


class CostUpdate(BaseModel):
    new_cost: Decimal
    note: str | None = None
