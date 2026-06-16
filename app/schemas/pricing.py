from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import ORMBase, SoftDeleteRead


# --- price category -------------------------------------------------------
class PriceCategoryCreate(BaseModel):
    name: str
    description: str | None = None


class PriceCategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class PriceCategoryRead(SoftDeleteRead):
    name: str
    description: str | None = None


# --- price list -----------------------------------------------------------
class PriceListCreate(BaseModel):
    name: str
    product_type_id: int | None = None
    is_default: bool = False


class PriceListUpdate(BaseModel):
    name: str | None = None
    product_type_id: int | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class PriceListRead(SoftDeleteRead):
    name: str
    product_type_id: int | None = None
    is_default: bool


# --- price list item ------------------------------------------------------
class PriceListItemCreate(BaseModel):
    price_category_id: int
    price: Decimal


class PriceListItemUpdate(BaseModel):
    price: Decimal


class PriceListItemRead(ORMBase):
    id: int
    price_list_id: int
    price_category_id: int
    price: Decimal


# --- bulk percentage update ----------------------------------------------
class BulkPriceUpdate(BaseModel):
    """Apply a percentage change to every item in a price list."""

    percentage: Decimal  # e.g. 10 => +10%, -5 => -5%


# --- cost history (read-only) --------------------------------------------
class CostHistoryRead(ORMBase):
    id: int
    product_id: int
    old_cost: Decimal | None = None
    new_cost: Decimal
    changed_by_user_id: int | None = None
    note: str | None = None
    changed_at: datetime
