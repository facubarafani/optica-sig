from __future__ import annotations

import re
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

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
def _norm_color_code(v: str | None) -> str | None:
    """Colour codes read best upper-cased, and are matched that way."""
    if v is None:
        return None
    code = str(v).strip().upper()
    return code or None


class ColorCreate(BaseModel):
    name: str
    # Left empty, services.products.derive_color_code proposes one from the
    # name; it only has to be given when the shop wants its own tag.
    code: str | None = None
    hex_code: str | None = None

    @field_validator("hex_code")
    @classmethod
    def _clean_hex(cls, v: str | None) -> str | None:
        return _norm_hex(v)

    @field_validator("code")
    @classmethod
    def _clean_code(cls, v: str | None) -> str | None:
        return _norm_color_code(v)


class ColorUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    hex_code: str | None = None
    is_active: bool | None = None

    @field_validator("hex_code")
    @classmethod
    def _clean_hex(cls, v: str | None) -> str | None:
        return _norm_hex(v)

    @field_validator("code")
    @classmethod
    def _clean_code(cls, v: str | None) -> str | None:
        return _norm_color_code(v)


class ColorRead(SoftDeleteRead):
    name: str
    code: str | None = None
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
    # The max_lengths mirror the columns (String(40)/(500)/(8)). Without them an
    # over-long value reaches Postgres and raises DataError, which main.py does
    # not map — an unhandled 500 rather than a 422 naming the field. SQLite
    # truncates silently instead, so the test suite cannot catch this.
    code: str = Field(min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    # The style this article is a colour of. NULL = a style, or a plain
    # article with no variants.
    parent_id: int | None = None
    # A product comes in as many colours as the shop stocks it in; the ids are
    # the whole set, so sending [] clears it.
    color_ids: list[int] = []
    # True: those colours are one article (a bicolour frame), not one per colour.
    multicolor: bool = False
    product_type_id: int
    brand_id: int | None = None
    model_id: int | None = None
    supplier_id: int | None = None
    # --- selling price ---
    pricing_mode: PricingMode = PricingMode.PRICE_LIST
    sale_price: Decimal | None = None
    price_list_id: int | None = None
    # The category code ("AB"), resolved inside whichever list applies.
    price_category_code: str | None = Field(default=None, max_length=8)
    current_cost: Decimal = Decimal("0")
    min_stock: Decimal = Decimal("0")

    @field_validator("price_category_code")
    @classmethod
    def _clean_code(cls, v: str | None) -> str | None:
        return _norm_category_code(v)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    parent_id: int | None = None
    # Omitted = leave the colours alone; [] = remove them all.
    color_ids: list[int] | None = None
    # Unticking it turns the same colours into a range, split like a colour edit.
    multicolor: bool | None = None
    product_type_id: int | None = None
    brand_id: int | None = None
    model_id: int | None = None
    supplier_id: int | None = None
    # Pricing fields go through services.pricing.apply_pricing_update so every
    # change lands in change_history (CLAUDE.md rule 4).
    pricing_mode: PricingMode | None = None
    sale_price: Decimal | None = None
    price_list_id: int | None = None
    price_category_code: str | None = Field(default=None, max_length=8)
    min_stock: Decimal | None = None
    is_active: bool | None = None
    # NOTE: current_cost is intentionally excluded — change it via the cost
    # endpoint so the change is audited and written to cost_history.

    @field_validator("price_category_code")
    @classmethod
    def _clean_code(cls, v: str | None) -> str | None:
        return _norm_category_code(v)


class ProductRead(SoftDeleteRead, ProductBase):
    # The colours expanded, so a grid can paint swatches without a second
    # request. ``color_ids`` (inherited) is what a write takes back.
    colors: list[ColorRead] = []
    # Family, resolved by the router in one batched query rather than per row.
    # ``variant_count`` > 0 means this is a style: not sellable, not stockable.
    variant_count: int = 0
    parent_code: str | None = None
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


class VariantSpec(BaseModel):
    """One variant to generate: the colours it comes in, and its code."""

    color_ids: list[int]
    # Left empty, it is built from the style's code plus the colour tags
    # (ARM-001 + HAV -> ARM-001-HAV).
    code: str | None = None


class VariantsCreate(BaseModel):
    """Generate variants of a style. Either shape is accepted:

    ``color_ids`` is the everyday case — one variant per colour. ``variants``
    is the general one, and the only way to ask for a bicolour variant.
    """

    color_ids: list[int] = []
    variants: list[VariantSpec] = []

    def specs(self) -> list[tuple[list[int], str | None]]:
        if self.variants:
            return [(v.color_ids, v.code) for v in self.variants]
        return [([cid], None) for cid in self.color_ids]


class CostUpdate(BaseModel):
    new_cost: Decimal
    note: str | None = None
