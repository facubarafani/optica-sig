from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import SupplierType
from app.schemas.common import SoftDeleteRead


class SupplierBase(BaseModel):
    # The max_lengths mirror the columns (see tests/test_schema_lengths.py).
    name: str = Field(max_length=150)
    supplier_type: SupplierType
    tax_id: str | None = Field(default=None, max_length=20)
    contact_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    supplier_type: SupplierType | None = None
    tax_id: str | None = Field(default=None, max_length=20)
    contact_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class SupplierRead(SoftDeleteRead, SupplierBase):
    pass


class SupplierBrandsUpdate(BaseModel):
    """Replaces the supplier's whole brand set."""

    brand_ids: list[int]
