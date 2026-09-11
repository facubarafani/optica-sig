"""Password hashing and JWT helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token audiences. A tenant token authenticates a ``users`` row and is scoped
# to one company; a platform token authenticates a ``platform_users`` row and
# has no company at all. They are minted with the same secret, so the claim is
# what keeps them apart: the dependencies in ``app.core.deps`` refuse a token
# whose scope is not the one they expect. Without this a provider token would
# sail through every tenant endpoint, and vice versa.
SCOPE_TENANT = "tenant"
SCOPE_PLATFORM = "platform"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str | int,
    extra: dict[str, Any] | None = None,
    *,
    scope: str = SCOPE_TENANT,
    expires_minutes: int | None = None,
) -> str:
    """Mint a JWT. ``scope`` decides which set of endpoints will accept it.

    ``expires_minutes`` overrides the configured lifetime — impersonation uses
    it to hand out a token that dies in half an hour rather than in a day.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire, "scope": scope}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
