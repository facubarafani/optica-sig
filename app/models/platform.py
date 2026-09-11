"""Platform (provider) identity — the people who sell and run SGI.

This is deliberately *not* ``users``. A tenant user always carries a
``company_id`` and can never see past it; a platform user has no company at
all and works across every tenant. Keeping them in separate tables means the
question "can this token reach another shop's data?" is answered by which
table the subject came from, rather than by remembering a flag check — see
``app/core/deps.py``, where the two token scopes reject each other.

``users.is_superuser`` is unrelated: it means "every permission *inside my
company*", and must never be widened to mean this.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IDMixin, SoftDeleteMixin, TimestampMixin


class PlatformUser(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A provider operator: you, and whoever else runs the business with you.

    Every platform user can do everything the admin console offers. There is
    no RBAC here on purpose — the population is a handful of people who all
    need the same access, and inventing roles for them would be ceremony. If
    that changes, this is where a role column goes.
    """

    __tablename__ = "platform_users"

    email: Mapped[str] = mapped_column(
        String(150), unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformAuditLog(IDMixin, Base):
    """Every cross-tenant action a platform user takes.

    Not ``ChangeHistory``: that one is per-company and belongs to the shop's
    own data. This records what *we* did to a shop — provisioning it,
    suspending it, and above all logging into it. Impersonation is real access
    to a customer's sales, so it is written down before the token is minted,
    never after.

    ``company_id`` is nullable because some actions (a failed lookup, a future
    platform-wide setting) belong to no tenant.
    """

    __tablename__ = "platform_audit_log"

    platform_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    # The tenant user an impersonation was performed *as*. Null for everything
    # else. Deliberately not a FK with RESTRICT: deleting is not a thing we do,
    # but the log must survive whatever happens to the row it points at.
    target_user_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
