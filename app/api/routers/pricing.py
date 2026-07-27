from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.pricing import PriceCategory, PriceList
from app.schemas.pricing import (
    BulkPriceUpdate,
    GenerateCategories,
    GeneratePrices,
    PriceCategoryCreate,
    PriceCategoryRead,
    PriceCategoryUpdate,
    PriceListCreate,
    PriceListRead,
    PriceListSummaryRead,
    PriceListUpdate,
)
from app.services import pricing as pricing_service

router = APIRouter()


# NOTE: registered *before* the CRUD router below, otherwise "/summary" would be
# swallowed by its "/price-lists/{price_list_id}" route.
@router.get(
    "/price-lists/summary", response_model=list[PriceListSummaryRead], tags=["pricing"]
)
def price_lists_summary(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:read")),
):
    """Every list with the size and span of its category ladder."""
    stmt = select(PriceList).where(PriceList.company_id == company_id)
    if not include_inactive:
        stmt = stmt.where(PriceList.is_active.is_(True))
    lists = list(db.execute(stmt.order_by(PriceList.id)).scalars().all())

    stats = {
        r[0]: (r[1], r[2], r[3])
        for r in db.execute(
            select(
                PriceCategory.price_list_id,
                func.count(PriceCategory.id),
                func.min(PriceCategory.price),
                func.max(PriceCategory.price),
            )
            .where(
                PriceCategory.company_id == company_id,
                PriceCategory.is_active.is_(True),
            )
            .group_by(PriceCategory.price_list_id)
        ).all()
    }
    out = []
    for pl in lists:
        count, low, high = stats.get(pl.id, (0, None, None))
        data = PriceListRead.model_validate(pl, from_attributes=True).model_dump()
        out.append(
            PriceListSummaryRead(
                **data, category_count=count, min_price=low, max_price=high
            )
        )
    return out


# --- price lists via the generic factory ---------------------------------
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

# --- the categories of one list (bespoke: they are a ladder, not a set) ---
cats_router = APIRouter(prefix="/price-lists/{price_list_id}", tags=["pricing"])


def _get_list(db: Session, company_id: int, price_list_id: int) -> PriceList:
    obj = db.execute(
        select(PriceList).where(
            PriceList.id == price_list_id, PriceList.company_id == company_id
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    return obj


def _get_category(
    db: Session, company_id: int, price_list_id: int, category_id: int
) -> PriceCategory:
    cat = db.execute(
        select(PriceCategory).where(
            PriceCategory.id == category_id,
            PriceCategory.price_list_id == price_list_id,
            PriceCategory.company_id == company_id,
        )
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price category not found")
    return cat


def _bad_request(exc: pricing_service.PricingError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@cats_router.get("/categories", response_model=list[PriceCategoryRead])
def list_categories(
    price_list_id: int,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:read")),
):
    _get_list(db, company_id, price_list_id)
    return pricing_service.list_categories(
        db,
        company_id=company_id,
        price_list_id=price_list_id,
        include_inactive=include_inactive,
    )


@cats_router.post(
    "/categories", response_model=PriceCategoryRead, status_code=status.HTTP_201_CREATED
)
def add_category(
    price_list_id: int,
    data: PriceCategoryCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:write")),
):
    """Append one step. Leave ``code`` out and the next free AA..ZZ is used."""
    _get_list(db, company_id, price_list_id)
    try:
        return pricing_service.add_category(
            db,
            company_id=company_id,
            price_list_id=price_list_id,
            code=data.code,
            description=data.description,
            price=data.price,
        )
    except pricing_service.PricingError as exc:
        raise _bad_request(exc)


@cats_router.put("/categories/{category_id}", response_model=PriceCategoryRead)
def update_category(
    price_list_id: int,
    category_id: int,
    data: PriceCategoryUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("pricing:write")),
):
    _get_list(db, company_id, price_list_id)
    cat = _get_category(db, company_id, price_list_id, category_id)
    payload = data.model_dump(exclude_unset=True)

    # The price goes through the service so the change reaches change_history.
    new_price = payload.pop("price", None)
    for field, value in payload.items():
        setattr(cat, field, value)
    try:
        if new_price is not None:
            pricing_service.set_category_price(
                db, cat, new_price, company_id=company_id, user_id=current_user.id
            )
    except pricing_service.PricingError as exc:
        db.rollback()
        raise _bad_request(exc)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@cats_router.delete(
    "/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_category(
    price_list_id: int,
    category_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:write")),
):
    """Soft delete: the step stops pricing products but its price is kept."""
    _get_list(db, company_id, price_list_id)
    cat = _get_category(db, company_id, price_list_id, category_id)
    cat.is_active = False
    db.add(cat)
    db.commit()
    return None


@cats_router.post("/generate-categories", response_model=list[PriceCategoryRead])
def generate_categories(
    price_list_id: int,
    data: GenerateCategories,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:write")),
):
    """Set the list to exactly N steps named AA, AB, AC…"""
    _get_list(db, company_id, price_list_id)
    try:
        return pricing_service.set_category_count(
            db, company_id=company_id, price_list_id=price_list_id, count=data.count
        )
    except pricing_service.PricingError as exc:
        db.rollback()
        raise _bad_request(exc)


@cats_router.post("/generate-prices")
def generate_prices(
    price_list_id: int,
    data: GeneratePrices,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("pricing:write")),
):
    """Spread a min..max range across the ladder, rounded (audited)."""
    _get_list(db, company_id, price_list_id)
    try:
        count = pricing_service.generate_prices(
            db,
            company_id=company_id,
            price_list_id=price_list_id,
            min_price=data.min_price,
            max_price=data.max_price,
            rounding_step=data.rounding_step,
            rounding_mode=data.rounding_mode,
            user_id=current_user.id,
        )
    except pricing_service.PricingError as exc:
        db.rollback()
        raise _bad_request(exc)
    return {"updated_items": count}


@cats_router.post("/bulk-update")
def bulk_update(
    price_list_id: int,
    data: BulkPriceUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("pricing:write")),
):
    """Apply a percentage change to every category in the list (audited)."""
    _get_list(db, company_id, price_list_id)
    try:
        count = pricing_service.bulk_update_prices(
            db,
            company_id=company_id,
            price_list_id=price_list_id,
            percentage=data.percentage,
            rounding_step=data.rounding_step,
            rounding_mode=data.rounding_mode,
            user_id=current_user.id,
        )
    except pricing_service.PricingError as exc:
        db.rollback()
        raise _bad_request(exc)
    return {"updated_items": count, "percentage": data.percentage}


router.include_router(cats_router)


# --- every code in use, for the product form ------------------------------
@router.get("/price-category-codes", tags=["pricing"])
def category_codes(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("pricing:read")),
):
    """Distinct category codes across the company's active lists.

    Products are tagged by code, so the picker offers every code that at least
    one list knows how to price, plus how many lists that is.
    """
    rows = db.execute(
        select(PriceCategory.code, func.count(func.distinct(PriceCategory.price_list_id)))
        .join(PriceList, PriceList.id == PriceCategory.price_list_id)
        .where(
            PriceCategory.company_id == company_id,
            PriceCategory.is_active.is_(True),
            PriceList.is_active.is_(True),
        )
        .group_by(PriceCategory.code)
        .order_by(PriceCategory.code)
    ).all()
    return [{"code": r[0], "list_count": r[1]} for r in rows]
