from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.company import CompanySettings
from app.schemas.stock import (
    StockLevelRead,
    StockMovementCreate,
    StockMovementRead,
    StockTransferCreate,
)
from app.services import stock as stock_service

router = APIRouter(prefix="/stock", tags=["stock"])


def _allow_negative(db: Session, company_id: int) -> bool:
    cfg = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    return bool(cfg.allow_negative_stock) if cfg else False


@router.get("/levels", response_model=list[StockLevelRead])
def list_levels(
    product_id: int | None = None,
    branch_id: int | None = None,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("stock:read")),
):
    return stock_service.list_levels(
        db, company_id=company_id, product_id=product_id, branch_id=branch_id
    )


@router.get("/movements", response_model=list[StockMovementRead])
def list_movements(
    product_id: int | None = None,
    branch_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("stock:read")),
):
    return stock_service.list_movements(
        db, company_id=company_id, product_id=product_id, branch_id=branch_id, limit=limit
    )


@router.post(
    "/movements", response_model=StockMovementRead, status_code=status.HTTP_201_CREATED
)
def create_movement(
    data: StockMovementCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("stock:write")),
):
    try:
        return stock_service.apply_movement(
            db,
            data,
            company_id=company_id,
            user_id=current_user.id,
            allow_negative=_allow_negative(db, company_id),
        )
    except stock_service.StockError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/transfers",
    response_model=list[StockMovementRead],
    status_code=status.HTTP_201_CREATED,
)
def create_transfer(
    data: StockTransferCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("stock:write")),
):
    try:
        out_mv, in_mv = stock_service.apply_transfer(
            db,
            data,
            company_id=company_id,
            user_id=current_user.id,
            allow_negative=_allow_negative(db, company_id),
        )
    except stock_service.StockError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return [out_mv, in_mv]
