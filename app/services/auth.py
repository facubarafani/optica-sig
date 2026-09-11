"""User & role management plus authentication."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.auth import Permission, Role, User
from app.models.company import Company
from app.schemas.auth import RoleCreate, RoleUpdate, UserCreate, UserUpdate


class AuthError(Exception):
    """Raised on auth/RBAC rule violations."""


class SuspendedCompanyError(AuthError):
    """Credentials were right, but the shop they belong to is suspended.

    Kept distinct from "wrong password" on purpose: telling a paying customer
    their password is wrong when we are the ones who cut them off wastes their
    afternoon and generates a support call.
    """


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


def find_logins(
    db: Session, email: str, password: str, company_id: int | None = None
) -> list[tuple[User, Company]]:
    """Resolve credentials without being told which company they belong to.

    ``users`` is unique on (company_id, email), so one address can legitimately
    exist at two shops — an owner with two companies, an accountant working for
    several. This returns every account the password actually opens, and the
    router decides: one means log straight in, several mean ask which.

    Suspended companies are included; the caller reports them differently from
    a bad password (see :class:`SuspendedCompanyError`). Password verification
    runs per candidate, which is fine because the candidate list is one or two
    rows in every realistic case.
    """
    email = email.strip().lower()
    stmt = (
        select(User, Company)
        .join(Company, Company.id == User.company_id)
        .where(func.lower(User.email) == email, User.is_active.is_(True))
        .order_by(Company.name, Company.id)
    )
    if company_id is not None:
        stmt = stmt.where(User.company_id == company_id)
    rows = db.execute(stmt).all()
    return [
        (user, company)
        for user, company in rows
        if verify_password(password, user.hashed_password)
    ]


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
