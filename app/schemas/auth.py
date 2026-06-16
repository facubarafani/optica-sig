from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.schemas.common import ORMBase, SoftDeleteRead


# --- tokens / login -------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# --- permissions ----------------------------------------------------------
class PermissionRead(ORMBase):
    id: int
    code: str
    name: str
    description: str | None = None


# --- roles ----------------------------------------------------------------
class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_ids: list[int] | None = None
    is_active: bool | None = None


class RoleRead(SoftDeleteRead):
    name: str
    description: str | None = None
    permissions: list[PermissionRead] = []


# --- users ----------------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    is_superuser: bool = False
    branch_id: int | None = None
    role_ids: list[int] = []


class UserUpdate(BaseModel):
    full_name: str | None = None
    password: str | None = None
    is_superuser: bool | None = None
    branch_id: int | None = None
    role_ids: list[int] | None = None
    is_active: bool | None = None


class UserRead(SoftDeleteRead):
    email: EmailStr
    full_name: str
    is_superuser: bool
    branch_id: int | None = None
    roles: list[RoleRead] = []
