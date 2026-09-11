"""Provider console API — onboarding and supporting tenant ópticas.

Every route here is authenticated by a *platform* token (see
``app/core/deps.py``): a shop's own token, however privileged inside its
company, cannot reach any of them. This is the only router that takes a
company id as an argument rather than deriving it from the caller.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_platform_user
from app.core.security import SCOPE_PLATFORM, create_access_token
from app.models.platform import PlatformUser
from app.schemas.auth import Token
from app.schemas.platform import (
    AuditLogRead,
    ImpersonateRequest,
    ImpersonateResponse,
    PasswordReset,
    PlatformLoginRequest,
    PlatformUserRead,
    TenantAdminCreate,
    TenantCreate,
    TenantCreated,
    TenantRead,
    TenantSummary,
    TenantUpdate,
    TenantUserCreated,
    TenantUserRead,
)
from app.services import platform as platform_service

router = APIRouter(prefix="/admin", tags=["platform admin"])

_BAD_CREDENTIALS = "Incorrect email or password"


def _platform_token(user: PlatformUser) -> str:
    return create_access_token(user.id, scope=SCOPE_PLATFORM)


# --- identity -------------------------------------------------------------
@router.post("/login", response_model=Token)
def login(payload: PlatformLoginRequest, db: Session = Depends(get_db)) -> Token:
    user = platform_service.authenticate(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)
    return Token(access_token=_platform_token(user))


@router.post("/token", response_model=Token)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    """OAuth2 password flow, so Swagger can authorize against the admin API."""
    user = platform_service.authenticate(db, form.username, form.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)
    return Token(access_token=_platform_token(user))


@router.get("/me", response_model=PlatformUserRead)
def me(
    current: PlatformUser = Depends(get_current_platform_user),
) -> PlatformUser:
    return current


# --- tenants --------------------------------------------------------------
@router.get("/tenants", response_model=list[TenantSummary])
def list_tenants(
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(get_current_platform_user),
) -> list[TenantSummary]:
    return [
        TenantSummary(
            **TenantRead.model_validate(row["company"]).model_dump(),
            user_count=row["user_count"],
            product_count=row["product_count"],
            sale_count=row["sale_count"],
        )
        for row in platform_service.list_tenants(db)
    ]


@router.post(
    "/tenants", response_model=TenantCreated, status_code=status.HTTP_201_CREATED
)
def create_tenant(
    data: TenantCreate,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
) -> TenantCreated:
    """Provision a whole óptica: company, settings, roles, admin, defaults.

    With no ``admin_password`` the owner is emailed an invitation and chooses
    their own — the normal path. With one, it is echoed back once so it can be
    read out, for an owner whose email is not working yet.
    """
    try:
        company, admin, invited = platform_service.create_tenant(
            db,
            current,
            name=data.name,
            legal_name=data.legal_name,
            tax_id=data.tax_id,
            email=data.email,
            phone=data.phone,
            address=data.address,
            currency=data.currency,
            admin_email=data.admin_email,
            admin_full_name=data.admin_full_name,
            admin_password=data.admin_password,
        )
    except Exception as exc:  # provisioning is one transaction; report it whole
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return TenantCreated(
        company=TenantRead.model_validate(company),
        admin_email=admin.email,
        # Echoed once, so it can be read out to the owner. It is never stored
        # in the clear and never retrievable again.
        admin_password=data.admin_password,
        invitation_sent=invited,
    )


@router.get("/tenants/{company_id}", response_model=TenantRead)
def get_tenant(
    company_id: int,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(get_current_platform_user),
):
    try:
        return platform_service.get_tenant(db, company_id)
    except platform_service.PlatformError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.put("/tenants/{company_id}", response_model=TenantRead)
def update_tenant(
    company_id: int,
    data: TenantUpdate,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
):
    try:
        company = platform_service.get_tenant(db, company_id)
    except platform_service.PlatformError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    changed = data.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(company, field, value)
    db.add(company)
    platform_service.record(
        db, current, platform_service.PlatformAction.TENANT_UPDATE,
        company_id=company.id, detail=", ".join(sorted(changed)) or None,
        commit=False,
    )
    db.commit()
    db.refresh(company)
    return company


@router.post("/tenants/{company_id}/suspend", response_model=TenantRead)
def suspend_tenant(
    company_id: int,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
):
    """Cut a shop off. Takes effect on their very next request, not next login."""
    try:
        return platform_service.set_tenant_active(db, current, company_id, False)
    except platform_service.PlatformError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.post("/tenants/{company_id}/reactivate", response_model=TenantRead)
def reactivate_tenant(
    company_id: int,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
):
    try:
        return platform_service.set_tenant_active(db, current, company_id, True)
    except platform_service.PlatformError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


# --- tenant users ---------------------------------------------------------
@router.get("/tenants/{company_id}/users", response_model=list[TenantUserRead])
def list_tenant_users(
    company_id: int,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(get_current_platform_user),
):
    return platform_service.tenant_users(db, company_id)


@router.post(
    "/tenants/{company_id}/users",
    response_model=TenantUserCreated,
    status_code=status.HTTP_201_CREATED,
)
def add_tenant_admin(
    company_id: int,
    data: TenantAdminCreate,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
):
    """Add another administrator — the lockout remedy.

    Without a password they get an invitation, which is also the better answer
    to a lockout: we never learn the credential we are restoring.
    """
    try:
        user, invited = platform_service.add_tenant_admin(
            db, current, company_id,
            email=data.email, full_name=data.full_name, password=data.password,
        )
    except platform_service.PlatformError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return TenantUserCreated(
        user=TenantUserRead.model_validate(user),
        password=data.password,
        invitation_sent=invited,
    )


@router.post("/tenants/{company_id}/users/{user_id}/invite")
def resend_invitation(
    company_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
) -> dict[str, bool]:
    """Send a fresh set-your-password link, voiding any earlier one.

    The everyday answer to "I never got the email" and to a forgotten
    password, and it replaces us choosing a credential on someone's behalf.
    """
    try:
        sent = platform_service.resend_invitation(db, current, company_id, user_id)
    except platform_service.PlatformError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {"sent": sent}


@router.post(
    "/tenants/{company_id}/users/{user_id}/password",
    response_model=TenantUserRead,
)
def reset_tenant_password(
    company_id: int,
    user_id: int,
    data: PasswordReset,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
):
    try:
        return platform_service.reset_tenant_password(
            db, current, company_id, user_id, data.new_password
        )
    except platform_service.PlatformError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- support access -------------------------------------------------------
@router.post("/tenants/{company_id}/impersonate", response_model=ImpersonateResponse)
def impersonate(
    company_id: int,
    data: ImpersonateRequest,
    db: Session = Depends(get_db),
    current: PlatformUser = Depends(get_current_platform_user),
):
    """Get a short-lived tenant token to see the shop's console as they see it.

    Logged before the token exists. Expires in 30 minutes regardless of the
    configured session length.
    """
    try:
        token, target = platform_service.impersonate(
            db, current, company_id, user_id=data.user_id, reason=data.reason
        )
    except platform_service.PlatformError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return ImpersonateResponse(
        access_token=token,
        expires_in_minutes=platform_service.IMPERSONATION_MINUTES,
        company_id=company_id,
        user_email=target.email,
        user_full_name=target.full_name,
    )


# --- audit ----------------------------------------------------------------
@router.get("/audit", response_model=list[AuditLogRead])
def list_audit(
    company_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(get_current_platform_user),
):
    return platform_service.list_audit(db, company_id=company_id, limit=min(limit, 500))
