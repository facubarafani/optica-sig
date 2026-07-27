from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import Currency, RoundingMode
from app.schemas.common import ORMBase, SoftDeleteRead

# A list can hold at most AA..ZZ steps.
MAX_CATEGORIES = 26 * 26


def _clean_code(value: str) -> str:
    """Codes are compared case-insensitively, so they are stored upper-cased."""
    code = str(value).strip().upper()
    if not code:
        raise ValueError("El código de la categoría no puede estar vacío.")
    return code


# --- price list -----------------------------------------------------------
class PriceListCreate(BaseModel):
    name: str
    product_type_id: int | None = None
    is_default: bool = False
    currency: Currency = Currency.ARS


class PriceListUpdate(BaseModel):
    name: str | None = None
    product_type_id: int | None = None
    is_default: bool | None = None
    currency: Currency | None = None
    is_active: bool | None = None


class PriceListRead(SoftDeleteRead):
    name: str
    product_type_id: int | None = None
    is_default: bool
    currency: str


class PriceListSummaryRead(PriceListRead):
    """A list plus the shape of its ladder, for the grid."""

    category_count: int = 0
    min_price: Decimal | None = None
    max_price: Decimal | None = None


# --- price category (a step inside one list) ------------------------------
class PriceCategoryCreate(BaseModel):
    # Omit the code and the next one in the AA..ZZ sequence is assigned.
    code: str | None = None
    description: str | None = None
    price: Decimal = Decimal("0")

    @field_validator("code")
    @classmethod
    def _norm_code(cls, v: str | None) -> str | None:
        return None if v is None else _clean_code(v)


class PriceCategoryUpdate(BaseModel):
    code: str | None = None
    description: str | None = None
    price: Decimal | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def _norm_code(cls, v: str | None) -> str | None:
        return None if v is None else _clean_code(v)


class PriceCategoryRead(SoftDeleteRead):
    price_list_id: int
    code: str
    description: str | None = None
    price: Decimal
    position: int


# --- generators -----------------------------------------------------------
class GenerateCategories(BaseModel):
    """Set the list to exactly ``count`` active steps, named AA, AB, AC…

    Growing appends new codes; shrinking deactivates the trailing ones (their
    prices are kept, so going back up restores them).
    """

    count: int = Field(ge=1, le=MAX_CATEGORIES)


class GeneratePrices(BaseModel):
    """Spread a price range across the list's active categories.

    The first category gets ``min_price`` and the last ``max_price``; the steps
    in between are evenly spaced. Every result is rounded with ``rounding_step``
    / ``rounding_mode`` (default: up to the nearest 100).
    """

    min_price: Decimal = Field(ge=0)
    max_price: Decimal = Field(ge=0)
    rounding_step: Decimal = Field(default=Decimal("100"), ge=0)
    rounding_mode: RoundingMode = RoundingMode.UP

    @model_validator(mode="after")
    def _check_range(self):
        if self.max_price < self.min_price:
            raise ValueError("El precio máximo no puede ser menor que el mínimo.")
        return self


# --- bulk percentage update ----------------------------------------------
class BulkPriceUpdate(BaseModel):
    """Apply a percentage change to every category in a price list."""

    percentage: Decimal  # e.g. 10 => +10%, -5 => -5%
    # 0 keeps the exact percentage result (rounded to cents).
    rounding_step: Decimal = Field(default=Decimal("100"), ge=0)
    rounding_mode: RoundingMode = RoundingMode.UP


# --- cost history (read-only) --------------------------------------------
class CostHistoryRead(ORMBase):
    id: int
    product_id: int
    old_cost: Decimal | None = None
    new_cost: Decimal
    changed_by_user_id: int | None = None
    note: str | None = None
    changed_at: datetime
