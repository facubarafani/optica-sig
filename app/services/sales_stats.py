"""The sales summary on Inicio: how a day, week, month or year is going.

Every period runs from its calendar start (the shop's, see services.clock) up
to now, and is compared with the same stretch of the period before: this
month's first eleven days against last month's first eleven, not against a
whole month that had twenty more days to sell in.

What counts is what was sold: a presupuesto has not been agreed to and an
anulada has been undone, so neither is a sale (``sales.NON_DEBT_STATUSES``).
"Cobrado" is money received in the period, whenever its sale was made.

Inicio comes in two. The owner's (``reports:read``) is the whole shop plus how
each seller, branch and product type did. A seller's is the same summary
narrowed to them (``salesperson_id``): the sales they rang up, and as
"cobrado" the money they took in at the counter, whoever made the sale, which
is what their drawer has to add up to at closing.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import Permission, User, role_permissions, user_roles
from app.models.branch import Branch
from app.models.enums import PaymentMethod, SaleStatus
from app.models.product import Product, ProductType
from app.models.sales import Sale, SaleItem, SalePayment
from app.services import clock
from app.services.sales import NON_DEBT_STATUSES, ZERO, money, quote_followed

PERIODS = ("day", "week", "month", "year")
TOP_PRODUCTS = 5

_DAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun",
           "jul", "ago", "sep", "oct", "nov", "dic")


class StatsError(ValueError):
    pass


@dataclass
class _Window:
    start: date            # first calendar day of the period
    lo: datetime           # UTC instants, [lo, hi)
    hi: datetime


def _period_start(period: str, today: date) -> date:
    if period == "day":
        return today
    if period == "week":
        return today - timedelta(days=today.weekday())
    if period == "month":
        return today.replace(day=1)
    return today.replace(month=1, day=1)


def _previous_start(period: str, start: date) -> date:
    if period == "day":
        return start - timedelta(days=1)
    if period == "week":
        return start - timedelta(days=7)
    if period == "month":
        return (start - timedelta(days=1)).replace(day=1)
    return start.replace(year=start.year - 1)


def _windows(period: str, today: date, now: datetime, tz: tzinfo) -> tuple[_Window, _Window]:
    start = _period_start(period, today)
    lo = clock.day_start(start, tz)
    prev_start = _previous_start(period, start)
    prev_lo = clock.day_start(prev_start, tz)
    # The same stretch, never running into the current period.
    prev_hi = min(prev_lo + (now - lo), lo)
    return _Window(start, lo, now), _Window(prev_start, prev_lo, prev_hi)


def _buckets(period: str, start: date) -> list[tuple[str, str]]:
    """(key, label) for each bar of the chart, the whole period."""
    if period == "day":
        return [(str(h), f"{h} h") for h in range(24)]
    if period == "week":
        return [((start + timedelta(days=i)).isoformat(),
                 f"{_DAYS[i]} {(start + timedelta(days=i)).day}") for i in range(7)]
    if period == "month":
        days = calendar.monthrange(start.year, start.month)[1]
        return [(str(d), str(d)) for d in range(1, days + 1)]
    return [(str(m), _MONTHS[m - 1]) for m in range(1, 13)]


def _index(period: str, local: datetime) -> int:
    """Which bar a moment falls in, counted from the period's start. The
    previous period uses the same position, so the two line up bar by bar."""
    if period == "day":
        return local.hour
    if period == "week":
        return local.weekday()
    if period == "month":
        return local.day - 1
    return local.month - 1


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive timestamps; they were stored as UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _delta(now: Decimal, before: Decimal) -> Decimal | None:
    """Percentage change, or None when there is nothing to compare with."""
    if before <= 0:
        return None
    return ((now - before) * 100 / before).quantize(Decimal("0.1"))


def _share(part: Decimal, whole: Decimal) -> Decimal | None:
    """``part`` as a percentage of ``whole``; None when there is no whole."""
    if whole <= 0:
        return None
    return (part * 100 / whole).quantize(Decimal("0.1"))


def summary(
    db: Session, *, company_id: int, period: str, salesperson_id: int | None = None
) -> dict:
    """How the period is going. With ``salesperson_id``, only that seller's:
    the sales they made and the payments they took in."""
    if period not in PERIODS:
        raise StatsError(f"Período inválido: {period}.")
    tz = clock.company_zone(db, company_id)
    now = clock._now()
    today = now.astimezone(tz).date()
    cur, prev = _windows(period, today, now, tz)

    real = (Sale.company_id == company_id, Sale.status.not_in(NON_DEBT_STATUSES),
            Sale.is_active.is_(True))
    theirs = real if salesperson_id is None else (*real, Sale.salesperson_id == salesperson_id)
    took_in = () if salesperson_id is None else (SalePayment.created_by_user_id == salesperson_id,)
    sales = db.execute(
        select(Sale.sold_at, Sale.total, Sale.balance)
        .where(*theirs, Sale.sold_at >= prev.lo, Sale.sold_at < cur.hi)
    ).all()
    payments = db.execute(
        select(SalePayment.paid_at, SalePayment.amount, SalePayment.method)
        .join(Sale, Sale.id == SalePayment.sale_id)
        .where(*real, *took_in, SalePayment.paid_at >= prev.lo, SalePayment.paid_at < cur.hi)
    ).all()

    buckets = _buckets(period, cur.start)
    revenue = [ZERO] * len(buckets)
    counts = [0] * len(buckets)
    prev_revenue = [ZERO] * len(buckets)
    totals = {"revenue": ZERO, "count": 0, "owed": ZERO,
              "prev_revenue": ZERO, "prev_count": 0}
    for sold_at, total, balance in sales:
        at = _aware(sold_at)
        i = _index(period, at.astimezone(tz))
        if cur.lo <= at < cur.hi:
            revenue[i] += Decimal(total)
            counts[i] += 1
            totals["revenue"] += Decimal(total)
            totals["count"] += 1
            totals["owed"] += Decimal(balance)
        elif prev.lo <= at < prev.hi:
            totals["prev_revenue"] += Decimal(total)
            totals["prev_count"] += 1
        # The previous period's bars cover all of it, not only the stretch
        # compared in the figures: the line shows how it went on to finish.
        if at < cur.lo and i < len(buckets):
            prev_revenue[i] += Decimal(total)

    collected, prev_collected = ZERO, ZERO
    by_method: dict[PaymentMethod, Decimal] = {}
    for paid_at, amount, method in payments:
        at = _aware(paid_at)
        if cur.lo <= at < cur.hi:
            collected += Decimal(amount)
            by_method[method] = by_method.get(method, ZERO) + Decimal(amount)
        elif prev.lo <= at < prev.hi:
            prev_collected += Decimal(amount)

    top = _top_models(db, theirs, cur)

    # Bars after this moment have not happened yet: None, not zero.
    current = _index(period, now.astimezone(tz))
    count, prev_count = totals["count"], totals["prev_count"]
    avg = money(totals["revenue"] / count) if count else ZERO
    prev_avg = money(totals["prev_revenue"] / prev_count) if prev_count else ZERO
    return {
        "period": period,
        "start": cur.start,
        "previous_start": prev.start,
        "revenue": money(totals["revenue"]),
        "count": count,
        "average_ticket": avg,
        "collected": money(collected),
        "owed": money(totals["owed"]),
        "previous": {
            "revenue": money(totals["prev_revenue"]), "count": prev_count,
            "average_ticket": prev_avg, "collected": money(prev_collected),
        },
        "change": {
            "revenue": _delta(totals["revenue"], totals["prev_revenue"]),
            "count": _delta(Decimal(count), Decimal(prev_count)),
            "average_ticket": _delta(avg, prev_avg),
            "collected": _delta(collected, prev_collected),
        },
        "series": [
            {"key": key, "label": label,
             "revenue": money(revenue[i]) if i <= current else None,
             "count": counts[i] if i <= current else None,
             "previous": money(prev_revenue[i])}
            for i, (key, label) in enumerate(buckets)
        ],
        "methods": [
            {"method": m, "amount": money(by_method[m])}
            for m in sorted(by_method, key=lambda m: by_method[m], reverse=True)
        ],
        "top_products": top,
        **(_breakdowns(db, company_id, real, cur, prev) if salesperson_id is None else {}),
    }


def _blank() -> dict:
    return {"revenue": ZERO, "count": 0, "owed": ZERO, "prev_revenue": ZERO,
            "gross": ZERO, "discount": ZERO, "price_overrides": 0,
            "cancelled": 0, "quotes": 0, "quotes_won": 0}


def _figures(acc: dict, store_revenue: Decimal) -> dict:
    count = acc["count"]
    return {
        "revenue": money(acc["revenue"]),
        "count": count,
        "average_ticket": money(acc["revenue"] / count) if count else ZERO,
        "share": _share(acc["revenue"], store_revenue),
        "previous_revenue": money(acc["prev_revenue"]),
        "change": _delta(acc["revenue"], acc["prev_revenue"]),
    }


def _breakdowns(db: Session, company_id: int, real, cur: _Window, prev: _Window) -> dict:
    """The owner's view of the period: who sold it, where, and what.

    Each seller's and each branch's sales add up to the shop's: the same sales,
    the same totals, filed by who rang them up and where. A seller is also
    compared with their own same stretch before, and carries what a counter
    is answerable for besides selling: the discounts they gave (line and sale
    discounts, against the list price of what they sold), the lines they priced
    by hand, the sales they cancelled, and their presupuestos with how many
    were followed by a purchase.
    """
    base = (Sale.company_id == company_id, Sale.is_active.is_(True))
    rows = db.execute(
        select(Sale.id, Sale.salesperson_id, Sale.branch_id, Sale.sold_at, Sale.status,
               Sale.total, Sale.balance, Sale.subtotal, Sale.discount_amount)
        .where(*base, Sale.sold_at >= prev.lo, Sale.sold_at < cur.hi)
    ).all()
    lines = {sale_id: (Decimal(disc or 0), int(manual or 0)) for sale_id, disc, manual in db.execute(
        select(SaleItem.sale_id, func.sum(SaleItem.discount_amount),
               func.sum(case((SaleItem.price_overridden.is_(True), 1), else_=0)))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(*real, Sale.sold_at >= cur.lo, Sale.sold_at < cur.hi)
        .group_by(SaleItem.sale_id)
    )}
    won = set(db.execute(
        select(Sale.id).where(*base, Sale.status == SaleStatus.QUOTE,
                              Sale.sold_at >= cur.lo, Sale.sold_at < cur.hi, quote_followed())
    ).scalars())

    sellers: dict[int | None, dict] = defaultdict(_blank)
    branches: dict[int | None, dict] = defaultdict(_blank)
    store = _blank()
    for sale_id, user_id, branch_id, sold_at, status, total, balance, subtotal, disc in rows:
        at = _aware(sold_at)
        current = cur.lo <= at < cur.hi
        # The rest of the previous period, past the stretch compared, is not
        # part of any figure here.
        if not current and not prev.lo <= at < prev.hi:
            continue
        seller = sellers[user_id]
        if status is SaleStatus.QUOTE:
            if current:
                seller["quotes"] += 1
                seller["quotes_won"] += sale_id in won
            continue
        if status is SaleStatus.CANCELLED:
            if current:
                seller["cancelled"] += 1
            continue
        for acc in (seller, branches[branch_id], store):
            if current:
                acc["revenue"] += Decimal(total)
                acc["count"] += 1
                acc["owed"] += Decimal(balance)
            else:
                acc["prev_revenue"] += Decimal(total)
        if current:
            line_disc, manual = lines.get(sale_id, (ZERO, 0))
            for acc in (seller, store):
                # The list price of what was sold: the subtotal is already net
                # of the line discounts.
                acc["gross"] += Decimal(subtotal) + line_disc
                acc["discount"] += line_disc + Decimal(disc)
                acc["price_overrides"] += manual

    # Everyone who sells at the counter is listed, at zero if need be: a
    # seller with no sales yet is news too. The owner, superuser by default,
    # only when they sold.
    for user_id in db.execute(
        select(User.id)
        .join(user_roles, user_roles.c.user_id == User.id)
        .join(role_permissions, role_permissions.c.role_id == user_roles.c.role_id)
        .join(Permission, Permission.id == role_permissions.c.permission_id)
        .where(User.company_id == company_id, User.is_active.is_(True),
               User.is_superuser.is_(False), Permission.code == "sales:write")
    ).scalars():
        sellers[user_id]
    names = {uid: (name, active) for uid, name, active in db.execute(
        select(User.id, User.full_name, User.is_active)
        .where(User.company_id == company_id, User.id.in_([k for k in sellers if k is not None]))
    )}
    seller_rows = []
    for user_id, acc in sellers.items():
        name, active = names.get(user_id, ("Sin vendedor", True))
        seller_rows.append({
            "user_id": user_id, "name": name, "is_active": active,
            **_figures(acc, store["revenue"]),
            "owed": money(acc["owed"]),
            "discount_amount": money(acc["discount"]),
            "discount_rate": _share(acc["discount"], acc["gross"]),
            "price_overrides": acc["price_overrides"],
            "cancelled": acc["cancelled"],
            "quotes": acc["quotes"],
            "quotes_won": acc["quotes_won"],
        })
    # Best first; sales nobody is named on, last.
    seller_rows.sort(key=lambda r: (r["user_id"] is None, -r["revenue"], r["name"]))

    branch_names = dict(db.execute(
        select(Branch.id, Branch.name).where(Branch.company_id == company_id)).all())
    branch_rows = sorted((
        {"branch_id": branch_id, "name": branch_names.get(branch_id, "Sin sucursal"),
         **_figures(acc, store["revenue"])}
        for branch_id, acc in branches.items()
    ), key=lambda r: (r["branch_id"] is None, -r["revenue"], r["name"]))

    return {
        "discount_rate": _share(store["discount"], store["gross"]),
        "sellers": seller_rows,
        "branches": branch_rows,
        "product_types": _by_type(db, company_id, real, cur),
    }


def _by_type(db: Session, company_id: int, real, cur: _Window) -> list[dict]:
    """What each product type brought in: lines, like Más vendidos, so the
    two agree; a sale's own discount and any recargo are not split over them."""
    rows = db.execute(
        select(Product.product_type_id, func.sum(SaleItem.line_total), func.sum(SaleItem.quantity))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .where(*real, Sale.sold_at >= cur.lo, Sale.sold_at < cur.hi)
        .group_by(Product.product_type_id)
    ).all()
    if not rows:
        return []
    names = dict(db.execute(
        select(ProductType.id, ProductType.name).where(ProductType.company_id == company_id)).all())
    whole = sum((Decimal(rev or 0) for _, rev, _ in rows), ZERO)
    return sorted((
        {"product_type_id": type_id, "name": names.get(type_id, "Sin tipo"),
         "revenue": money(rev), "quantity": Decimal(qty or 0),
         "share": _share(Decimal(rev or 0), whole)}
        for type_id, rev, qty in rows
    ), key=lambda r: -r["revenue"])


def _top_models(db: Session, real, cur: _Window) -> list[dict]:
    """The best sellers by model, not by colour.

    Each colour is its own article (rule 11), so ARM-001-CAR and ARM-001-NEG
    would split one frame's sales in two and push it down the list. They are
    added up under their style, and the colours ride along as a breakdown.
    """
    lines = db.execute(
        select(SaleItem.product_id, func.sum(SaleItem.quantity), func.sum(SaleItem.line_total))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(*real, Sale.sold_at >= cur.lo, Sale.sold_at < cur.hi)
        .group_by(SaleItem.product_id)
    ).all()
    if not lines:
        return []
    sold = {pid: (Decimal(qty or 0), Decimal(rev or 0)) for pid, qty, rev in lines}
    articles = {p.id: p for p in db.execute(
        select(Product).options(selectinload(Product.parent))
        .where(Product.id.in_(sold))).unique().scalars()}
    models: dict[int, dict] = {}
    for pid, (qty, rev) in sold.items():
        article = articles[pid]
        style = article.parent or article
        m = models.setdefault(style.id, {
            "product_id": style.id, "code": style.code, "description": style.description,
            "quantity": ZERO, "revenue": ZERO, "variants": [],
        })
        m["quantity"] += qty
        m["revenue"] += rev
        if article.parent is not None:
            m["variants"].append({
                "code": article.code,
                "label": ", ".join(c.name for c in article.colors) or article.code,
                "quantity": qty, "revenue": money(rev),
            })
    best = sorted(models.values(), key=lambda m: m["revenue"], reverse=True)[:TOP_PRODUCTS]
    for m in best:
        m["revenue"] = money(m["revenue"])
        m["variants"].sort(key=lambda v: v["quantity"], reverse=True)
    return best
