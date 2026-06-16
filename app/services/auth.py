"""User & role management plus authentication."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.auth import Permission, Role, User
from app.schemas.auth import RoleCreate, RoleUpdate, UserCreate, UserUpdate


class AuthError(Exception):
    """Raised on auth/RBAC rule violations."""


# --- lookups --------------------------------------------------------------
def get_user_by_email(db: Session, company_id: int, email: str) -> User | None:
    return db.execute(
        select(User).where(User.company_id == company_id, User.email == email)
    ).scalar_one_or_none()


def authenticate(
    db: Session, company_id: int, email: str, password: str
) -> User | None:
    user = get_user_by_email(db, company_id, email)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def _load_roles(db: Session, company_id: int, role_ids: list[int]) -> list[Role]:
    if not role_ids:
        return []
    roles = list(
        db.execute(
            select(Role).where(
                Role.company_id == company_id, Role.id.in_(role_ids)
            )
        ).scalars().all()
    )
    missing = set(role_ids) - {r.id for r in roles}
    if missing:
        raise AuthError(f"Unknown role ids: {sorted(missing)}")
    return roles


def _load_permissions(db: Session, permission_ids: list[int]) -> list[Permission]:
    if not permission_ids:
        return []
    perms = list(
        db.execute(
            select(Permission).where(Permission.id.in_(permission_ids))
        ).scalars().all()
    )
    missing = set(permission_ids) - {p.id for p in perms}
    if missing:
        raise AuthError(f"Unknown permission ids: {sorted(missing)}")
    return perms


# --- users ----------------------------------------------------------------
def create_user(db: Session, company_id: int, data: UserCreate) -> User:
    if get_user_by_email(db, company_id, data.email):
        raise AuthError(f"A user with email {data.email} already exists.")
    user = User(
        company_id=company_id,
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        is_superuser=data.is_superuser,
        branch_id=data.branch_id,
        roles=_load_roles(db, company_id, data.role_ids),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, company_id: int, user: User, data: UserUpdate) -> User:
    payload = data.model_dump(exclude_unset=True)
    if "password" in payload and payload["password"]:
        user.hashed_password = hash_password(payload.pop("password"))
    else:
        payload.pop("password", None)
    if "role_ids" in payload:
        user.roles = _load_roles(db, company_id, payload.pop("role_ids") or [])
    for field, value in payload.items():
        setattr(user, field, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# --- roles ----------------------------------------------------------------
def create_role(db: Session, company_id: int, data: RoleCreate) -> Role:
    role = Role(
        company_id=company_id,
        name=data.name,
        description=data.description,
        permissions=_load_permissions(db, data.permission_ids),
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def update_role(db: Session, role: Role, data: RoleUpdate) -> Role:
    payload = data.model_dump(exclude_unset=True)
    if "permission_ids" in payload:
        role.permissions = _load_permissions(db, payload.pop("permission_ids") or [])
    for field, value in payload.items():
        setattr(role, field, value)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role
