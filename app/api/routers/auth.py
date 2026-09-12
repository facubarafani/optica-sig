from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import SCOPE_TENANT, create_access_token
from app.models.auth import User
from app.schemas.auth import (
    CompanyChoice,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    SetPasswordRequest,
    Token,
    TokenCheck,
    UserRead,
)
from app.services import auth as auth_service
from app.services import invitations

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_BAD_CREDENTIALS = "Incorrect email or password"
_SUSPENDED = (
    "This account is suspended. Please contact support."
)


def _token_for(user: User) -> str:
    return create_access_token(
        user.id, extra={"company_id": user.company_id}, scope=SCOPE_TENANT
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Resolve credentials to a company, then issue a token.

    The company is *not* taken from configuration any more: it is whichever
    company the email and password actually open. When they open more than
    one, the caller gets the list and posts again with ``company_id``.
    """
    matches = auth_service.find_logins(
        db, payload.email, payload.password, payload.company_id
    )
    if not matches:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)

    active = [(u, c) for u, c in matches if c.is_active]
    if not active:
        # Right password, suspended shop — say so rather than blame the password.
        raise HTTPException(status.HTTP_403_FORBIDDEN, _SUSPENDED)

    if len(active) > 1:
        return LoginResponse(
            companies=[
                CompanyChoice(id=c.id, name=c.name, address=c.address)
                for _, c in active
            ]
        )

    user, _ = active[0]
    return LoginResponse(access_token=_token_for(user))


@router.post("/token", response_model=Token)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    """OAuth2 password flow so the Swagger 'Authorize' button works.

    Username field = email. The form flow has nowhere to render a company
    picker, so an ambiguous address is refused with an explanation instead of
    a silent guess at which shop was meant.
    """
    matches = auth_service.find_logins(db, form.username, form.password)
    active = [(u, c) for u, c in matches if c.is_active]
    if not matches:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)
    if not active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _SUSPENDED)
    if len(active) > 1:
        names = ", ".join(f"{c.name} (id={c.id})" for _, c in active)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This email exists at several companies ({names}). "
            "Use POST /api/auth/login with company_id.",
        )
    user, _ = active[0]
    return Token(access_token=_token_for(user))


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


# --- invitations & password reset ----------------------------------------
# The only endpoints in the application that anyone can call without
# credentials, so they are rate limited and deliberately uninformative.

@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, str],
)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Email a reset link, if that address has an account.

    Always answers the same thing. Confirming which addresses exist would turn
    this into a directory of every óptica's staff, and the person who really
    forgot their password learns nothing extra from a different message.
    """
    email = payload.email.strip().lower()
    # Two buckets: one stops hammering a single victim's inbox, the other
    # stops a caller walking a list of addresses.
    ratelimit.enforce(
        f"forgot:{email}", limit=5, window_seconds=3600,
        detail="Demasiados intentos para esa dirección. Probá de nuevo más tarde.",
    )
    ratelimit.enforce(
        f"forgot-ip:{ratelimit.client_ip(request)}", limit=20, window_seconds=3600,
        detail="Demasiados intentos. Probá de nuevo más tarde.",
    )
    sent = invitations.request_password_reset(db, email)
    logger.info("Password reset requested for %s — %d mail(s) sent", email, sent)
    return {"detail": "Si esa dirección tiene una cuenta, te llega un correo."}


@router.get("/password-token/{token}", response_model=TokenCheck)
def check_password_token(
    token: str, request: Request, db: Session = Depends(get_db)
) -> TokenCheck:
    """Validate a link before showing the form, so a dead link says so early."""
    ratelimit.enforce(
        f"token-ip:{ratelimit.client_ip(request)}", limit=60, window_seconds=3600,
        detail="Demasiados intentos. Probá de nuevo más tarde.",
    )
    try:
        row, user, company = invitations.resolve(db, token)
    except invitations.InvitationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return TokenCheck(
        purpose=row.purpose,
        email=user.email,
        full_name=user.full_name,
        company_name=company.name,
    )


@router.post("/set-password", response_model=LoginResponse)
def set_password(
    payload: SetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Spend an invitation or reset link and set the password.

    Hands back a session token on success, so accepting an invitation drops
    the user straight into their console instead of at a login form they would
    immediately fill in with what they just typed.
    """
    ratelimit.enforce(
        f"setpwd-ip:{ratelimit.client_ip(request)}", limit=30, window_seconds=3600,
        detail="Demasiados intentos. Probá de nuevo más tarde.",
    )
    try:
        user = invitations.consume(db, payload.token, payload.new_password)
    except invitations.InvitationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return LoginResponse(access_token=_token_for(user))
