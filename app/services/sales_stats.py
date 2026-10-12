"""The sales summary on Inicio: how a day, week, month or year is going.

Every period runs from its calendar start (the shop's, see services.clock) up
to now, and is compared with the same stretch of the period before: this
month's first eleven days against last month's first eleven, not against a
whole month that had twenty more days to sell in.

What counts is what was sold: a presupuesto has not been agreed to and an
anulada has been undone, so neither is a sale (``sales.NON_DEBT_STATUSES``).
"Cobrado" is money received in the period, whenever its sale was made.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import PaymentMethod
from app.models.product import Product
from app.models.sales import Sale, SaleItem, SalePayment
from app.services import clock
from app.services.sales import NON_DEBT_STATUSES, ZERO, money

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


def summary(db: Session, *, company_id: int, period: str) -> dict:
    if period not in PERIODS:
        raise StatsError(f"Período inválido: {period}.")
    tz = clock.company_zone(db, company_id)
    now = clock._now()
    today = now.astimezone(tz).date()
    cur, prev = _windows(period, today, now, tz)

    real = (Sale.company_id == company_id, Sale.status.not_in(NON_DEBT_STATUSES),
            Sale.is_active.is_(True))
    sales = db.execute(
        select(Sale.sold_at, Sale.total, Sale.balance)
        .where(*real, Sale.sold_at >= prev.lo, Sale.sold_at < cur.hi)
    ).all()
    payments = db.execute(
        select(SalePayment.paid_at, SalePayment.amount, SalePayment.method)
        .join(Sale, Sale.id == SalePayment.sale_id)
        .where(*real, SalePayment.paid_at >= prev.lo, SalePayment.paid_at < cur.hi)
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

    top = _top_models(db, real, cur)

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
    }


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
