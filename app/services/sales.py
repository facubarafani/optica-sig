"""Ventas — the only place a sale, its lines and its money are written.

Three rules from CLAUDE.md meet here, and none of them may be re-implemented:

* the selling price comes from ``services.pricing.resolve_prices`` (batched, so
  a ten-line sale is still one query),
* the number comes from ``services.numbering.next_number``,
* stock moves only through ``services.stock.apply_movement``.

Everything below runs with ``commit=False`` so one sale is one transaction: if
a line fails, no number is burned and no movement is left behind.

A credit card in cuotas may carry a recargo. It is part of the price, so it
raises ``sale.total`` (and the factura with it): the payments cover the goods,
``total - surcharge_amount``, and each stored payment is what the card was
actually charged, recargo included.

Missing stock is not a failure. A shop sells what is on the counter whether or
not the system knew it was there (a product created at 0, a delivery nobody
loaded), so a sale always discharges, stock may go negative, and
``stock_warnings`` says so on the form and on the receipt instead of refusing.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.core import search
from app.models.branch import Branch
from app.models.company import CompanySettings
from app.models.customer import Customer
from app.models.enums import DebtLight, DiscountType, PaymentMethod, SaleStatus, StockMovementType
from app.models.product import Product
from app.models.sales import InstallmentRate, PaymentAccount, Sale, SaleItem, SalePayment
from app.schemas.sales import (
    InstallmentRateIn,
    PaymentCreate,
    SaleCreate,
    SaleItemCreate,
    SalePreview,
    SalePreviewItem,
)
from app.schemas.stock import StockMovementCreate
from app.services import clock, invoicing, numbering, pricing
from app.services import products as products_service
from app.services import stock as stock_service

CENTS = Decimal("0.01")
ZERO = Decimal("0")


class SaleError(Exception):
    """Raised when a sale cannot be recorded as asked."""


# A sale only owes money once it is real. A presupuesto has not been agreed to
# and an anulada has been undone, so neither is a cuenta pendiente.
NON_DEBT_STATUSES = (SaleStatus.QUOTE, SaleStatus.CANCELLED)


# --- the semáforo of a debt -------------------------------------------------

# Yellow reaches this far ahead: what falls due this week needs attention now.
DUE_SOON_DAYS = 7
_LIGHT_RANK = {DebtLight.RED: 0, DebtLight.YELLOW: 1, DebtLight.GREEN: 2}


def debt_light(promised: date | None, today: date) -> DebtLight:
    """Red once the promised date has passed; yellow when it falls due this
    week (today included) or nobody agreed one; green when it is further off."""
    if promised is None:
        return DebtLight.YELLOW
    if promised < today:
        return DebtLight.RED
    if promised <= today + timedelta(days=DUE_SOON_DAYS):
        return DebtLight.YELLOW
    return DebtLight.GREEN


def _owes():
    """A sale that is a debt: real, and with money still to come."""
    return (Sale.balance > 0, Sale.status.not_in(NON_DEBT_STATUSES), Sale.is_active.is_(True))


def _light_where(light: DebtLight, today: date):
    """``debt_light`` as SQL, so a list can be narrowed to one colour."""
    promised = Sale.promised_payment_date
    if light is DebtLight.RED:
        return promised < today
    soon = today + timedelta(days=DUE_SOON_DAYS)
    if light is DebtLight.YELLOW:
        return or_(promised.is_(None), and_(promised >= today, promised <= soon))
    return promised > soon


def customer_debts(
    db: Session, *, company_id: int, customer_ids: list[int] | None = None
) -> dict[int, dict]:
    """What each customer owes, and their light: the worst of their debts.

    The debt that decides it also gives the date shown beside the light: the
    most overdue when red, the soonest due otherwise (a dated one before one
    with no date, which says less).
    """
    today = clock.today(db, company_id)
    stmt = select(Sale.customer_id, Sale.balance, Sale.promised_payment_date).where(
        Sale.company_id == company_id, Sale.customer_id.is_not(None), *_owes())
    if customer_ids is not None:
        stmt = stmt.where(Sale.customer_id.in_(customer_ids))
    debts: dict[int, dict] = {}
    for customer_id, balance, promised in db.execute(stmt):
        light = debt_light(promised, today)
        key = (_LIGHT_RANK[light], promised or date.max)
        d = debts.setdefault(customer_id, {"owed": ZERO, "count": 0, "key": key,
                                           "light": light, "due": promised})
        d["owed"] += Decimal(balance)
        d["count"] += 1
        if key < d["key"]:
            d.update(key=key, light=light, due=promised)
    return {
        cid: {"light": d["light"], "due": d["due"], "owed": money(d["owed"]), "count": d["count"]}
        for cid, d in debts.items()
    }


def owing_customer_ids(company_id: int):
    """The customers with a debt, as a subquery a customer list can filter on."""
    return select(Sale.customer_id).where(
        Sale.company_id == company_id, Sale.customer_id.is_not(None), *_owes())


def quote_followed():
    """True for a presupuesto its customer went on to buy after.

    A presupuesto is never turned into the sale itself (the sale is rung up
    afresh), so what links them is the customer: a real sale of theirs at or
    after the presupuesto counts, whatever it sold. Without a customer there is
    nobody to have bought, so it is never followed.
    """
    later = aliased(Sale)
    return exists().where(
        later.company_id == Sale.company_id,
        later.customer_id == Sale.customer_id,
        later.status.not_in(NON_DEBT_STATUSES),
        later.is_active.is_(True),
        later.sold_at >= Sale.sold_at,
    )


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


def payment_surcharge(entry: PaymentCreate) -> Decimal:
    """The recargo a payment adds on top of the part of the price it covers.

    Read like a discount (a percentage of the amount, or a fixed sum) but not
    capped: financing can cost more than the goods.
    """
    if (
        entry.method is not PaymentMethod.CREDIT_CARD
        or entry.surcharge_type is None
        or not entry.surcharge_value
    ):
        return ZERO
    if entry.surcharge_type is DiscountType.PERCENT:
        return money(money(entry.amount) * entry.surcharge_value / Decimal(100))
    return money(entry.surcharge_value)


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
    # Every line of every sale is loaded here, so this is where a style gets
    # turned away — a customer buys a colour, not a family.
    for product in products.values():
        try:
            products_service.assert_sellable(db, product)
        except products_service.ProductError as exc:
            raise SaleError(str(exc)) from exc
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
    covered = money(sum((p.amount for p in data.payments), ZERO))
    surcharge = money(sum((payment_surcharge(p) for p in data.payments), ZERO))
    warnings = [] if data.status is SaleStatus.QUOTE else stock_warnings(
        db, data.items, company_id=company_id,
        branch_id=data.branch_id or _default_branch(db, company_id),
    )
    return SalePreview(
        stock_warnings=warnings,
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
        surcharge_amount=surcharge,
        total=money(total + surcharge),
        paid_amount=money(covered + surcharge),
        balance=money(total - covered),
        currency=currency,
    )


# --- writing ---------------------------------------------------------------

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
                # Never refused for lack of stock: see the module docstring.
                # stock_warnings is what tells the operator.
                allow_negative=True,
                commit=False,
            )
        except stock_service.StockError as exc:
            raise SaleError(str(exc)) from exc


def _qty(value: Decimal) -> str:
    """3, not 3.00: a count of frames reads as a whole number."""
    return f"{value.normalize():f}"


def stock_warnings(
    db: Session,
    items: list[SaleItemCreate],
    *,
    company_id: int,
    branch_id: int | None,
) -> list[str]:
    """One sentence per product the sale would leave below zero at its branch.

    Read before the discharge, so it states what the shelf held and where it
    ends up. Lines of the same product are added together, since that is what
    leaves the shelf.
    """
    if branch_id is None or not items:
        return []
    wanted: dict[int, Decimal] = {}
    for item in items:
        wanted[item.product_id] = wanted.get(item.product_id, ZERO) + Decimal(item.quantity)
    products = {
        p.id: p for p in db.execute(
            select(Product).where(
                Product.id.in_(wanted), Product.company_id == company_id
            )
        ).scalars()
    }
    branch = db.execute(
        select(Branch.name).where(Branch.id == branch_id, Branch.company_id == company_id)
    ).scalar_one_or_none() or "la sucursal"
    out = []
    for product_id, qty in wanted.items():
        product = products.get(product_id)
        if product is None:
            continue
        level = stock_service.get_level(
            db, company_id=company_id, product_id=product_id, branch_id=branch_id
        )
        have = Decimal(level.quantity) if level else ZERO
        if have - qty >= 0:
            continue
        held = f"no hay stock cargado en {branch}" if have <= 0 else f"hay {_qty(have)} en {branch}"
        out.append(
            f"{product.code}: {held}. Se vende igual y el stock queda en {_qty(have - qty)}."
        )
    return out


def _apply_payments(
    db: Session,
    sale: Sale,
    payments: list[PaymentCreate],
    *,
    company_id: int,
    user_id: int | None,
) -> Decimal:
    """Write the payments; returns the recargo they add to the sale."""
    added = ZERO
    for entry in payments:
        surcharge = payment_surcharge(entry)
        added += surcharge
        db.add(SalePayment(
            company_id=company_id,
            sale=sale,
            amount=money(entry.amount) + surcharge,
            surcharge_amount=surcharge,
            method=entry.method,
            account_id=entry.account_id,
            reference=entry.reference,
            installments=entry.installments,
            note=entry.note,
            created_by_user_id=user_id,
        ))
    return money(added)


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

    # What the payments cover of the price; a recargo comes on top of it.
    paid = money(sum((p.amount for p in data.payments), ZERO))
    if paid > total:
        raise SaleError(
            f"Lo abonado ({paid}) supera el total de la venta ({total})."
        )
    if data.status is SaleStatus.QUOTE and any(payment_surcharge(p) for p in data.payments):
        raise SaleError("Un presupuesto no lleva recargo por cuotas.")
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
    surcharge = _apply_payments(db, sale, data.payments, company_id=company_id, user_id=user_id)
    sale.surcharge_amount = surcharge
    sale.total = money(total + surcharge)
    db.flush()
    _resettle(sale)

    warnings: list[str] = []
    if data.status is not SaleStatus.QUOTE:
        # A presupuesto has not left the shop, so it holds no stock.
        warnings = stock_warnings(
            db, data.items, company_id=company_id, branch_id=branch_id
        )
        _move_stock(db, sale, company_id=company_id, user_id=user_id,
                    direction=StockMovementType.OUTBOUND)

    db.commit()
    db.refresh(sale)
    # Not a column: it describes this write, so only this response carries it.
    sale.stock_warnings = warnings
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
    if payment_surcharge(data) and invoicing.has_factura(sale):
        # The factura already states the total; a recargo now would need a
        # nota de débito, which is not issued from here.
        raise SaleError(
            "La venta ya está facturada: no se le puede sumar un recargo por cuotas."
        )
    surcharge = _apply_payments(db, sale, [data], company_id=company_id, user_id=user_id)
    if surcharge:
        sale.surcharge_amount = money(Decimal(sale.surcharge_amount) + surcharge)
        sale.total = money(Decimal(sale.total) + surcharge)
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
    that would hide a refund that still has to happen. A factura is reversed
    by a nota de crédito afterwards (``invoicing.credit_note_if_invoiced``),
    outside this transaction; one still with ARCA blocks the cancellation.
    """
    if sale.status is SaleStatus.CANCELLED:
        raise SaleError("La venta ya está anulada.")
    try:
        invoicing.assert_cancellable(db, sale)
    except invoicing.InvoicingError as exc:
        raise SaleError(str(exc)) from exc
    # Read again under the row lock assert_cancellable took: a second Anular
    # waits here for the first, then finds the sale already cancelled instead
    # of putting the stock back twice.
    db.refresh(sale)
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


# --- recargos por cuotas ----------------------------------------------------

def set_installment_rates(
    db: Session, account: PaymentAccount, rates: list[InstallmentRateIn], *, company_id: int
) -> PaymentAccount:
    """Replace an account's whole table of recargos: the form edits it as one."""
    counts = [r.installments for r in rates]
    if len(counts) != len(set(counts)):
        raise SaleError("Cada cantidad de cuotas puede aparecer una sola vez.")
    account.installment_rates.clear()
    db.flush()
    for rate in sorted(rates, key=lambda r: r.installments):
        account.installment_rates.append(InstallmentRate(
            company_id=company_id, installments=rate.installments,
            surcharge_percent=rate.surcharge_percent,
        ))
    db.commit()
    db.refresh(account)
    return account


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
    salesperson_id: int | None = None,
    pending_only: bool = False,
    overdue_only: bool = False,
    light: DebtLight | None = None,
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
        .options(selectinload(Sale.items), selectinload(Sale.payments),
                 selectinload(Sale.customer), selectinload(Sale.salesperson))
        .where(Sale.company_id == company_id)
    )
    if status is not None:
        stmt = stmt.where(Sale.status == status)
    if customer_id is not None:
        stmt = stmt.where(Sale.customer_id == customer_id)
    if branch_id is not None:
        stmt = stmt.where(Sale.branch_id == branch_id)
    if salesperson_id is not None:
        stmt = stmt.where(Sale.salesperson_id == salesperson_id)
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
            Sale.promised_payment_date < clock.today(db, company_id),
        )
    if light is not None:
        stmt = stmt.where(*_owes(), _light_where(light, clock.today(db, company_id)))
    if due_from is not None:
        stmt = stmt.where(Sale.promised_payment_date >= due_from)
    if due_to is not None:
        stmt = stmt.where(Sale.promised_payment_date <= due_to)
    # Calendar days are the shop's: "hasta el 16" includes a sale rung up at
    # 22:00 on the 16th, which UTC already files under the 17th.
    if sold_from is not None or sold_to is not None:
        tz = clock.company_zone(db, company_id)
        if sold_from is not None:
            stmt = stmt.where(Sale.sold_at >= clock.day_start(sold_from, tz))
        if sold_to is not None:
            stmt = stmt.where(Sale.sold_at < clock.day_start(sold_to + timedelta(days=1), tz))

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
    sales = list(db.execute(stmt).unique().scalars().all())
    # Each debt carries its light. Not a column: it moves with the calendar.
    today = clock.today(db, company_id)
    for sale in sales:
        owes = Decimal(sale.balance) > 0 and sale.status not in NON_DEBT_STATUSES
        sale.debt_light = debt_light(sale.promised_payment_date, today) if owes else None
    return sales


def open_quotes(
    db: Session, *, company_id: int, since: date, salesperson_id: int | None = None
) -> list[dict]:
    """Presupuestos still worth a call: made since ``since`` to a customer who
    has bought nothing since (``quote_followed``). Newest first, each with who
    to call and what it was for."""
    tz = clock.company_zone(db, company_id)
    stmt = (
        select(Sale, Customer)
        .join(Customer, Customer.id == Sale.customer_id)
        .options(selectinload(Sale.items))
        .where(
            Sale.company_id == company_id,
            Sale.is_active.is_(True),
            Sale.status == SaleStatus.QUOTE,
            Sale.sold_at >= clock.day_start(since, tz),
            ~quote_followed(),
        )
    )
    if salesperson_id is not None:
        stmt = stmt.where(Sale.salesperson_id == salesperson_id)
    stmt = stmt.order_by(Sale.sold_at.desc(), Sale.id.desc())
    return [
        {
            "id": sale.id, "number": sale.number, "sold_at": sale.sold_at,
            "salesperson_id": sale.salesperson_id, "total": sale.total,
            "customer_id": customer.id,
            "customer_name": f"{customer.last_name}, {customer.first_name}",
            "customer_phone": customer.phone,
            "items": [item.product_description or item.product_code or "" for item in sale.items],
        }
        for sale, customer in db.execute(stmt).unique().all()
    ]


def get_sale(db: Session, sale_id: int, *, company_id: int) -> Sale | None:
    return db.execute(
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.payments))
        .where(Sale.company_id == company_id, Sale.id == sale_id)
    ).unique().scalar_one_or_none()


def pending_summary(db: Session, *, company_id: int) -> dict:
    """Headline numbers for the "cuentas pendientes" screen."""
    today = clock.today(db, company_id)
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
    lights = {light: {"amount": ZERO, "count": 0} for light in DebtLight}
    for balance, promised in rows:
        bucket = lights[debt_light(promised, today)]
        bucket["amount"] += Decimal(balance)
        bucket["count"] += 1
    return {
        "lights": {light: {"amount": money(b["amount"]), "count": b["count"]}
                   for light, b in lights.items()},
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
    "add_payment", "cancel_sale", "payment_surcharge", "set_installment_rates", "list_sales", "get_sale", "pending_summary",
    "open_quotes", "quote_followed", "debt_light", "customer_debts", "owing_customer_ids",
    "PaymentMethod",
]
