from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.models.auth import User
from app.schemas.auth import LoginRequest, Token, UserRead
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_for(user: User) -> Token:
    token = create_access_token(user.id, extra={"company_id": user.company_id})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    """JSON login. Single-tenant MVP resolves the company from settings."""
    user = auth_service.authenticate(
        db, settings.default_company_id, payload.email, payload.password
    )
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password"
        )
    return _token_for(user)


@router.post("/token", response_model=Token)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    """OAuth2 password flow so the Swagger 'Authorize' button works.

    Username field = email.
    """
    user = auth_service.authenticate(
        db, settings.default_company_id, form.username, form.password
    )
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password"
        )
    return _token_for(user)


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
