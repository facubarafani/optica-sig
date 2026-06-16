"""Stock levels (per product/branch) and the movement ledger.

Stock is never edited directly — every change is an append to ``stock_movements``
applied through ``services.stock.apply_movement``, which keeps ``stock_levels``
in sync. ``resulting_quantity`` snapshots the level after the movement for audit.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin
from app.models.enums import StockMovementType


class StockLevel(IDMixin, CompanyMixin, Base):
    __tablename__ = "stock_levels"
    __table_args__ = (
        UniqueConstraint("product_id", "branch_id", name="uq_stock_product_branch"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    # Optional per-branch override of Product.min_stock.
    min_stock: Mapped[float | None] = mapped_column(Numeric(12, 2))


class StockMovement(IDMixin, CompanyMixin, Base):
    __tablename__ = "stock_movements"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    movement_type: Mapped[StockMovementType] = mapped_column(
        SAEnum(StockMovementType, name="stock_movement_type"), nullable=False
    )
    # Signed delta actually applied to the branch level: positive for inbound /
    # transfer-in, negative for outbound / transfer-out, signed for adjustments.
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    resulting_quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # For transfers: the other branch involved (two movements are written).
    counterpart_branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL")
    )
    reference: Mapped[str | None] = mapped_column(String(80))  # e.g. doc number
    note: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
