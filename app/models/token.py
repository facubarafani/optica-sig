"""One-time links sent by email: invitations and password resets.

The row stores a **hash** of the token, never the token itself. The raw value
exists only in the email, so a database read — a leaked backup, a support
query, an SQL injection — hands over nothing usable. This is the same reason
passwords are hashed, and an invitation link is exactly as powerful as a
password: it sets one.

The hash is SHA-256 rather than bcrypt, deliberately. Bcrypt exists to make
*guessable* secrets expensive to attack; these tokens are 32 random bytes, so
there is nothing to guess. What we need instead is to look a token up by its
hash in one indexed query, which bcrypt's per-row salt makes impossible
without scanning every row.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IDMixin


class UserToken(IDMixin, Base):
    __tablename__ = "user_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Single use. Set the moment the token is spent, so a link forwarded on or
    # sitting in a mailbox cannot be replayed.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
