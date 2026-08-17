from __future__ import annotations

import re
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.models.enums import PricingMode
from app.schemas.common import SoftDeleteRead

_HEX_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _norm_category_code(v: str | None) -> str | None:
    """Category codes are matched case-insensitively, so store them upper-cased."""
    if v is None:
        return None
    code = str(v).strip().upper()
    return code or None


def _norm_hex(v: str | None) -> str | None:
    """Normalise a swatch to ``#rrggbb``.

    Accepts what a human or an ``<input type="color">`` might send: with or
    without the ``#``, 3 or 6 digits, any case. Blank means "no swatch".
    """
    if v is None:
        return None
    raw = str(v).strip()
    if not raw:
        return None
    if not _HEX_RE.match(raw):
        raise ValueError('El color debe ser hexadecimal, por ejemplo "#1a1a1a".')
    digits = raw.lstrip("#").lower()
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return f"#{digits}"


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


# --- color ----------------------------------------------------------------
class ColorCreate(BaseModel):
    name: str
    hex_code: str | None = None

    @field_validator("hex_code")
    @classmethod
    def _clean_hex(cls, v: str | None) -> str | None:
        return _norm_hex(v)


class ColorUpdate(BaseModel):
    name: str | None = None
    hex_code: str | None = None
    is_active: bool | None = None

    @field_validator("hex_code")
    @classmethod
    def _clean_hex(cls, v: str | None) -> str | None:
        return _norm_hex(v)


class ColorRead(SoftDeleteRead):
    name: str
    hex_code: str | None = None


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
    color_id: int | None = None
    product_type_id: int
    brand_id: int | None = None
    model_id: int | None = None
    supplier_id: int | None = None
    # --- selling price ---
    pricing_mode: PricingMode = PricingMode.PRICE_LIST
    sale_price: Decimal | None = None
    price_list_id: int | None = None
    # The category code ("AB"), resolved inside whichever list applies.
    price_category_code: str | None = None
    current_cost: Decimal = Decimal("0")
    min_stock: Decimal = Decimal("0")

    @field_validator("price_category_code")
    @classmethod
    def _clean_code(cls, v: str | None) -> str | None:
        return _norm_category_code(v)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    code: str | None = None
    description: str | None = None
    color_id: int | None = None
    product_type_id: int | None = None
    brand_id: int | None = None
    model_id: int | None = None
    supplier_id: int | None = None
    # Pricing fields go through services.pricing.apply_pricing_update so every
    # change lands in change_history (CLAUDE.md rule 4).
    pricing_mode: PricingMode | None = None
    sale_price: Decimal | None = None
    price_list_id: int | None = None
    price_category_code: str | None = None
    min_stock: Decimal | None = None
    is_active: bool | None = None
    # NOTE: current_cost is intentionally excluded — change it via the cost
    # endpoint so the change is audited and written to cost_history.

    @field_validator("price_category_code")
    @classmethod
    def _clean_code(cls, v: str | None) -> str | None:
        return _norm_category_code(v)


class ProductRead(SoftDeleteRead, ProductBase):
    # Resolved by services.pricing.resolve_prices — not stored on the row.
    resolved_sale_price: Decimal | None = None
    price_source: str | None = None
    price_reason: str | None = None
    # Currency of the resolved price: the list's for PRICE_LIST, the company's
    # for MANUAL. A label only — nothing is converted.
    price_currency: str | None = None


class ProductPriceRead(BaseModel):
    """Where a product's selling price comes from."""

    product_id: int
    price: Decimal | None
    source: str
    price_list_id: int | None = None
    currency: str | None = None
    reason: str | None = None


class CostUpdate(BaseModel):
    new_cost: Decimal
    note: str | None = None
