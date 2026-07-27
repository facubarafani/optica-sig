"""Pricing & costs: price lists, their categories and cost history.

A price list is a ladder of **categories** — steps named ``AA``, ``AB``, ``AC``…
each holding one price. The categories belong to the list, so every list decides
on its own how many steps it has: "Mostrador" can run AA..AL while "Mayorista"
runs AA..BD.

Products are tagged with the category **code**, not with a row id
(``Product.price_category_code``). That is what lets the same product be priced
by whichever list applies — the code ``AB`` is looked up inside the list that
ends up being used. Resolution lives in ``services.pricing.resolve_price()``.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin


class PriceList(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "price_lists"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_price_list_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Optional scoping of a list to a product type ("listas por tipo de producto").
    product_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_types.id", ondelete="SET NULL")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # See enums.Currency: a label, not a conversion. Kept as a 3-letter code for
    # consistency with companies.currency.
    currency: Mapped[str] = mapped_column(
        String(3), default="ARS", server_default="ARS", nullable=False
    )


class PriceCategory(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One step of a price list: a code (``AA``, ``AB``…) and its price.

    ``position`` is the 0-based rank in the ladder and drives both the display
    order and the code sequence — codes are never reused, so deactivating a
    category leaves its code retired rather than shifting everything below it.
    """

    __tablename__ = "price_categories"
    __table_args__ = (
        UniqueConstraint("price_list_id", "code", name="uq_price_category_code"),
    )

    price_list_id: Mapped[int] = mapped_column(
        ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0", nullable=False
    )
    position: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )


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
