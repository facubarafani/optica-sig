from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.schemas.common import ORMBase, SoftDeleteRead


class CompanyBase(BaseModel):
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    currency: str = "ARS"


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    currency: str | None = None
    is_active: bool | None = None


class CompanyRead(SoftDeleteRead, CompanyBase):
    pass


class CompanySettingsBase(BaseModel):
    currency: str = "ARS"
    timezone: str = "America/Argentina/Buenos_Aires"
    allow_negative_stock: bool = False
    default_branch_id: int | None = None
    default_price_list_id: int | None = None
    low_stock_alerts_enabled: bool = True


class CompanySettingsUpdate(BaseModel):
    currency: str | None = None
    timezone: str | None = None
    allow_negative_stock: bool | None = None
    default_branch_id: int | None = None
    default_price_list_id: int | None = None
    low_stock_alerts_enabled: bool | None = None


class CompanySettingsRead(ORMBase, CompanySettingsBase):
    id: int
    company_id: int
