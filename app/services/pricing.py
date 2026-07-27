"""Pricing & cost business logic.

Four responsibilities:
  * audited cost changes (``change_cost``)
  * resolving a product's selling price (``resolve_price`` / ``resolve_prices``)
  * building a list's category ladder (``category_code`` / ``set_category_count``)
  * filling and adjusting the prices on that ladder (``generate_prices``,
    ``bulk_update_prices``)
"""
from __future__ import annotations

import string
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import CompanySettings
from app.models.enums import PricingMode, RoundingMode
from app.models.pricing import CostHistory, PriceCategory, PriceList
from app.models.product import Product
from app.services import audit

CENTS = Decimal("0.01")
# A ladder runs AA..ZZ, so 26*26 steps at most.
MAX_CATEGORIES = 26 * 26


class PricingError(Exception):
    pass


# --- category codes -------------------------------------------------------

def category_code(position: int) -> str:
    """0 -> "AA", 1 -> "AB", … 25 -> "AZ", 26 -> "BA", … 675 -> "ZZ"."""
    if not 0 <= position < MAX_CATEGORIES:
        raise PricingError(
            f"Una lista admite hasta {MAX_CATEGORIES} categorías (AA a ZZ)."
        )
    letters = string.ascii_uppercase
    return letters[position // 26] + letters[position % 26]


# --- rounding -------------------------------------------------------------

_ROUNDING = {
    RoundingMode.UP: ROUND_CEILING,
    RoundingMode.DOWN: ROUND_FLOOR,
    RoundingMode.NEAREST: ROUND_HALF_UP,
}


def round_price(
    value: Decimal,
    *,
    step: Decimal = Decimal("100"),
    mode: RoundingMode = RoundingMode.UP,
) -> Decimal:
    """Round ``value`` to a multiple of ``step`` (8583 -> 8600 by default).

    ``step`` of 0 means "don't", and the value is only quantised to cents.
    """
    value = Decimal(value)
    step = Decimal(step)
    if step <= 0:
        return value.quantize(CENTS)
    rounded = (value / step).quantize(Decimal("1"), rounding=_ROUNDING[mode]) * step
    return rounded.quantize(CENTS)


# --- selling price resolution ---------------------------------------------

@dataclass
class ResolvedPrice:
    """A product's selling price plus where it came from.

    ``price`` is None when it cannot be resolved; ``reason`` then says why, so
    the UI can show something better than a blank cell. ``currency`` is the
    list's (or the company's, for manual prices) — a label, never a conversion.
    """

    price: Decimal | None
    source: str                    # "manual" | "price_list" | "unresolved"
    price_list_id: int | None = None
    reason: str | None = None
    currency: str | None = None


def resolve_prices(
    db: Session, products: list[Product], *, company_id: int
) -> dict[int, ResolvedPrice]:
    """Resolve the selling price of many products at once.

    Batched on purpose: the product grid needs a price per row, and doing this
    one query per product would be an N+1. Every price list involved is read in
    a single query and matched in memory.

    A product carries a category *code*, so the same code resolves against
    whichever list applies — its own, or the company default.
    """
    if not products:
        return {}

    settings = db.execute(
        select(
            CompanySettings.default_price_list_id, CompanySettings.currency
        ).where(CompanySettings.company_id == company_id)
    ).first()
    default_list_id = settings[0] if settings else None
    company_currency = (settings[1] if settings else None) or "ARS"

    # Which lists do we actually need to read?
    needed_lists: set[int] = set()
    for p in products:
        if p.pricing_mode is PricingMode.PRICE_LIST:
            list_id = p.price_list_id or default_list_id
            if list_id is not None:
                needed_lists.add(list_id)

    prices: dict[tuple[int, str], Decimal] = {}
    currencies: dict[int, str] = {}
    if needed_lists:
        rows = db.execute(
            select(
                PriceCategory.price_list_id, PriceCategory.code, PriceCategory.price
            ).where(
                PriceCategory.company_id == company_id,
                PriceCategory.price_list_id.in_(needed_lists),
                PriceCategory.is_active.is_(True),
            )
        ).all()
        prices = {(r[0], r[1].strip().upper()): Decimal(r[2]) for r in rows}
        currencies = dict(
            db.execute(
                select(PriceList.id, PriceList.currency).where(
                    PriceList.company_id == company_id, PriceList.id.in_(needed_lists)
                )
            ).all()
        )

    out: dict[int, ResolvedPrice] = {}
    for p in products:
        if p.pricing_mode is PricingMode.MANUAL:
            if p.sale_price is None:
                out[p.id] = ResolvedPrice(
                    None, "unresolved", reason="Precio manual sin cargar."
                )
            else:
                out[p.id] = ResolvedPrice(
                    Decimal(p.sale_price), "manual", currency=company_currency
                )
            continue

        list_id = p.price_list_id or default_list_id
        code = (p.price_category_code or "").strip().upper()
        currency = currencies.get(list_id) if list_id else None
        if list_id is None:
            out[p.id] = ResolvedPrice(
                None,
                "unresolved",
                reason=(
                    "El producto no tiene lista y la empresa no definió una "
                    "lista por defecto."
                ),
            )
        elif not code:
            out[p.id] = ResolvedPrice(
                None, "unresolved", list_id, "El producto no tiene categoría de precio.",
                currency,
            )
        elif (list_id, code) not in prices:
            out[p.id] = ResolvedPrice(
                None,
                "unresolved",
                list_id,
                f'La lista no tiene la categoría "{code}".',
                currency,
            )
        else:
            out[p.id] = ResolvedPrice(
                prices[(list_id, code)], "price_list", list_id, currency=currency
            )
    return out


def resolve_price(db: Session, product: Product, *, company_id: int) -> ResolvedPrice:
    """Single-product version of :func:`resolve_prices`."""
    return resolve_prices(db, [product], company_id=company_id)[product.id]


def validate_pricing(db: Session, product: Product, *, company_id: int) -> None:
    """Raise PricingError if the pricing configuration is *wrong*.

    Deliberately tolerant about what is merely *incomplete*: a product with no
    category, or manual mode with no price yet, is allowed — you can create a
    product first and price it later, and bulk imports rely on that. Those
    cases surface through ``resolve_price`` as "unresolved" with a reason.
    Only genuinely invalid configurations are rejected.
    """
    if product.pricing_mode is PricingMode.MANUAL:
        if product.sale_price is not None and Decimal(product.sale_price) < 0:
            raise PricingError("El precio de venta no puede ser negativo.")
        return

    if product.price_list_id is not None:
        price_list = db.execute(
            select(PriceList).where(
                PriceList.id == product.price_list_id,
                PriceList.company_id == company_id,
            )
        ).scalar_one_or_none()
        if price_list is None:
            raise PricingError("La lista de precios no existe.")
        # A list scoped to a product type may only price products of that type.
        if (
            price_list.product_type_id is not None
            and price_list.product_type_id != product.product_type_id
        ):
            raise PricingError(
                f'La lista "{price_list.name}" es sólo para otro tipo de producto.'
            )


# Fields whose changes must land in change_history (CLAUDE.md rule 4).
_AUDITED_PRICING_FIELDS = (
    "pricing_mode",
    "sale_price",
    "price_list_id",
    "price_category_code",
)


def apply_pricing_update(
    db: Session, product: Product, data: dict, *, user_id: int | None = None
) -> None:
    """Apply the pricing-related part of a product update, auditing each change.

    Mutates ``product`` in place and records a change-history row per changed
    field. The caller commits. ``data`` is the already-filtered update payload.
    """
    for field in _AUDITED_PRICING_FIELDS:
        if field not in data:
            continue
        old = getattr(product, field)
        new = data[field]
        if old == new:
            continue
        setattr(product, field, new)
        audit.record_change(
            db,
            company_id=product.company_id,
            entity_type="product",
            entity_id=product.id,
            field_name=field,
            old_value=old.value if hasattr(old, "value") else old,
            new_value=new.value if hasattr(new, "value") else new,
            user_id=user_id,
        )


def change_cost(
    db: Session,
    product: Product,
    new_cost: Decimal,
    *,
    user_id: int | None = None,
    note: str | None = None,
    commit: bool = True,
) -> Product:
    """Update a product's current cost, appending to cost_history and auditing.

    ``commit=False`` leaves the transaction open so a bulk import can apply many
    cost changes as a single unit of work.
    """
    old_cost = Decimal(product.current_cost)
    new_cost = Decimal(new_cost)
    if new_cost < 0:
        raise PricingError("Cost cannot be negative.")

    product.current_cost = new_cost
    db.add(product)
    db.add(
        CostHistory(
            company_id=product.company_id,
            product_id=product.id,
            old_cost=old_cost,
            new_cost=new_cost,
            changed_by_user_id=user_id,
            note=note,
        )
    )
    audit.record_change(
        db,
        company_id=product.company_id,
        entity_type="product",
        entity_id=product.id,
        field_name="current_cost",
        old_value=old_cost,
        new_value=new_cost,
        user_id=user_id,
    )
    if commit:
        db.commit()
        db.refresh(product)
    else:
        db.flush()
    return product


def list_cost_history(
    db: Session, *, company_id: int, product_id: int
) -> list[CostHistory]:
    return list(
        db.execute(
            select(CostHistory)
            .where(
                CostHistory.company_id == company_id,
                CostHistory.product_id == product_id,
            )
            .order_by(CostHistory.id.desc())
        ).scalars().all()
    )


# --- the category ladder --------------------------------------------------

def list_categories(
    db: Session, *, company_id: int, price_list_id: int, include_inactive: bool = False
) -> list[PriceCategory]:
    """The list's steps, in ladder order (cheapest first)."""
    stmt = select(PriceCategory).where(
        PriceCategory.company_id == company_id,
        PriceCategory.price_list_id == price_list_id,
    )
    if not include_inactive:
        stmt = stmt.where(PriceCategory.is_active.is_(True))
    return list(
        db.execute(stmt.order_by(PriceCategory.position, PriceCategory.id))
        .scalars()
        .all()
    )


def add_category(
    db: Session,
    *,
    company_id: int,
    price_list_id: int,
    code: str | None = None,
    description: str | None = None,
    price: Decimal = Decimal("0"),
    commit: bool = True,
) -> PriceCategory:
    """Append one step to the ladder, defaulting to the next free AA..ZZ code."""
    existing = list_categories(
        db, company_id=company_id, price_list_id=price_list_id, include_inactive=True
    )
    taken = {c.code for c in existing}
    next_position = max((c.position for c in existing), default=-1) + 1

    if code is None:
        # Codes are never reused, so walk the sequence until one is free. Starting
        # from 0 means a code freed by a rename gets picked up again.
        pos = 0
        while pos < MAX_CATEGORIES and category_code(pos) in taken:
            pos += 1
        if pos >= MAX_CATEGORIES:
            raise PricingError(
                f"La lista ya usó las {MAX_CATEGORIES} categorías posibles (AA a ZZ)."
            )
        code = category_code(pos)
    elif code in taken:
        raise PricingError(f'La lista ya tiene una categoría "{code}".')

    cat = PriceCategory(
        company_id=company_id,
        price_list_id=price_list_id,
        code=code,
        description=description,
        price=Decimal(price),
        position=next_position,
    )
    db.add(cat)
    if commit:
        db.commit()
    else:
        db.flush()
    return cat


def set_category_count(
    db: Session, *, company_id: int, price_list_id: int, count: int
) -> list[PriceCategory]:
    """Make the list have exactly ``count`` active steps, named AA, AB, AC…

    Growing appends new codes; shrinking deactivates the trailing ones rather
    than deleting them (no physical deletes on master data), so their prices
    survive and going back up restores them.
    """
    if not 1 <= count <= MAX_CATEGORIES:
        raise PricingError(f"La cantidad debe estar entre 1 y {MAX_CATEGORIES}.")

    everything = list_categories(
        db, company_id=company_id, price_list_id=price_list_id, include_inactive=True
    )
    # Re-rank so positions are dense (0..n-1) whatever the history was.
    for rank, cat in enumerate(everything):
        cat.position = rank
        cat.is_active = rank < count
        db.add(cat)

    taken = {c.code for c in everything}
    for rank in range(len(everything), count):
        code = category_code(rank)
        if code in taken:                       # a hand-renamed code got in the way
            raise PricingError(
                f'No se puede generar "{code}": la lista ya tiene una categoría '
                "con ese código. Renombrala o borrala primero."
            )
        db.add(
            PriceCategory(
                company_id=company_id,
                price_list_id=price_list_id,
                code=code,
                price=Decimal("0"),
                position=rank,
            )
        )
    db.commit()
    return list_categories(db, company_id=company_id, price_list_id=price_list_id)


# --- filling the ladder with prices ---------------------------------------

def set_price(
    db: Session,
    cat: PriceCategory,
    new_price: Decimal,
    *,
    company_id: int,
    user_id: int | None = None,
) -> bool:
    """Assign a category price, auditing it (CLAUDE.md rule 4). True if changed.

    Never commits, so a generator or a bulk import can apply many changes as one
    unit of work; the caller commits.
    """
    old_price = Decimal(cat.price)
    new_price = Decimal(new_price)
    if old_price == new_price:
        return False
    cat.price = new_price
    db.add(cat)
    audit.record_change(
        db,
        company_id=company_id,
        entity_type="price_category",
        entity_id=cat.id,
        field_name="price",
        old_value=old_price,
        new_value=new_price,
        user_id=user_id,
    )
    return True


def set_category_price(
    db: Session,
    cat: PriceCategory,
    new_price: Decimal,
    *,
    company_id: int,
    user_id: int | None = None,
) -> PriceCategory:
    """Edit one step by hand — still audited like every other price change."""
    if Decimal(new_price) < 0:
        raise PricingError("El precio no puede ser negativo.")
    set_price(db, cat, new_price, company_id=company_id, user_id=user_id)
    db.commit()
    db.refresh(cat)
    return cat


def generate_prices(
    db: Session,
    *,
    company_id: int,
    price_list_id: int,
    min_price: Decimal,
    max_price: Decimal,
    rounding_step: Decimal = Decimal("100"),
    rounding_mode: RoundingMode = RoundingMode.UP,
    user_id: int | None = None,
) -> int:
    """Spread ``min_price``..``max_price`` evenly across the list's categories.

    The cheapest category gets exactly ``min_price`` and the dearest exactly
    ``max_price``, with the rest evenly spaced between them — so the step is
    ``(max - min) / (n - 1)``. Each result is then rounded (up to the nearest
    100 by default), which is what makes $8.583 land on $8.600.

    Returns how many categories actually changed. Every change is audited.
    """
    min_price, max_price = Decimal(min_price), Decimal(max_price)
    if min_price < 0:
        raise PricingError("El precio mínimo no puede ser negativo.")
    if max_price < min_price:
        raise PricingError("El precio máximo no puede ser menor que el mínimo.")

    cats = list_categories(db, company_id=company_id, price_list_id=price_list_id)
    if not cats:
        raise PricingError(
            "La lista no tiene categorías. Generá las categorías primero."
        )

    changed = 0
    last = len(cats) - 1
    for i, cat in enumerate(cats):
        # A single category has no range to spread — it just takes the minimum.
        raw = min_price if last == 0 else (
            min_price + (max_price - min_price) * Decimal(i) / Decimal(last)
        )
        price = round_price(raw, step=rounding_step, mode=rounding_mode)
        if set_price(db, cat, price, company_id=company_id, user_id=user_id):
            changed += 1
    db.commit()
    return changed


def bulk_update_prices(
    db: Session,
    *,
    company_id: int,
    price_list_id: int,
    percentage: Decimal,
    rounding_step: Decimal = Decimal("100"),
    rounding_mode: RoundingMode = RoundingMode.UP,
    user_id: int | None = None,
) -> int:
    """Move every price in a list by a percentage. ``percentage`` of 10 = +10%.

    Returns the number of categories updated.
    """
    factor = Decimal("1") + (Decimal(percentage) / Decimal("100"))
    if factor < 0:
        raise PricingError("El ajuste no puede dejar los precios en negativo.")
    cats = list_categories(db, company_id=company_id, price_list_id=price_list_id)
    changed = 0
    for cat in cats:
        new_price = round_price(
            Decimal(cat.price) * factor, step=rounding_step, mode=rounding_mode
        )
        if set_price(db, cat, new_price, company_id=company_id, user_id=user_id):
            changed += 1
    db.commit()
    return changed
