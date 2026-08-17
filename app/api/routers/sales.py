"""Ventas, their payments, and the accounts money lands in."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.enums import SaleStatus
from app.models.sales import PaymentAccount
from app.schemas.sales import (
    PaymentAccountCreate,
    PaymentAccountRead,
    PaymentAccountUpdate,
    PaymentCreate,
    PendingSummary,
    SaleCreate,
    SaleListRead,
    SalePreview,
    SaleRead,
    SaleUpdate,
)
from app.services import sales as sales_service

router = APIRouter()

# --- cuentas (Santander, MercadoPago, caja...) ------------------------------
router.include_router(
    build_crud_router(
        prefix="/payment-accounts",
        tags=["sales"],
        crud=CRUDBase(PaymentAccount),
        create_schema=PaymentAccountCreate,
        update_schema=PaymentAccountUpdate,
        read_schema=PaymentAccountRead,
        permission="sales",
    )
)

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
    pending_only: bool = False,
    overdue_only: bool = False,
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
    reminder note, ignoring case and accents."""
    return sales_service.list_sales(
        db, company_id=company_id, q=q, status=sale_status, customer_id=customer_id,
        branch_id=branch_id, pending_only=pending_only, overdue_only=overdue_only,
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


@sales.post("/{sale_id}/cancel", response_model=SaleRead)
def cancel_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:write")),
):
    """Anular: the stock goes back, the payment record stays."""
    sale = _get_or_404(db, sale_id, company_id)
    try:
        return sales_service.cancel_sale(
            db, sale, company_id=company_id, user_id=current_user.id
        )
    except sales_service.SaleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


router.include_router(sales)
