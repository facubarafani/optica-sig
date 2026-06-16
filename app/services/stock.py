"""Stock service — the single entry point for all stock changes.

Every change writes a ``stock_movement`` row AND updates the matching
``stock_level`` in the same unit of work. Nothing else may mutate stock levels.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import StockMovementType
from app.models.stock import StockLevel, StockMovement
from app.schemas.stock import StockMovementCreate, StockTransferCreate
from app.services import audit


class StockError(Exception):
    """Raised on invalid stock operations (e.g. negative stock not allowed)."""


def get_level(
    db: Session, *, company_id: int, product_id: int, branch_id: int
) -> StockLevel | None:
    return db.execute(
        select(StockLevel).where(
            StockLevel.company_id == company_id,
            StockLevel.product_id == product_id,
            StockLevel.branch_id == branch_id,
        )
    ).scalar_one_or_none()


def list_levels(
    db: Session,
    *,
    company_id: int,
    product_id: int | None = None,
    branch_id: int | None = None,
) -> list[StockLevel]:
    stmt = select(StockLevel).where(StockLevel.company_id == company_id)
    if product_id is not None:
        stmt = stmt.where(StockLevel.product_id == product_id)
    if branch_id is not None:
        stmt = stmt.where(StockLevel.branch_id == branch_id)
    return list(db.execute(stmt.order_by(StockLevel.id)).scalars().all())


def _get_or_create_level(
    db: Session, *, company_id: int, product_id: int, branch_id: int
) -> StockLevel:
    level = get_level(
        db, company_id=company_id, product_id=product_id, branch_id=branch_id
    )
    if level is None:
        level = StockLevel(
            company_id=company_id,
            product_id=product_id,
            branch_id=branch_id,
            quantity=Decimal("0"),
        )
        db.add(level)
        db.flush()
    return level


def _post(
    db: Session,
    *,
    company_id: int,
    product_id: int,
    branch_id: int,
    movement_type: StockMovementType,
    delta: Decimal,
    user_id: int | None,
    reference: str | None,
    note: str | None,
    counterpart_branch_id: int | None,
    allow_negative: bool,
) -> StockMovement:
    level = _get_or_create_level(
        db, company_id=company_id, product_id=product_id, branch_id=branch_id
    )
    old_qty = Decimal(level.quantity)
    new_qty = old_qty + delta
    if new_qty < 0 and not allow_negative:
        raise StockError(
            f"Insufficient stock for product {product_id} at branch {branch_id}: "
            f"have {old_qty}, requested change {delta}."
        )
    level.quantity = new_qty
    db.add(level)

    movement = StockMovement(
        company_id=company_id,
        product_id=product_id,
        branch_id=branch_id,
        movement_type=movement_type,
        quantity=delta,
        resulting_quantity=new_qty,
        counterpart_branch_id=counterpart_branch_id,
        reference=reference,
        note=note,
        created_by_user_id=user_id,
    )
    db.add(movement)

    audit.record_change(
        db,
        company_id=company_id,
        entity_type="stock_level",
        entity_id=product_id,
        field_name=f"quantity@branch:{branch_id}",
        old_value=old_qty,
        new_value=new_qty,
        user_id=user_id,
    )
    return movement


def apply_movement(
    db: Session,
    data: StockMovementCreate,
    *,
    company_id: int,
    user_id: int | None = None,
    allow_negative: bool = False,
) -> StockMovement:
    """Apply an inbound/outbound/adjustment movement to a single branch."""
    qty = Decimal(data.quantity)
    mt = data.movement_type
    if mt is StockMovementType.TRANSFER:
        raise StockError("Use apply_transfer for transfers between branches.")
    elif mt is StockMovementType.INBOUND:
        delta = abs(qty)
    elif mt is StockMovementType.OUTBOUND:
        delta = -abs(qty)
    else:  # ADJUSTMENT — quantity is a signed delta
        delta = qty

    movement = _post(
        db,
        company_id=company_id,
        product_id=data.product_id,
        branch_id=data.branch_id,
        movement_type=mt,
        delta=delta,
        user_id=user_id,
        reference=data.reference,
        note=data.note,
        counterpart_branch_id=None,
        allow_negative=allow_negative,
    )
    db.commit()
    db.refresh(movement)
    return movement


def apply_transfer(
    db: Session,
    data: StockTransferCreate,
    *,
    company_id: int,
    user_id: int | None = None,
    allow_negative: bool = False,
) -> tuple[StockMovement, StockMovement]:
    """Move stock between two branches (writes two TRANSFER movements)."""
    if data.from_branch_id == data.to_branch_id:
        raise StockError("Transfer source and destination must differ.")
    qty = abs(Decimal(data.quantity))
    if qty == 0:
        raise StockError("Transfer quantity must be greater than zero.")

    out_mv = _post(
        db,
        company_id=company_id,
        product_id=data.product_id,
        branch_id=data.from_branch_id,
        movement_type=StockMovementType.TRANSFER,
        delta=-qty,
        user_id=user_id,
        reference=data.reference,
        note=data.note,
        counterpart_branch_id=data.to_branch_id,
        allow_negative=allow_negative,
    )
    in_mv = _post(
        db,
        company_id=company_id,
        product_id=data.product_id,
        branch_id=data.to_branch_id,
        movement_type=StockMovementType.TRANSFER,
        delta=qty,
        user_id=user_id,
        reference=data.reference,
        note=data.note,
        counterpart_branch_id=data.from_branch_id,
        allow_negative=True,  # destination only ever increases
    )
    db.commit()
    db.refresh(out_mv)
    db.refresh(in_mv)
    return out_mv, in_mv


def list_movements(
    db: Session,
    *,
    company_id: int,
    product_id: int | None = None,
    branch_id: int | None = None,
    limit: int = 100,
) -> list[StockMovement]:
    stmt = select(StockMovement).where(StockMovement.company_id == company_id)
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if branch_id is not None:
        stmt = stmt.where(StockMovement.branch_id == branch_id)
    stmt = stmt.order_by(StockMovement.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())
