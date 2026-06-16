from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.pricing import PriceCategory, PriceList, PriceListItem
from app.schemas.pricing import (
    BulkPriceUpdate,
    PriceCategoryCreate,
    PriceCategoryRead,
    PriceCategoryUpdate,
    PriceListCreate,
    PriceListItemCreate,
    PriceListItemRead,
    PriceListItemUpdate,
    PriceListRead,
    PriceListUpdate,
)
from app.services import pricing as pricing_service

router = APIRouter()

# --- price categories & lists via the generic factory --------------------
router.include_router(
    build_crud_router(
        prefix="/price-categories",
        tags=["pricing"],
        crud=CRUDBase(PriceCategory),
        create_schema=PriceCategoryCreate,
        update_schema=PriceCategoryUpdate,
        read_schema=PriceCategoryRead,
        permission="pricing",
    )
)
router.include_router(
    build_crud_router(
        prefix="/price-lists",
        tags=["pricing"],
        crud=CRUDBase(PriceList),
        create_schema=PriceListCreate,
        update_schema=PriceListUpdate,
        read_schema=PriceListRead,
        permission="pricing",
    )
)

# --- price list items + bulk update (bespoke) ----------------------------
items_router = APIRouter(prefix="/price-lists/{price_list_id}", tags=["pricing"])
item_crud = CRUDBase(PriceListItem)


def _get_list(db: Session, company_id: int, price_list_id: int) -> PriceList:
    obj = db.execute(
        select(PriceList).where(
            PriceList.id == price_list_id, PriceList.company_id == company_id
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    return obj


@items_router.get("/items", response_model=list[PriceListItemRead])
def list_items(
    price_list_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:read")),
):
    _get_list(db, company_id, price_list_id)
    return list(
        db.execute(
            select(PriceListItem).where(
                PriceListItem.company_id == company_id,
                PriceListItem.price_list_id == price_list_id,
            ).order_by(PriceListItem.id)
        ).scalars().all()
    )


@items_router.post(
    "/items", response_model=PriceListItemRead, status_code=status.HTTP_201_CREATED
)
def add_item(
    price_list_id: int,
    data: PriceListItemCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:write")),
):
    _get_list(db, company_id, price_list_id)
    item = PriceListItem(
        company_id=company_id,
        price_list_id=price_list_id,
        price_category_id=data.price_category_id,
        price=data.price,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@items_router.put("/items/{item_id}", response_model=PriceListItemRead)
def update_item(
    price_list_id: int,
    item_id: int,
    data: PriceListItemUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:write")),
):
    item = db.execute(
        select(PriceListItem).where(
            PriceListItem.id == item_id,
            PriceListItem.price_list_id == price_list_id,
            PriceListItem.company_id == company_id,
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list item not found")
    item.price = data.price
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@items_router.post("/bulk-update")
def bulk_update(
    price_list_id: int,
    data: BulkPriceUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("pricing:write")),
):
    """Apply a percentage change to every item in the list (audited)."""
    _get_list(db, company_id, price_list_id)
    count = pricing_service.bulk_update_prices(
        db,
        company_id=company_id,
        price_list_id=price_list_id,
        percentage=data.percentage,
        user_id=current_user.id,
    )
    return {"updated_items": count, "percentage": data.percentage}


router.include_router(items_router)
