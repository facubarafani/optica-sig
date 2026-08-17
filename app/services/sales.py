"""Ventas — the only place a sale, its lines and its money are written.

Three rules from CLAUDE.md meet here, and none of them may be re-implemented:

* the selling price comes from ``services.pricing.resolve_prices`` (batched, so
  a ten-line sale is still one query),
* the number comes from ``services.numbering.next_number``,
* stock moves only through ``services.stock.apply_movement``.

Everything below runs with ``commit=False`` so one sale is one transaction: if
a line fails the stock check, no number is burned and no movement is left
behind.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core import search
from app.models.company import CompanySettings
from app.models.customer import Customer
from app.models.enums import DiscountType, PaymentMethod, SaleStatus, StockMovementType
from app.models.product import Product
from app.models.sales import Sale, SaleItem, SalePayment
from app.schemas.sales import (
    PaymentCreate,
    SaleCreate,
    SaleItemCreate,
    SalePreview,
    SalePreviewItem,
)
from app.schemas.stock import StockMovementCreate
from app.services import numbering, pricing
from app.services import stock as stock_service

CENTS = Decimal("0.01")
ZERO = Decimal("0")


class SaleError(Exception):
    """Raised when a sale cannot be recorded as asked."""


# A sale only owes money once it is real. A presupuesto has not been agreed to
# and an anulada has been undone, so neither is a cuenta pendiente.
NON_DEBT_STATUSES = (SaleStatus.QUOTE, SaleStatus.CANCELLED)


def money(value: Decimal | int | float | None) -> Decimal:
    """Round to cents, half-up — the way a till rounds, not the way floats do."""
    if value is None:
        return ZERO
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def discount_amount(
    base: Decimal, kind: DiscountType | None, value: Decimal | None
) -> Decimal:
    """What a discount comes to in money.

    Capped at the base: a 120% discount, or $10.000 off a $8.000 line, takes the
    line to zero rather than turning it into a refund.
    """
    if kind is None or value is None or value <= 0 or base <= 0:
        return ZERO
    raw = base * value / Decimal(100) if kind is DiscountType.PERCENT else value
    return min(money(raw), money(base))


# --- computing a sale (shared by preview and create) -----------------------

class _ComputedLine:
    __slots__ = ("product", "quantity", "unit_price", "overridden",
                 "discount_type", "discount_value", "discount_amount",
                 "line_total", "price_reason")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _load_products(
    db: Session, items: list[SaleItemCreate], *, company_id: int
) -> dict[int, Product]:
    ids = {item.product_id for item in items}
    products = {
        p.id: p
        for p in db.execute(
            select(Product).where(
                Product.company_id == company_id, Product.id.in_(ids)
            )
        ).unique().scalars()
    }
    missing = ids - set(products)
    if missing:
        raise SaleError(
            f"Producto inexistente: {', '.join(f'#{i}' for i in sorted(missing))}."
        )
    return products


def _compute(
    db: Session,
    items: list[SaleItemCreate],
    *,
    company_id: int,
    sale_discount_type: DiscountType | None,
    sale_discount_value: Decimal | None,
) -> tuple[list[_ComputedLine], Decimal, Decimal, Decimal, str | None]:
    """Price every line and add it up. Returns (lines, subtotal, discount, total, currency)."""
    if not items:
        raise SaleError("La venta necesita al menos un ítem.")
    products = _load_products(db, items, company_id=company_id)
    # One batched call for the whole sale — never resolve_price() in a loop.
    resolved = pricing.resolve_prices(
        db, list(products.values()), company_id=company_id
    )

    lines: list[_ComputedLine] = []
    subtotal = ZERO
    currency = None
    for item in items:
        product = products[item.product_id]
        price_info = resolved[product.id]
        currency = currency or price_info.currency
        reason = None
        if item.unit_price is not None:
            unit_price, overridden = money(item.unit_price), True
        elif price_info.price is not None:
            unit_price, overridden = money(price_info.price), False
        else:
            # No resolvable price and none typed in: say which product and why,
            # rather than silently selling it for nothing.
            raise SaleError(
                f"{product.code}: no se pudo resolver el precio "
                f"({price_info.reason or 'sin precio'}). Cargalo manualmente."
            )
        if unit_price < 0:
            raise SaleError(f"{product.code}: el precio no puede ser negativo.")

        gross = money(unit_price * item.quantity)
        line_discount = discount_amount(gross, item.discount_type, item.discount_value)
        line_total = money(gross - line_discount)
        subtotal += line_total
        lines.append(_ComputedLine(
            product=product, quantity=item.quantity, unit_price=unit_price,
            overridden=overridden, discount_type=item.discount_type,
            discount_value=item.discount_value, discount_amount=line_discount,
            line_total=line_total, price_reason=reason,
        ))

    subtotal = money(subtotal)
    sale_discount = discount_amount(subtotal, sale_discount_type, sale_discount_value)
    return lines, subtotal, sale_discount, money(subtotal - sale_discount), currency


def preview(db: Session, data: SaleCreate, *, company_id: int) -> SalePreview:
    """Total a sale without writing anything — what the form shows while typing."""
    lines, subtotal, sale_discount, total, currency = _compute(
        db, data.items, company_id=company_id,
        sale_discount_type=data.discount_type,
        sale_discount_value=data.discount_value,
    )
    paid = money(sum((p.amount for p in data.payments), ZERO))
    return SalePreview(
        items=[
            SalePreviewItem(
                product_id=line.product.id, quantity=line.quantity,
                unit_price=line.unit_price, price_overridden=line.overridden,
                discount_amount=line.discount_amount, line_total=line.line_total,
                price_reason=line.price_reason,
            )
            for line in lines
        ],
        subtotal=subtotal,
        discount_amount=sale_discount,
        total=total,
        paid_amount=paid,
        balance=money(total - paid),
        currency=currency,
    )


# --- writing ---------------------------------------------------------------

def _allow_negative_stock(db: Session, company_id: int) -> bool:
    cfg = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    return bool(cfg.allow_negative_stock) if cfg else False


def _default_branch(db: Session, company_id: int) -> int | None:
    cfg = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    return cfg.default_branch_id if cfg else None


def _move_stock(
    db: Session,
    sale: Sale,
    *,
    company_id: int,
    user_id: int | None,
    direction: StockMovementType,
) -> None:
    """Discharge (or give back) the sold quantities, one movement per line."""
    if sale.branch_id is None:
        raise SaleError(
            "La venta necesita una sucursal para poder descontar stock."
        )
    allow_negative = _allow_negative_stock(db, company_id)
    for item in sale.items:
        try:
            stock_service.apply_movement(
                db,
                StockMovementCreate(
                    product_id=item.product_id,
                    branch_id=sale.branch_id,
                    movement_type=direction,
                    quantity=item.quantity,
                    reference=sale.number,
                    note=("Venta " if direction is StockMovementType.OUTBOUND
                          else "Anulación de venta ") + sale.number,
                ),
                company_id=company_id,
                user_id=user_id,
                allow_negative=(
                    allow_negative or direction is StockMovementType.INBOUND
                ),
                commit=False,
            )
        except stock_service.StockError as exc:
            raise SaleError(str(exc)) from exc


def _apply_payments(
    db: Session,
    sale: Sale,
    payments: list[PaymentCreate],
    *,
    company_id: int,
    user_id: int | None,
) -> None:
    for entry in payments:
        db.add(SalePayment(
            company_id=company_id,
            sale=sale,
            amount=money(entry.amount),
            method=entry.method,
            account_id=entry.account_id,
            reference=entry.reference,
            note=entry.note,
            created_by_user_id=user_id,
        ))


def _resettle(sale: Sale) -> None:
    """Re-derive paid/balance from the payment rows. The rows are the truth."""
    sale.paid_amount = money(sum((Decimal(p.amount) for p in sale.payments), ZERO))
    sale.balance = money(Decimal(sale.total) - sale.paid_amount)


def create_sale(
    db: Session, data: SaleCreate, *, company_id: int, user_id: int | None = None
) -> Sale:
    lines, subtotal, sale_discount, total, _ = _compute(
        db, data.items, company_id=company_id,
        sale_discount_type=data.discount_type,
        sale_discount_value=data.discount_value,
    )

    paid = money(sum((p.amount for p in data.payments), ZERO))
    if paid > total:
        raise SaleError(
            f"Lo abonado ({paid}) supera el total de la venta ({total})."
        )
    if (
        data.customer_id is None
        and data.status not in NON_DEBT_STATUSES
        and money(total - paid) > 0
    ):
        # A debt has to belong to someone, or it can never be collected. A
        # presupuesto is exempt: nobody owes anything until it is confirmed.
        raise SaleError("Una venta con saldo pendiente necesita un cliente.")

    branch_id = data.branch_id or _default_branch(db, company_id)
    sale = Sale(
        company_id=company_id,
        number=numbering.next_number(
            db, company_id, numbering.KEY_SALE, commit=False
        ),
        status=data.status,
        customer_id=data.customer_id,
        branch_id=branch_id,
        salesperson_id=user_id,
        subtotal=subtotal,
        discount_type=data.discount_type,
        discount_value=data.discount_value,
        discount_amount=sale_discount,
        total=total,
        promised_payment_date=data.promised_payment_date,
        reminder_note=data.reminder_note,
        notes=data.notes,
    )
    for line in lines:
        sale.items.append(SaleItem(
            company_id=company_id,
            product_id=line.product.id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            price_overridden=line.overridden,
            discount_type=line.discount_type,
            discount_value=line.discount_value,
            discount_amount=line.discount_amount,
            line_total=line.line_total,
        ))
    db.add(sale)
    _apply_payments(db, sale, data.payments, company_id=company_id, user_id=user_id)
    db.flush()
    _resettle(sale)

    if data.status is not SaleStatus.QUOTE:
        # A presupuesto has not left the shop, so it holds no stock.
        _move_stock(db, sale, company_id=company_id, user_id=user_id,
                    direction=StockMovementType.OUTBOUND)

    db.commit()
    db.refresh(sale)
    return sale


def add_payment(
    db: Session,
    sale: Sale,
    data: PaymentCreate,
    *,
    company_id: int,
    user_id: int | None = None,
) -> Sale:
    if sale.status is SaleStatus.CANCELLED:
        raise SaleError("La venta está anulada.")
    amount = money(data.amount)
    if amount > Decimal(sale.balance):
        raise SaleError(
            f"El pago ({amount}) supera el saldo pendiente ({sale.balance})."
        )
    _apply_payments(db, sale, [data], company_id=company_id, user_id=user_id)
    db.flush()
    _resettle(sale)
    if sale.balance == ZERO:
        # Nothing left to chase; the reminder has done its job.
        sale.promised_payment_date = None
    db.commit()
    db.refresh(sale)
    return sale


def cancel_sale(
    db: Session, sale: Sale, *, company_id: int, user_id: int | None = None
) -> Sale:
    """Anular: put the goods back and mark it cancelled.

    Payments are left on the record — the money did change hands, and erasing
    that would hide a refund that still has to happen.
    """
    if sale.status is SaleStatus.CANCELLED:
        raise SaleError("La venta ya está anulada.")
    if sale.status is not SaleStatus.QUOTE:
        _move_stock(db, sale, company_id=company_id, user_id=user_id,
                    direction=StockMovementType.INBOUND)
    sale.status = SaleStatus.CANCELLED
    sale.promised_payment_date = None
    db.commit()
    db.refresh(sale)
    return sale


# --- reading ---------------------------------------------------------------

def _customer_name_match(q: str | None):
    """Match a customer by either name part, or by both ("perez juan")."""
    clauses = []
    for term in search.terms(q):
        like = f"%{term}%"
        clauses.append(or_(
            search.searchable(Customer.first_name).like(like),
            search.searchable(Customer.last_name).like(like),
            search.searchable(Customer.document_number).like(like),
        ))
    return clauses


def list_sales(
    db: Session,
    *,
    company_id: int,
    q: str | None = None,
    status: SaleStatus | None = None,
    customer_id: int | None = None,
    branch_id: int | None = None,
    pending_only: bool = False,
    overdue_only: bool = False,
    due_from: date | None = None,
    due_to: date | None = None,
    sold_from: date | None = None,
    sold_to: date | None = None,
    limit: int = 200,
) -> list[Sale]:
    """Sales, newest first.

    ``q`` matches the sale number, the customer's name or document, and the
    note left on the reminder — the three things anyone actually remembers.
    """
    stmt = (
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.payments))
        .where(Sale.company_id == company_id)
    )
    if status is not None:
        stmt = stmt.where(Sale.status == status)
    if customer_id is not None:
        stmt = stmt.where(Sale.customer_id == customer_id)
    if branch_id is not None:
        stmt = stmt.where(Sale.branch_id == branch_id)
    if pending_only:
        # Quotes and cancelled sales owe nothing, whatever their balance says.
        stmt = stmt.where(
            Sale.balance > 0, Sale.status.not_in(NON_DEBT_STATUSES)
        )
    if overdue_only:
        stmt = stmt.where(
            Sale.balance > 0,
            Sale.status.not_in(NON_DEBT_STATUSES),
            Sale.promised_payment_date.is_not(None),
            Sale.promised_payment_date < date.today(),
        )
    if due_from is not None:
        stmt = stmt.where(Sale.promised_payment_date >= due_from)
    if due_to is not None:
        stmt = stmt.where(Sale.promised_payment_date <= due_to)
    if sold_from is not None:
        stmt = stmt.where(Sale.sold_at >= sold_from)
    if sold_to is not None:
        stmt = stmt.where(func.date(Sale.sold_at) <= sold_to)

    if terms := _customer_name_match(q):
        stmt = stmt.outerjoin(Customer, Customer.id == Sale.customer_id)
        # The number and the reminder note are searched too, so one box covers
        # "V-000012", "Pérez" and "señó el armazón".
        like_all = [f"%{t}%" for t in search.terms(q)]
        stmt = stmt.where(or_(
            *terms,
            *[search.searchable(Sale.number).like(lk) for lk in like_all],
            *[search.searchable(Sale.reminder_note).like(lk) for lk in like_all],
        ))

    stmt = stmt.order_by(Sale.sold_at.desc(), Sale.id.desc()).limit(limit)
    return list(db.execute(stmt).unique().scalars().all())


def get_sale(db: Session, sale_id: int, *, company_id: int) -> Sale | None:
    return db.execute(
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.payments))
        .where(Sale.company_id == company_id, Sale.id == sale_id)
    ).unique().scalar_one_or_none()


def pending_summary(db: Session, *, company_id: int) -> dict:
    """Headline numbers for the "cuentas pendientes" screen."""
    today = date.today()
    rows = db.execute(
        select(Sale.balance, Sale.promised_payment_date).where(
            Sale.company_id == company_id,
            Sale.balance > 0,
            Sale.status.not_in(NON_DEBT_STATUSES),
        )
    ).all()
    total = money(sum((Decimal(r[0]) for r in rows), ZERO))
    overdue = money(sum(
        (Decimal(r[0]) for r in rows if r[1] is not None and r[1] < today), ZERO
    ))
    due_today = money(sum(
        (Decimal(r[0]) for r in rows if r[1] == today), ZERO
    ))
    return {
        "count": len(rows),
        "total_pending": total,
        "overdue_amount": overdue,
        "overdue_count": sum(1 for r in rows if r[1] is not None and r[1] < today),
        "due_today_amount": due_today,
        "due_today_count": sum(1 for r in rows if r[1] == today),
        "undated_count": sum(1 for r in rows if r[1] is None),
    }


__all__ = [
    "SaleError", "money", "discount_amount", "preview", "create_sale",
    "add_payment", "cancel_sale", "list_sales", "get_sale", "pending_summary",
    "PaymentMethod",
]
