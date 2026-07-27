"""Pricing & cost business logic.

Three responsibilities:
  * audited cost changes (``change_cost``)
  * resolving a product's selling price (``resolve_price`` / ``resolve_prices``)
  * bulk price updates on a list (``bulk_update_prices``)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import CompanySettings
from app.models.enums import PricingMode
from app.models.pricing import CostHistory, PriceList, PriceListItem
from app.models.product import Product
from app.services import audit


class PricingError(Exception):
    pass


# --- selling price resolution ---------------------------------------------

@dataclass
class ResolvedPrice:
    """A product's selling price plus where it came from.

    ``price`` is None when it cannot be resolved; ``reason`` then says why, so
    the UI can show something better than a blank cell.
    """

    price: Decimal | None
    source: str                    # "manual" | "price_list" | "unresolved"
    price_list_id: int | None = None
    reason: str | None = None


def resolve_prices(
    db: Session, products: list[Product], *, company_id: int
) -> dict[int, ResolvedPrice]:
    """Resolve the selling price of many products at once.

    Batched on purpose: the product grid needs a price per row, and doing this
    one query per product would be an N+1. Every price list involved is read in
    a single query and matched in memory.
    """
    if not products:
        return {}

    default_list_id = db.execute(
        select(CompanySettings.default_price_list_id).where(
            CompanySettings.company_id == company_id
        )
    ).scalar_one_or_none()

    # Which (list, category) pairs do we actually need?
    needed_lists: set[int] = set()
    for p in products:
        if p.pricing_mode is PricingMode.PRICE_LIST:
            list_id = p.price_list_id or default_list_id
            if list_id is not None:
                needed_lists.add(list_id)

    items: dict[tuple[int, int], Decimal] = {}
    if needed_lists:
        rows = db.execute(
            select(
                PriceListItem.price_list_id,
                PriceListItem.price_category_id,
                PriceListItem.price,
            ).where(
                PriceListItem.company_id == company_id,
                PriceListItem.price_list_id.in_(needed_lists),
            )
        ).all()
        items = {(r[0], r[1]): Decimal(r[2]) for r in rows}

    out: dict[int, ResolvedPrice] = {}
    for p in products:
        if p.pricing_mode is PricingMode.MANUAL:
            if p.sale_price is None:
                out[p.id] = ResolvedPrice(
                    None, "unresolved", reason="Precio manual sin cargar."
                )
            else:
                out[p.id] = ResolvedPrice(Decimal(p.sale_price), "manual")
            continue

        list_id = p.price_list_id or default_list_id
        if list_id is None:
            out[p.id] = ResolvedPrice(
                None,
                "unresolved",
                reason=(
                    "El producto no tiene lista y la empresa no definió una "
                    "lista por defecto."
                ),
            )
        elif p.price_category_id is None:
            out[p.id] = ResolvedPrice(
                None, "unresolved", list_id, "El producto no tiene categoría de precio."
            )
        elif (list_id, p.price_category_id) not in items:
            out[p.id] = ResolvedPrice(
                None,
                "unresolved",
                list_id,
                "La lista no tiene precio para esa categoría.",
            )
        else:
            out[p.id] = ResolvedPrice(
                items[(list_id, p.price_category_id)], "price_list", list_id
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
    "price_category_id",
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


def bulk_update_prices(
    db: Session,
    *,
    company_id: int,
    price_list_id: int,
    percentage: Decimal,
    user_id: int | None = None,
) -> int:
    """Apply a percentage change to every item in a price list.

    Returns the number of items updated. ``percentage`` of 10 means +10%.
    """
    factor = Decimal("1") + (Decimal(percentage) / Decimal("100"))
    items = list(
        db.execute(
            select(PriceListItem).where(
                PriceListItem.company_id == company_id,
                PriceListItem.price_list_id == price_list_id,
            )
        ).scalars().all()
    )
    for item in items:
        old_price = Decimal(item.price)
        new_price = (old_price * factor).quantize(Decimal("0.01"))
        item.price = new_price
        db.add(item)
        audit.record_change(
            db,
            company_id=company_id,
            entity_type="price_list_item",
            entity_id=item.id,
            field_name="price",
            old_value=old_price,
            new_value=new_price,
            user_id=user_id,
        )
    db.commit()
    return len(items)
