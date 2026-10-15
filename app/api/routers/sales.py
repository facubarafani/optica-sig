"""Ventas, their payments, and the accounts money lands in."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.enums import DebtLight, SaleStatus
from app.models.sales import PaymentAccount
from app.schemas.sales import (
    InstallmentRateIn,
    OpenQuote,
    PaymentAccountCreate,
    PaymentAccountRead,
    PaymentAccountUpdate,
    PaymentCreate,
    PaymentReminderRead,
    PendingSummary,
    ReminderDraft,
    ReminderSend,
    SaleCreate,
    SaleListRead,
    SalePreview,
    SaleRead,
    SalesStats,
    SaleUpdate,
)
from app.services import clock, invoicing, payment_reminders
from app.services import sales as sales_service
from app.services import sales_stats

router = APIRouter()
accounts = CRUDBase(PaymentAccount)

# --- cuentas (Santander, MercadoPago, caja...) ------------------------------
router.include_router(
    build_crud_router(
        prefix="/payment-accounts",
        tags=["sales"],
        crud=accounts,
        create_schema=PaymentAccountCreate,
        update_schema=PaymentAccountUpdate,
        read_schema=PaymentAccountRead,
        permission="sales",
    )
)



@router.put("/payment-accounts/{account_id}/installment-rates",
            response_model=PaymentAccountRead, tags=["sales"])
def set_installment_rates(
    account_id: int,
    rates: list[InstallmentRateIn],
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:write")),
):
    """Replace the account's recargos por cuotas, the whole table at once."""
    account = accounts.get(db, account_id, company_id=company_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta inexistente.")
    try:
        return sales_service.set_installment_rates(db, account, rates, company_id=company_id)
    except sales_service.SaleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


sales = APIRouter(prefix="/sales", tags=["sales"])


def _get_or_404(db: Session, sale_id: int, company_id: int):
    sale = sales_service.get_sale(db, sale_id, company_id=company_id)
    if sale is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Venta inexistente.")
    return sale


@sales.get("", response_model=list[SaleListRead])
def list_sales(
    q: str | None = None,
    # Aliased because `status` is fastapi's status-code module in this file.
    sale_status: SaleStatus | None = Query(None, alias="status"),
    customer_id: int | None = None,
    branch_id: int | None = None,
    salesperson_id: int | None = None,
    pending_only: bool = False,
    overdue_only: bool = False,
    light: DebtLight | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    sold_from: date | None = None,
    sold_to: date | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    """``q`` matches the sale number, the customer (name or document) and the
    reminder note, ignoring case and accents. ``light`` keeps the debts of one
    semáforo colour (red, yellow, green)."""
    return sales_service.list_sales(
        db, company_id=company_id, q=q, status=sale_status, customer_id=customer_id,
        branch_id=branch_id, salesperson_id=salesperson_id,
        pending_only=pending_only, overdue_only=overdue_only, light=light,
        due_from=due_from, due_to=due_to, sold_from=sold_from, sold_to=sold_to,
        limit=limit,
    )


@sales.get("/pending/summary", response_model=PendingSummary)
def pending_summary(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    """Headline figures for the cuentas-pendientes screen."""
    return sales_service.pending_summary(db, company_id=company_id)


PERIOD = Query("month", pattern="^(day|week|month|year)$")


@sales.get("/stats", response_model=SalesStats)
def sales_summary(
    period: str = PERIOD,
    salesperson_id: int | None = None,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("reports:read")),
):
    """How the day, week, month or year is going, against the same stretch of
    the one before, and how each seller, branch and product type did. Feeds
    the owner's Inicio. ``salesperson_id`` narrows it to one seller, as they
    see it themselves."""
    return sales_stats.summary(
        db, company_id=company_id, period=period, salesperson_id=salesperson_id
    )


@sales.get("/stats/mine", response_model=SalesStats)
def my_sales_summary(
    period: str = PERIOD,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:read")),
):
    """The caller's own period: what they sold and what they took in. Feeds a
    seller's Inicio, which never shows the whole shop's figures."""
    return sales_stats.summary(
        db, company_id=company_id, period=period, salesperson_id=current_user.id
    )


@sales.get("/quotes/open", response_model=list[OpenQuote])
def open_quotes(
    salesperson_id: int | None = None,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    """Presupuestos of the last ``days`` whose customer has not bought since:
    the ones still worth a call."""
    since = clock.today(db, company_id) - timedelta(days=days)
    return sales_service.open_quotes(
        db, company_id=company_id, since=since, salesperson_id=salesperson_id
    )


@sales.post("/preview", response_model=SalePreview)
def preview_sale(
    data: SaleCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    """Total a sale without writing it — the form's running total.

    The arithmetic lives on the server so the screen and the saved row can
    never disagree about what a discount means.
    """
    try:
        return sales_service.preview(db, data, company_id=company_id)
    except sales_service.SaleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@sales.post("", response_model=SaleRead, status_code=status.HTTP_201_CREATED)
def create_sale(
    data: SaleCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:write")),
):
    try:
        return sales_service.create_sale(
            db, data, company_id=company_id, user_id=current_user.id
        )
    except sales_service.SaleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@sales.get("/{sale_id}", response_model=SaleRead)
def get_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    return _get_or_404(db, sale_id, company_id)


@sales.put("/{sale_id}", response_model=SaleRead)
def update_sale(
    sale_id: int,
    data: SaleUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: User = Depends(require_permission("sales:write")),
):
    """Only status, the reminder and the notes. Money and lines are immutable —
    correct a sale by cancelling it and issuing another."""
    sale = _get_or_404(db, sale_id, company_id)
    if data.status is SaleStatus.CANCELLED and sale.status is not SaleStatus.CANCELLED:
        # Setting the flag here would skip what anular does: the stock going
        # back and the nota de crédito reversing its factura.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Para anular una venta usá Anular."
        )
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(sale, field, value)
    db.commit()
    db.refresh(sale)
    return sale


@sales.post("/{sale_id}/payments", response_model=SaleRead)
def add_payment(
    sale_id: int,
    data: PaymentCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:write")),
):
    sale = _get_or_404(db, sale_id, company_id)
    try:
        return sales_service.add_payment(
            db, sale, data, company_id=company_id, user_id=current_user.id
        )
    except sales_service.SaleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@sales.get("/{sale_id}/whatsapp", response_model=ReminderDraft)
def whatsapp_draft(
    sale_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: User = Depends(require_permission("sales:write")),
):
    """The payment reminder for this sale in each tone, and the customer's
    registered phone as WhatsApp takes it. Asks for sales:write because it
    exists only to send one."""
    sale = _get_or_404(db, sale_id, company_id)
    try:
        return payment_reminders.draft(db, sale, company_id=company_id)
    except payment_reminders.ReminderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@sales.post("/{sale_id}/whatsapp", response_model=PaymentReminderRead,
            status_code=status.HTTP_201_CREATED)
def whatsapp_sent(
    sale_id: int,
    data: ReminderSend,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:write")),
):
    """Record the reminder the console just opened in WhatsApp. The number is
    the customer's, read from their file, never one sent along."""
    sale = _get_or_404(db, sale_id, company_id)
    try:
        return payment_reminders.record(
            db, sale, data, company_id=company_id, user_id=current_user.id
        )
    except payment_reminders.ReminderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@sales.post("/{sale_id}/cancel", response_model=SaleRead)
def cancel_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:write")),
):
    """Anular: the stock goes back, the payment record stays, and a factura is
    reversed by a nota de crédito (shown on the sale, whatever ARCA answers)."""
    sale = _get_or_404(db, sale_id, company_id)
    try:
        sale = sales_service.cancel_sale(
            db, sale, company_id=company_id, user_id=current_user.id
        )
    except sales_service.SaleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if invoicing.credit_note_if_invoiced(
        db, sale, company_id=company_id, user_id=current_user.id
    ) is not None:
        db.refresh(sale)
    return sale


router.include_router(sales)
