"""Ventas: the sale, its lines, the money received and where it landed.

Shapes follow ``docs/ER_DIAGRAM.md`` (SALE / SALE_ITEM / PAYMENT), with three
additions the diagram did not cover: discounts (per line and per sale), the
account a payment landed in, and the promise-to-pay reminder that drives the
"cuentas pendientes" screen.

Money is never recomputed on read: ``subtotal``/``total``/``paid_amount``/
``balance`` are stored snapshots, written by ``services.sales`` whenever a sale
or one of its payments changes. A price that moves next month must not silently
rewrite what a customer was charged today.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import DiscountType, PaymentMethod, SaleStatus

if TYPE_CHECKING:
    from app.models.product import Product

MONEY = Numeric(12, 2)

# Both of these are used by more than one table. Sharing a single type object
# (rather than constructing SAEnum twice with the same name) is what keeps
# Postgres to one CREATE TYPE per enum.
PAYMENT_METHOD = SAEnum(PaymentMethod, name="payment_method")
DISCOUNT_TYPE = SAEnum(DiscountType, name="discount_type")


class PaymentAccount(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Where money actually lands: "Santander", "MercadoPago", "Caja mostrador".

    Master data so the shop can add its own without a deploy. ``method`` is the
    payment method this account is normally used with — the sale form pre-picks
    it — but nothing forbids a transfer into an account tagged as card.
    """

    __tablename__ = "payment_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_payment_account_name"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    method: Mapped[PaymentMethod | None] = mapped_column(PAYMENT_METHOD)
    notes: Mapped[str | None] = mapped_column(String(255))


class Sale(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sales"
    __table_args__ = (UniqueConstraint("company_id", "number", name="uq_sale_number"),)

    # Auto-assigned by services.numbering (prefix "V-"); never set by hand.
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[SaleStatus] = mapped_column(
        SAEnum(SaleStatus, name="sale_status"),
        default=SaleStatus.CONFIRMED,
        server_default=SaleStatus.CONFIRMED.name,
        nullable=False,
    )
    sold_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL")
    )
    salesperson_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # --- money (all stored, see the module docstring) ---
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    # Discount on the subtotal, on top of any per-line discounts.
    discount_type: Mapped[DiscountType | None] = mapped_column(DISCOUNT_TYPE)
    discount_value: Mapped[Decimal | None] = mapped_column(MONEY)
    # What that discount worked out to in money, so a receipt never re-derives it.
    discount_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    balance: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)

    # --- recordatorio: what the customer promised, and what to remember ---
    promised_payment_date: Mapped[date | None] = mapped_column(Date, index=True)
    reminder_note: Mapped[str | None] = mapped_column(String(255))

    notes: Mapped[str | None] = mapped_column(String(500))

    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list["SalePayment"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", lazy="selectin"
    )


class SaleItem(IDMixin, CompanyMixin, Base):
    """One line. ``unit_price`` is a snapshot of what was charged, resolved by
    ``services.pricing`` at sale time unless the seller typed one in."""

    __tablename__ = "sale_items"

    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(MONEY, default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # True when the seller overrode the resolved price — worth seeing on a report.
    price_overridden: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    discount_type: Mapped[DiscountType | None] = mapped_column(DISCOUNT_TYPE)
    discount_value: Mapped[Decimal | None] = mapped_column(MONEY)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)

    sale: Mapped["Sale"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(lazy="joined")


class SalePayment(IDMixin, CompanyMixin, Base):
    """Money received against a sale. A sale can collect many over time — that
    is what makes a balance shrink and a "cuenta pendiente" disappear."""

    __tablename__ = "sale_payments"

    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(PAYMENT_METHOD, nullable=False)
    # Which account it landed in. Optional: cash in the drawer often has none.
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_accounts.id", ondelete="SET NULL")
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reference: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    sale: Mapped["Sale"] = relationship(back_populates="payments")
