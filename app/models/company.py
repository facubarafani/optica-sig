"""Company (tenant root) and per-company settings."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IDMixin, SoftDeleteMixin, TimestampMixin


class Company(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """The tenant root. All other business rows reference it via company_id."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(20))  # CUIT
    email: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="ARS", nullable=False)


class CompanySettings(IDMixin, TimestampMixin, Base):
    """General system configuration for a company (one row per company)."""

    __tablename__ = "company_settings"

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="ARS", nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), default="America/Argentina/Buenos_Aires", nullable=False
    )
    allow_negative_stock: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    default_branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL")
    )
    default_price_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_lists.id", ondelete="SET NULL")
    )
    low_stock_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
