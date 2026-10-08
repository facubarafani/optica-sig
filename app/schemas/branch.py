from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import SoftDeleteRead


class BranchBase(BaseModel):
    name: str
    code: str
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    # ARCA punto de venta for this branch's comprobantes. Empty uses the shop's.
    point_of_sale: int | None = Field(None, ge=1, le=99998)


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    point_of_sale: int | None = Field(None, ge=1, le=99998)
    is_active: bool | None = None


class BranchRead(SoftDeleteRead, BranchBase):
    pass
