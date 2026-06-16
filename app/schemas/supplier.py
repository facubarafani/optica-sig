from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.models.enums import SupplierType
from app.schemas.common import SoftDeleteRead


class SupplierBase(BaseModel):
    name: str
    supplier_type: SupplierType
    tax_id: str | None = None
    contact_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = None
    supplier_type: SupplierType | None = None
    tax_id: str | None = None
    contact_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class SupplierRead(SoftDeleteRead, SupplierBase):
    pass
