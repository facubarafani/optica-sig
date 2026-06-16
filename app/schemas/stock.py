from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import StockMovementType
from app.schemas.common import ORMBase


class StockLevelRead(ORMBase):
    id: int
    product_id: int
    branch_id: int
    quantity: Decimal
    min_stock: Decimal | None = None


class StockMovementCreate(BaseModel):
    """Record an inbound/outbound/adjustment movement for one branch.

    Use the transfer endpoint for branch-to-branch transfers.
    """

    product_id: int
    branch_id: int
    movement_type: StockMovementType
    quantity: Decimal  # positive magnitude
    reference: str | None = None
    note: str | None = None


class StockTransferCreate(BaseModel):
    product_id: int
    from_branch_id: int
    to_branch_id: int
    quantity: Decimal
    reference: str | None = None
    note: str | None = None


class StockMovementRead(ORMBase):
    id: int
    product_id: int
    branch_id: int
    movement_type: StockMovementType
    quantity: Decimal
    resulting_quantity: Decimal
    counterpart_branch_id: int | None = None
    reference: str | None = None
    note: str | None = None
    created_by_user_id: int | None = None
    created_at: datetime
