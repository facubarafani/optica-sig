from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMBase, SoftDeleteRead


# --- tokens / login -------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Only sent on the second round trip, when the first one found the same
    # address at more than one shop and the user picked which.
    company_id: int | None = None


class CompanyChoice(BaseModel):
    id: int
    name: str
    # La dirección desambigua dos sucursales de la misma cadena, que con
    # el nombre solo se confunden al elegir.
    address: str | None = None


class LoginResponse(BaseModel):
    """Either a token, or the list of shops the caller must choose between.

    One response model rather than two endpoints: the client posts the same
    form twice, the second time with ``company_id``. Nothing else about the
    login flow changes for the overwhelming majority of users, who exist at
    exactly one company and never see the picker.
    """

    access_token: str | None = None
    token_type: str = "bearer"
    companies: list[CompanyChoice] | None = None


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


# --- invitations / password reset ----------------------------------------
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class SetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class TokenCheck(BaseModel):
    """What the "set your password" screen needs to greet the visitor.

    Only ever returned to someone already holding a valid token, so naming the
    account is not a disclosure — and showing which óptica they are setting a
    password for is what stops a two-shop owner picking the wrong link.
    """

    purpose: str
    email: EmailStr
    full_name: str
    company_name: str
