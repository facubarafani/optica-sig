"""Invitations and password resets: mint a one-time link, spend it once.

The security properties this file is responsible for:

- **The token is never stored.** Only its SHA-256 lands in the database, so a
  leaked backup cannot be replayed. See ``models/token.py`` for why SHA-256
  and not bcrypt.
- **One live link per purpose.** Issuing a new one voids any outstanding
  token of the same kind, so an old email in a mailbox stops working the
  moment a new one is requested.
- **Single use, then expired.** ``used_at`` is stamped in the same transaction
  that changes the password.
- **No account enumeration.** ``request_password_reset`` behaves identically
  whether or not the address exists; only the caller's inbox differs.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.auth import User
from app.models.company import Company
from app.models.enums import TokenPurpose
from app.models.token import UserToken
from app.services import email as email_service
from app.services import email_templates

# 32 bytes of urandom. Long enough that guessing is not a threat model, short
# enough to survive a mail client wrapping the line.
TOKEN_BYTES = 32

MIN_PASSWORD_LENGTH = 8


class InvitationError(Exception):
    """Raised when a link is unusable or a password is rejected."""


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl_hours(purpose: TokenPurpose) -> int:
    return (
        settings.invitation_ttl_hours
        if purpose is TokenPurpose.INVITATION
        else settings.password_reset_ttl_hours
    )


def build_link(raw_token: str) -> str:
    """The URL that lands in the email.

    The token rides in the **fragment**, not the query string. Fragments are
    never sent to the server, so the token stays out of access logs, proxy
    logs and the Referer header — the console's JS reads it client-side and
    posts it back over HTTPS.
    """
    base = settings.public_base_url.rstrip("/")
    return f"{base}/app#/password/{quote(raw_token)}"


def issue(
    db: Session, user: User, purpose: TokenPurpose, *, commit: bool = True
) -> str:
    """Create a one-time token for ``user`` and return the raw value.

    The raw value is returned exactly once, to be put in an email. It cannot be
    recovered afterwards.
    """
    # Void any outstanding link of the same kind first.
    for old in db.execute(
        select(UserToken).where(
            UserToken.user_id == user.id,
            UserToken.purpose == purpose.value,
            UserToken.used_at.is_(None),
        )
    ).scalars():
        old.used_at = _now()
        db.add(old)

    raw = secrets.token_urlsafe(TOKEN_BYTES)
    db.add(
        UserToken(
            user_id=user.id,
            purpose=purpose.value,
            token_hash=_hash(raw),
            expires_at=_now() + timedelta(hours=_ttl_hours(purpose)),
        )
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return raw


def resolve(db: Session, raw_token: str) -> tuple[UserToken, User, Company]:
    """Look a token up and check it is still good, or raise."""
    row = db.execute(
        select(UserToken).where(UserToken.token_hash == _hash(raw_token or ""))
    ).scalar_one_or_none()
    if row is None:
        raise InvitationError("El enlace no es válido.")
    if row.used_at is not None:
        raise InvitationError("Ese enlace ya fue usado. Pedí uno nuevo.")
    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite hands back naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < _now():
        raise InvitationError("El enlace venció. Pedí uno nuevo.")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise InvitationError("La cuenta ya no está activa.")
    company = db.get(Company, user.company_id)
    if company is None or not company.is_active:
        raise InvitationError("La cuenta está suspendida. Contactá a soporte.")
    return row, user, company


def consume(db: Session, raw_token: str, new_password: str) -> User:
    """Spend a token and set the password, in one transaction."""
    if len(new_password or "") < MIN_PASSWORD_LENGTH:
        raise InvitationError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    row, user, _ = resolve(db, raw_token)
    user.hashed_password = hash_password(new_password)
    row.used_at = _now()
    db.add_all([user, row])
    db.commit()
    db.refresh(user)
    return user


# --- the two flows --------------------------------------------------------
def send_invitation(db: Session, user: User, company: Company) -> bool:
    raw = issue(db, user, TokenPurpose.INVITATION)
    hours = settings.invitation_ttl_hours
    msg = email_templates.invitation(
        full_name=user.full_name,
        company_name=company.name,
        link=build_link(raw),
        hours=hours,
    )
    return email_service.send(
        email_service.Message(
            to=user.email, subject=msg.subject, text=msg.text, html=msg.html
        )
    )


def request_password_reset(db: Session, email: str) -> int:
    """Email a reset link to every account using this address.

    Returns how many were sent, for logging only — the endpoint must answer
    identically whether that is zero or three, or it becomes a tool for
    checking which addresses have accounts.

    One address can belong to accounts at several ópticas (``users`` is unique
    on company + email), so each gets its own link and the mail names the shop.
    """
    rows = db.execute(
        select(User, Company)
        .join(Company, Company.id == User.company_id)
        .where(
            User.email == (email or "").strip().lower(),
            User.is_active.is_(True),
            Company.is_active.is_(True),
        )
    ).all()

    sent = 0
    for user, company in rows:
        raw = issue(db, user, TokenPurpose.PASSWORD_RESET)
        hours = settings.password_reset_ttl_hours
        msg = email_templates.password_reset(
            full_name=user.full_name,
            company_name=company.name,
            link=build_link(raw),
            hours=hours,
        )
        if email_service.send(
            email_service.Message(
                to=user.email, subject=msg.subject, text=msg.text, html=msg.html
            )
        ):
            sent += 1
    return sent


def set_unusable_password(user: User) -> None:
    """Leave an account with no password anybody can type.

    Used when a user is created to be invited rather than handed credentials:
    the row is real and can be listed and edited, but no login succeeds until
    the invitation is accepted.
    """
    user.hashed_password = hash_password(secrets.token_urlsafe(32))
