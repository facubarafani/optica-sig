"""FastAPI dependencies: DB session, current user, company scope, permissions."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import SCOPE_PLATFORM, SCOPE_TENANT, decode_access_token
from app.models.auth import User
from app.models.company import Company
from app.models.platform import PlatformUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
platform_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin/token")

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def _subject(token: str, expected_scope: str) -> int:
    """Decode a token and return its subject id, or 401.

    A token minted for the other audience is rejected here rather than deeper
    in, so a provider token can never authenticate a shop endpoint even if a
    router forgets its permission dependency. Tokens issued before scopes
    existed carry no claim; they are read as tenant tokens, which is what they
    were.
    """
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise _CREDENTIALS_EXC
    if payload.get("scope", SCOPE_TENANT) != expected_scope:
        raise _CREDENTIALS_EXC
    try:
        return int(payload["sub"])
    except (TypeError, ValueError):
        raise _CREDENTIALS_EXC


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    user_id = _subject(token, SCOPE_TENANT)
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    # A suspended tenant stops working mid-session, not just at the next login.
    # Otherwise a shop cut off for non-payment keeps trading for the rest of
    # the day on the token it already holds.
    company = db.get(Company, user.company_id)
    if company is None or not company.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is suspended. Please contact support.",
        )
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


# --- platform (provider) side --------------------------------------------
def get_current_platform_user(
    token: str = Depends(platform_oauth2_scheme), db: Session = Depends(get_db)
) -> PlatformUser:
    """The provider operator behind an ``/api/admin`` call.

    Note what this deliberately does *not* do: derive a company. Platform
    endpoints work across tenants, so they take the company as an explicit
    argument and are the only place in the codebase allowed to.
    """
    user_id = _subject(token, SCOPE_PLATFORM)
    user = db.execute(
        select(PlatformUser).where(PlatformUser.id == user_id)
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    return user
