"""Facturación electrónica: the Facturar button and what it produced.

Thin on purpose: every rule lives in ``services.invoicing``, and every call to
arca-api in ``services.arca``. Invoicing rides on the sales permissions,
since whoever may sell may invoice what they sold.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.enums import InvoiceStatus
from app.schemas.invoicing import (
    InvoiceRead,
    InvoicingCheck,
    InvoicingRequestWrite,
    InvoicingSetupRead,
    InvoicingStatus,
)
from app.services import invoicing
from app.services import sales as sales_service

router = APIRouter(tags=["invoicing"])


def _sale_or_404(db: Session, sale_id: int, company_id: int):
    sale = sales_service.get_sale(db, sale_id, company_id=company_id)
    if sale is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Venta inexistente.")
    return sale


def _invoice_or_404(db: Session, invoice_id: int, company_id: int):
    invoice = invoicing.get_invoice(db, invoice_id, company_id=company_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comprobante inexistente.")
    return invoice


@router.get("/invoicing/status", response_model=InvoicingStatus)
def invoicing_status(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    """Whether this shop invoices, and which classes: the console's cue."""
    return invoicing.status(db, company_id)


# --- the guide in Empresa ------------------------------------------------------
@router.get("/invoicing/setup", response_model=InvoicingSetupRead)
def invoicing_setup(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("company:read")),
):
    """Where the shop stands in the setup guide, our CUIT to delegate to, and
    what it declared so far."""
    return invoicing.setup(db, company_id)


@router.put("/invoicing/setup", response_model=InvoicingSetupRead)
def save_invoicing_setup(
    data: InvoicingRequestWrite,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("company:write")),
):
    """Keep the guide's data; with ``submit``, tell us the ARCA steps are done.

    Never turns invoicing on by itself: we accept the delegation at ARCA and
    activate it from /admin.
    """
    try:
        return invoicing.save_request(db, data, company_id=company_id, user_id=current_user.id)
    except invoicing.InvoicingError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/invoicing/setup/check", response_model=InvoicingCheck)
def check_invoicing(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("company:read")),
):
    """Verificar: whether ARCA would let us invoice for this CUIT right now."""
    try:
        return invoicing.check(db, company_id)
    except invoicing.InvoicingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/sales/{sale_id}/invoice", response_model=InvoiceRead)
def invoice_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:write")),
):
    """Facturar. Repeating it returns the factura already asked for.

    A pending answer is not an error: the comprobante comes back ``pending``
    with the reason, and ``GET /invoices/{id}`` follows it up.
    """
    sale = _sale_or_404(db, sale_id, company_id)
    try:
        return invoicing.request_invoice(
            db, sale, company_id=company_id, user_id=current_user.id
        )
    except invoicing.InvoicingError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/sales/{sale_id}/credit-note", response_model=InvoiceRead)
def credit_note(
    sale_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("sales:write")),
):
    """Reverse a cancelled sale's factura. Anular already asks for it; this is
    the retry when that one was rejected."""
    sale = _sale_or_404(db, sale_id, company_id)
    try:
        return invoicing.request_credit_note(
            db, sale, company_id=company_id, user_id=current_user.id
        )
    except invoicing.InvoicingError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/invoices", response_model=list[InvoiceRead])
def list_invoices(
    # Aliased because `status` is fastapi's status-code module in this file.
    invoice_status: InvoiceStatus | None = Query(None, alias="status"),
    sale_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    return invoicing.list_invoices(
        db, company_id=company_id, status=invoice_status, sale_id=sale_id,
        limit=min(limit, 500),
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    """A pending one is asked about on the way out (at most every few seconds),
    so a screen can poll this until it settles."""
    return invoicing.refresh(db, _invoice_or_404(db, invoice_id, company_id))


@router.post("/invoices/{invoice_id}/retry", response_model=InvoiceRead)
def retry_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: User = Depends(require_permission("sales:write")),
):
    """Resend a pending comprobante under its own key: never a second one."""
    invoice = _invoice_or_404(db, invoice_id, company_id)
    try:
        return invoicing.retry(db, invoice)
    except invoicing.InvoicingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("sales:read")),
):
    """The printable comprobante, rendered by arca-api."""
    invoice = _invoice_or_404(db, invoice_id, company_id)
    try:
        content, name = invoicing.pdf(db, invoice)
    except invoicing.InvoicingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return Response(
        content, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )
