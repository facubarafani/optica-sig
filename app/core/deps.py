"""FastAPI dependencies: DB session, current user, company scope, permissions."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.auth import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise _CREDENTIALS_EXC
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise _CREDENTIALS_EXC
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    return user


def get_company_id(current_user: User = Depends(get_current_user)) -> int:
    """Active company is derived from the authenticated user (multi-tenant ready)."""
    return current_user.company_id


def require_permission(code: str) -> Callable[..., User]:
    """Dependency factory enforcing a permission code (superusers bypass)."""

    def checker(current_user: User = Depends(get_current_user)) -> User:
        codes = current_user.permission_codes
        if "*" in codes or code in codes:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {code}",
        )

    return checker
