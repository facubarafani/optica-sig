"""Pricing & cost business logic: audited cost changes and bulk price updates."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pricing import CostHistory, PriceListItem
from app.models.product import Product
from app.services import audit


class PricingError(Exception):
    pass


def change_cost(
    db: Session,
    product: Product,
    new_cost: Decimal,
    *,
    user_id: int | None = None,
    note: str | None = None,
) -> Product:
    """Update a product's current cost, appending to cost_history and auditing."""
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
    db.commit()
    db.refresh(product)
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
