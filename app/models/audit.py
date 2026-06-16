"""Cross-cutting infrastructure: change history and auto-numbering."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin


class ChangeHistory(IDMixin, CompanyMixin, Base):
    """Generic audit trail for critical changes (price, cost, category, stock).

    Stores a (entity_type, entity_id, field, old, new) tuple with who/when.
    """

    __tablename__ = "change_history"

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(255))
    new_value: Mapped[str | None] = mapped_column(String(255))
    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NumberSequence(IDMixin, CompanyMixin, Base):
    """Per-company, per-document-kind auto-numbering counter.

    ``key`` is e.g. ``sale``, ``quote``, ``work_order``, ``repair``. Formatted
    output is ``f"{prefix}{value:0{padding}d}"`` (see services.numbering).
    """

    __tablename__ = "number_sequences"
    __table_args__ = (
        UniqueConstraint("company_id", "key", name="uq_number_sequence_key"),
    )

    key: Mapped[str] = mapped_column(String(40), nullable=False)
    prefix: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    padding: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
