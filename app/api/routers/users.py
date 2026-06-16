from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import Permission, Role, User
from app.schemas.auth import (
    PermissionRead,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services import auth as auth_service

router = APIRouter(tags=["users & rbac"])


# --- permissions (read-only catalogue) -----------------------------------
@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("users:read")),
):
    return list(db.execute(select(Permission).order_by(Permission.code)).scalars().all())


# --- roles ----------------------------------------------------------------
@router.get("/roles", response_model=list[RoleRead])
def list_roles(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("users:read")),
):
    return list(
        db.execute(
            select(Role).where(Role.company_id == company_id).order_by(Role.id)
        ).scalars().all()
    )


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    data: RoleCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("users:write")),
):
    try:
        return auth_service.create_role(db, company_id, data)
    except auth_service.AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.put("/roles/{role_id}", response_model=RoleRead)
def update_role(
    role_id: int,
    data: RoleUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("users:write")),
):
    role = db.execute(
        select(Role).where(Role.id == role_id, Role.company_id == company_id)
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    try:
        return auth_service.update_role(db, role, data)
    except auth_service.AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- users ----------------------------------------------------------------
@router.get("/users", response_model=list[UserRead])
def list_users(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("users:read")),
):
    stmt = select(User).where(User.company_id == company_id)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    return list(db.execute(stmt.order_by(User.id)).scalars().all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("users:write")),
):
    try:
        return auth_service.create_user(db, company_id, data)
    except auth_service.AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("users:read")),
):
    user = db.execute(
        select(User).where(User.id == user_id, User.company_id == company_id)
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.put("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("users:write")),
):
    user = db.execute(
        select(User).where(User.id == user_id, User.company_id == company_id)
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    try:
        return auth_service.update_user(db, company_id, user, data)
    except auth_service.AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
