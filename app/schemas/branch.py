from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.schemas.common import SoftDeleteRead


class BranchBase(BaseModel):
    name: str
    code: str
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None


class BranchRead(SoftDeleteRead, BranchBase):
    pass
