"""Pricing & costs: price categories, price lists/items and cost history.

Pricing is category-based: each product belongs to a price category, and a price
list assigns a single price per category. "El precio por categoría es único por
empresa" — enforced by the unique constraint on (price_list_id, price_category_id).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin


class PriceCategory(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "price_categories"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_price_category_name"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))


class PriceList(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "price_lists"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_price_list_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Optional scoping of a list to a product type ("listas por tipo de producto").
    product_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_types.id", ondelete="SET NULL")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PriceListItem(IDMixin, CompanyMixin, TimestampMixin, Base):
    __tablename__ = "price_list_items"
    __table_args__ = (
        UniqueConstraint(
            "price_list_id", "price_category_id", name="uq_price_list_category"
        ),
    )

    price_list_id: Mapped[int] = mapped_column(
        ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False
    )
    price_category_id: Mapped[int] = mapped_column(
        ForeignKey("price_categories.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)


class CostHistory(IDMixin, CompanyMixin, Base):
    """Append-only trail of product cost changes."""

    __tablename__ = "cost_history"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    new_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
