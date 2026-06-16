"""Reusable model mixins: PK, timestamps, soft delete, company scoping."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class IDMixin:
    id: Mapped[int] = mapped_column(primary_key=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Logical deletion — records are never physically removed."""

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CompanyMixin:
    """Multi-tenant scoping. Every business row carries its company."""

    @declared_attr
    def company_id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(
            ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
