from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import SoftDeleteRead


class BranchBase(BaseModel):
    # The max_lengths mirror the columns (see tests/test_schema_lengths.py).
    name: str = Field(max_length=120)
    code: str = Field(max_length=20)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = Field(default=None, max_length=150)
    # ARCA punto de venta for this branch's comprobantes. Empty uses the shop's.
    point_of_sale: int | None = Field(None, ge=1, le=99998)


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    code: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = Field(default=None, max_length=150)
    point_of_sale: int | None = Field(None, ge=1, le=99998)
    is_active: bool | None = None


class BranchRead(SoftDeleteRead, BranchBase):
    pass
