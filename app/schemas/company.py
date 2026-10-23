from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMBase, SoftDeleteRead
from app.services.clock import is_valid_zone


class CompanyBase(BaseModel):
    # The max_lengths mirror the columns (see tests/test_schema_lengths.py).
    name: str = Field(max_length=150)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    currency: str = Field(default="ARS", max_length=3)


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    currency: str | None = Field(default=None, max_length=3)
    is_active: bool | None = None


class CompanyRead(SoftDeleteRead, CompanyBase):
    pass


def _known_zone(value: str | None) -> str | None:
    """A zone the server can resolve: a typo would silently fall back to
    Buenos Aires in services.clock, and the shop would never know."""
    if value is not None and not is_valid_zone(value):
        raise ValueError(f"Zona horaria desconocida: {value}.")
    return value


class CompanySettingsBase(BaseModel):
    currency: str = Field(default="ARS", max_length=3)
    timezone: str = Field(default="America/Argentina/Buenos_Aires", max_length=64)
    allow_negative_stock: bool = False
    default_branch_id: int | None = None
    default_price_list_id: int | None = None
    low_stock_alerts_enabled: bool = True


class CompanySettingsUpdate(BaseModel):
    currency: str | None = Field(default=None, max_length=3)
    timezone: str | None = Field(default=None, max_length=64)
    allow_negative_stock: bool | None = None
    default_branch_id: int | None = None
    default_price_list_id: int | None = None
    low_stock_alerts_enabled: bool | None = None

    _zone = field_validator("timezone")(_known_zone)


class CompanySettingsRead(ORMBase, CompanySettingsBase):
    id: int
    company_id: int
