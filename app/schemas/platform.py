"""Schemas for the provider-side admin API (``/api/admin``)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMBase


# --- identity -------------------------------------------------------------
class PlatformLoginRequest(BaseModel):
    email: EmailStr
    password: str


class PlatformUserRead(ORMBase):
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    last_login_at: datetime | None = None


# --- tenants --------------------------------------------------------------
class TenantCreate(BaseModel):
    """A new óptica, plus the credentials its owner will log in with."""

    name: str = Field(min_length=1, max_length=150)
    legal_name: str | None = None
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    currency: str = "ARS"

    admin_email: EmailStr
    admin_full_name: str = "Administrador"
    # Leave empty to email the owner an invitation and let them choose their
    # own password — the default, and the only path where we never handle a
    # customer's credential. Setting one here is the fallback for an owner
    # whose email is not working yet.
    admin_password: str | None = Field(default=None, min_length=8, max_length=128)


class TenantUpdate(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    currency: str | None = None


class TenantRead(ORMBase):
    id: int
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    currency: str
    is_active: bool
    created_at: datetime


class TenantSummary(TenantRead):
    """A tenant row as the admin list shows it."""

    user_count: int = 0
    product_count: int = 0
    sale_count: int = 0


class TenantCreated(BaseModel):
    """The result of onboarding: either a link was mailed, or a password to read out."""

    company: TenantRead
    admin_email: EmailStr
    # Only when we set one ourselves — echoed once and never recoverable.
    admin_password: str | None = None
    invitation_sent: bool = False


class TenantUserRead(ORMBase):
    id: int
    email: EmailStr
    full_name: str
    is_superuser: bool
    is_active: bool


class TenantAdminCreate(BaseModel):
    email: EmailStr
    full_name: str = "Administrador"
    # Same as TenantCreate: empty means "invite them by email".
    password: str | None = Field(default=None, min_length=8, max_length=128)


class TenantUserCreated(BaseModel):
    user: "TenantUserRead"
    password: str | None = None
    invitation_sent: bool = False


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class ImpersonateRequest(BaseModel):
    # Which user to enter as. Omitted means the company's first administrator,
    # which is what a support call almost always needs.
    user_id: int | None = None
    reason: str | None = Field(default=None, max_length=200)


class ImpersonateResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    company_id: int
    user_email: EmailStr
    user_full_name: str


# --- audit ----------------------------------------------------------------
class AuditLogRead(ORMBase):
    id: int
    platform_user_id: int | None = None
    action: str
    company_id: int | None = None
    target_user_id: int | None = None
    detail: str | None = None
    created_at: datetime
