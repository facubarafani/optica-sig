from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DiscountType, PaymentMethod, SaleStatus
from app.schemas.common import ORMBase, SoftDeleteRead


# --- payment accounts (cuentas) -------------------------------------------
class PaymentAccountCreate(BaseModel):
    name: str
    method: PaymentMethod | None = None
    notes: str | None = None


class PaymentAccountUpdate(BaseModel):
    name: str | None = None
    method: PaymentMethod | None = None
    notes: str | None = None
    is_active: bool | None = None


class PaymentAccountRead(SoftDeleteRead):
    name: str
    method: PaymentMethod | None = None
    notes: str | None = None


# --- payments --------------------------------------------------------------
class PaymentCreate(BaseModel):
    """Money received. ``amount`` is what the customer actually handed over."""

    amount: Decimal = Field(gt=0)
    method: PaymentMethod = PaymentMethod.CASH
    account_id: int | None = None
    reference: str | None = None
    note: str | None = None


class PaymentRead(ORMBase):
    id: int
    sale_id: int
    amount: Decimal
    method: PaymentMethod
    account_id: int | None = None
    paid_at: datetime
    reference: str | None = None
    note: str | None = None


# --- sale lines ------------------------------------------------------------
class SaleItemCreate(BaseModel):
    product_id: int
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    # Leave unset and services.pricing resolves it; set it to override.
    unit_price: Decimal | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = None

    @field_validator("discount_value")
    @classmethod
    def _non_negative(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("El descuento no puede ser negativo.")
        return v


class SaleItemRead(ORMBase):
    id: int
    product_id: int
    quantity: Decimal
    unit_price: Decimal
    price_overridden: bool
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = None
    discount_amount: Decimal
    line_total: Decimal


# --- sales -----------------------------------------------------------------
class SaleCreate(BaseModel):
    customer_id: int | None = None
    branch_id: int | None = None
    items: list[SaleItemCreate] = Field(min_length=1)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = None
    # "Abonado": what was handed over at the counter. Several payments are
    # allowed from the start (cash now, card for the rest).
    payments: list[PaymentCreate] = Field(default_factory=list)
    promised_payment_date: date | None = None
    reminder_note: str | None = None
    notes: str | None = None
    status: SaleStatus = SaleStatus.CONFIRMED

    @field_validator("discount_value")
    @classmethod
    def _non_negative(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("El descuento no puede ser negativo.")
        return v


class SaleUpdate(BaseModel):
    """Only the things that stay editable after the fact.

    Lines and money are not: correcting a sale means cancelling it and issuing
    a new one, so stock and the payment trail stay honest.
    """

    status: SaleStatus | None = None
    promised_payment_date: date | None = None
    reminder_note: str | None = None
    notes: str | None = None


class SaleRead(ORMBase):
    id: int
    number: str
    status: SaleStatus
    sold_at: datetime
    customer_id: int | None = None
    branch_id: int | None = None
    salesperson_id: int | None = None
    subtotal: Decimal
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = None
    discount_amount: Decimal
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    promised_payment_date: date | None = None
    reminder_note: str | None = None
    notes: str | None = None
    is_active: bool
    items: list[SaleItemRead] = Field(default_factory=list)
    payments: list[PaymentRead] = Field(default_factory=list)


class SaleListRead(ORMBase):
    """The grid row — no lines, so listing many sales stays one query."""

    id: int
    number: str
    status: SaleStatus
    sold_at: datetime
    customer_id: int | None = None
    branch_id: int | None = None
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    promised_payment_date: date | None = None
    reminder_note: str | None = None
    is_active: bool


class PendingSummary(BaseModel):
    """Headline figures above the cuentas-pendientes list.

    Typed rather than a bare dict so the money stays Decimal on the way out —
    a float here would undo rule 6 at the last step.
    """

    count: int
    total_pending: Decimal
    overdue_amount: Decimal
    overdue_count: int
    due_today_amount: Decimal
    due_today_count: int
    undated_count: int


class SalePreviewItem(BaseModel):
    product_id: int
    quantity: Decimal
    unit_price: Decimal
    price_overridden: bool
    discount_amount: Decimal
    line_total: Decimal
    # Set when the price could not be resolved, so the form can say why.
    price_reason: str | None = None


class SalePreview(BaseModel):
    """What a sale *would* total, without writing anything.

    The form calls this on every change so the operator sees the real numbers
    before committing — and so the arithmetic lives in one place, server-side.
    """

    items: list[SalePreviewItem]
    subtotal: Decimal
    discount_amount: Decimal
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    currency: str | None = None
