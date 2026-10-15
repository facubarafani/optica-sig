from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import DebtLight, DiscountType, PaymentMethod, ReminderTone, SaleStatus
from app.schemas.common import ORMBase, SoftDeleteRead
from app.schemas.invoicing import InvoiceRead


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


class InstallmentRateIn(BaseModel):
    """"6 cuotas, 20% de recargo" on one account."""

    installments: int = Field(ge=1, le=60)
    surcharge_percent: Decimal = Field(ge=0, le=500)


class InstallmentRateRead(ORMBase):
    installments: int
    surcharge_percent: Decimal


class PaymentAccountRead(SoftDeleteRead):
    name: str
    method: PaymentMethod | None = None
    notes: str | None = None
    # What paying in cuotas through this account costs, fewest cuotas first.
    installment_rates: list[InstallmentRateRead] = Field(default_factory=list)


# --- payments --------------------------------------------------------------
class PaymentCreate(BaseModel):
    """Money received.

    ``amount`` is the part of the price it covers. A credit card in cuotas may
    add a recargo on top (``surcharge_type`` + ``surcharge_value``, read like
    a discount: a percentage of ``amount`` or a fixed sum). The recargo raises
    the sale's total, and the stored payment is amount + recargo: what was
    actually charged.
    """

    amount: Decimal = Field(gt=0)
    method: PaymentMethod = PaymentMethod.CASH
    account_id: int | None = None
    reference: str | None = None
    # Cuotas: only a credit card is paid in instalments.
    installments: int | None = Field(default=None, ge=1, le=60)
    surcharge_type: DiscountType | None = None
    surcharge_value: Decimal | None = Field(default=None, ge=0)
    note: str | None = None

    @model_validator(mode="after")
    def _installments_need_credit(self) -> "PaymentCreate":
        if self.method is not PaymentMethod.CREDIT_CARD:
            if self.installments is not None:
                raise ValueError("Las cuotas son sólo para pagos con tarjeta de crédito.")
            if self.surcharge_value:
                raise ValueError("El recargo es sólo para pagos con tarjeta de crédito.")
        return self


class PaymentRead(ORMBase):
    id: int
    sale_id: int
    amount: Decimal
    method: PaymentMethod
    account_id: int | None = None
    paid_at: datetime
    reference: str | None = None
    installments: int | None = None
    # The recargo inside ``amount``.
    surcharge_amount: Decimal = Decimal("0")
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
    # The product as it reads today, so a sale's detail needs no catalogue page.
    product_code: str | None = None
    product_description: str | None = None


# --- payment reminders by WhatsApp (services.payment_reminders) ------------
class PaymentReminderRead(ORMBase):
    id: int
    tone: ReminderTone
    # The number it went to, as wa.me takes it.
    phone: str
    sent_at: datetime
    sent_by_name: str | None = None


class ReminderMessage(BaseModel):
    tone: ReminderTone
    text: str


class ReminderDraft(BaseModel):
    """What the WhatsApp button opens with: the message in each tone, and the
    customer's registered phone as WhatsApp takes it."""

    sale_id: int
    sale_number: str
    balance: Decimal
    promised_payment_date: date | None = None
    customer_id: int
    customer_name: str
    # As typed on the customer's file.
    phone: str | None = None
    # For the wa.me link; None when the phone cannot be read, and then
    # phone_problem says why.
    whatsapp_number: str | None = None
    whatsapp_display: str | None = None
    phone_problem: str | None = None
    suggested_tone: ReminderTone
    messages: list[ReminderMessage]
    # The ones already sent for this sale, newest first.
    reminders: list[PaymentReminderRead] = Field(default_factory=list)


class ReminderSend(BaseModel):
    """The message the seller is sending. No number: it is the customer's."""

    tone: ReminderTone
    message: str = Field(max_length=2000)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El mensaje está vacío.")
        return v


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
    surcharge_amount: Decimal = Decimal("0")
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    promised_payment_date: date | None = None
    reminder_note: str | None = None
    notes: str | None = None
    is_active: bool
    items: list[SaleItemRead] = Field(default_factory=list)
    payments: list[PaymentRead] = Field(default_factory=list)
    # Its comprobantes, oldest first, rejected attempts included.
    invoices: list[InvoiceRead] = Field(default_factory=list)
    # The WhatsApp reminders it got, newest first.
    payment_reminders: list[PaymentReminderRead] = Field(default_factory=list)
    # Only on the response that created the sale: lines it sold below zero.
    stock_warnings: list[str] = Field(default_factory=list)


class SaleListRead(ORMBase):
    """The grid row — no lines, so listing many sales stays one query."""

    id: int
    number: str
    status: SaleStatus
    sold_at: datetime
    customer_id: int | None = None
    branch_id: int | None = None
    salesperson_id: int | None = None
    # Named on the row, so a list never depends on a customer page of 100.
    customer_name: str | None = None
    salesperson_name: str | None = None
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    promised_payment_date: date | None = None
    reminder_note: str | None = None
    is_active: bool
    invoices: list[InvoiceRead] = Field(default_factory=list)
    # The semáforo of what it still owes; None when it owes nothing.
    debt_light: DebtLight | None = None
    # So a list of debts says who was already written to.
    last_payment_reminder: PaymentReminderRead | None = None


class LightFigures(BaseModel):
    amount: Decimal
    count: int


class PendingSummary(BaseModel):
    """Headline figures above the cuentas-pendientes list.

    Typed rather than a bare dict so the money stays Decimal on the way out —
    a float here would undo rule 6 at the last step.
    """

    count: int
    total_pending: Decimal
    # The same debts by semáforo colour: red + yellow + green = total_pending.
    lights: dict[DebtLight, "LightFigures"]
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
    # The recargo the payments sent along would add. total includes it, so
    # what the payments may cover is total - surcharge_amount.
    surcharge_amount: Decimal = Decimal("0")
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    currency: str | None = None
    # Products this sale would leave below zero. Never blocks the sale.
    stock_warnings: list[str] = Field(default_factory=list)


# --- the summary on Inicio -------------------------------------------------
class StatsFigures(BaseModel):
    revenue: Decimal
    count: int
    average_ticket: Decimal
    collected: Decimal


class StatsChange(BaseModel):
    """Percent change against the same stretch of the previous period; None
    when that stretch sold nothing, so there is nothing to compare with."""

    revenue: Decimal | None = None
    count: Decimal | None = None
    average_ticket: Decimal | None = None
    collected: Decimal | None = None


class StatsBucket(BaseModel):
    key: str
    label: str
    # None for a bar still in the future (later today, later this month).
    revenue: Decimal | None = None
    count: int | None = None
    # The previous period at the same position, all of it.
    previous: Decimal


class StatsMethod(BaseModel):
    method: PaymentMethod
    amount: Decimal


class StatsVariant(BaseModel):
    code: str
    label: str              # its colours, "Carey" or "Negro, Dorado"
    quantity: Decimal
    revenue: Decimal


class StatsProduct(BaseModel):
    """A model (style) with what its colours sold, or a plain article."""

    product_id: int
    code: str
    description: str | None = None
    quantity: Decimal
    revenue: Decimal
    # Its colours, most sold first. Empty for an article with no family.
    variants: list[StatsVariant] = Field(default_factory=list)


class StatsShare(BaseModel):
    """One slice of the shop's period (a seller, a branch): its sales, its
    part of the whole, and how it went against its own same stretch before."""

    revenue: Decimal
    count: int
    average_ticket: Decimal
    # Percent of the shop's revenue; None when the shop sold nothing.
    share: Decimal | None = None
    previous_revenue: Decimal
    change: Decimal | None = None


class StatsSeller(StatsShare):
    # None gathers the sales nobody is named on.
    user_id: int | None = None
    name: str
    is_active: bool = True
    owed: Decimal
    # Line and sale discounts, and their percent of the list price sold.
    discount_amount: Decimal
    discount_rate: Decimal | None = None
    # Lines whose price was typed in instead of resolved.
    price_overrides: int
    cancelled: int
    quotes: int
    # Of those presupuestos, how many the customer went on to buy after.
    quotes_won: int


class StatsBranch(StatsShare):
    branch_id: int | None = None
    name: str


class StatsProductType(BaseModel):
    product_type_id: int | None = None
    name: str
    revenue: Decimal
    quantity: Decimal
    share: Decimal | None = None


class SalesStats(StatsFigures):
    period: str
    start: date
    previous_start: date
    # What the period's sales left owing.
    owed: Decimal
    previous: StatsFigures
    change: StatsChange
    series: list[StatsBucket]
    methods: list[StatsMethod]
    top_products: list[StatsProduct]
    # The owner's breakdowns. Empty on a seller's own summary.
    discount_rate: Decimal | None = None
    sellers: list[StatsSeller] = Field(default_factory=list)
    branches: list[StatsBranch] = Field(default_factory=list)
    product_types: list[StatsProductType] = Field(default_factory=list)


class OpenQuote(BaseModel):
    """A presupuesto whose customer has not bought since: who to call, and
    what it was for."""

    id: int
    number: str
    sold_at: datetime
    salesperson_id: int | None = None
    total: Decimal
    customer_id: int
    customer_name: str
    customer_phone: str | None = None
    items: list[str] = Field(default_factory=list)
