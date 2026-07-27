from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.product import Product
from app.schemas.pricing import CostHistoryRead
from app.schemas.product import (
    CostUpdate,
    ProductCreate,
    ProductPriceRead,
    ProductRead,
    ProductUpdate,
)
from app.services import pricing as pricing_service

router = APIRouter(prefix="/products", tags=["products"])
crud = CRUDBase(Product)


def _with_prices(db: Session, products: list[Product], company_id: int) -> list[dict]:
    """Attach the resolved selling price to each product.

    Uses the batch resolver, so the whole list costs one extra query rather
    than one per row.
    """
    resolved = pricing_service.resolve_prices(db, products, company_id=company_id)
    out = []
    for p in products:
        data = ProductRead.model_validate(p, from_attributes=True).model_dump()
        r = resolved[p.id]
        data["resolved_sale_price"] = r.price
        data["price_source"] = r.source
        data["price_reason"] = r.reason
        data["price_currency"] = r.currency
        out.append(data)
    return out


@router.get("", response_model=list[ProductRead])
def list_products(
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
    product_type_id: int | None = None,
    brand_id: int | None = None,
    model_id: int | None = None,
    supplier_id: int | None = None,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    products = crud.list(
        db,
        company_id=company_id,
        skip=skip,
        limit=limit,
        include_inactive=include_inactive,
        filters={
            "product_type_id": product_type_id,
            "brand_id": brand_id,
            "model_id": model_id,
            "supplier_id": supplier_id,
        },
    )
    return _with_prices(db, products, company_id)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    obj = Product(**data.model_dump(exclude_unset=True), company_id=company_id)
    try:
        pricing_service.validate_pricing(db, obj, company_id=company_id)
    except pricing_service.PricingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _with_prices(db, [obj], company_id)[0]


@router.get("/{product_id}", response_model=ProductRead)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    obj = crud.get(db, product_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return _with_prices(db, [obj], company_id)[0]


@router.get("/{product_id}/price", response_model=ProductPriceRead)
def get_product_price(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    """Explain where this product's selling price comes from."""
    obj = crud.get(db, product_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    r = pricing_service.resolve_price(db, obj, company_id=company_id)
    return ProductPriceRead(
        product_id=obj.id,
        price=r.price,
        source=r.source,
        price_list_id=r.price_list_id,
        currency=r.currency,
        reason=r.reason,
    )


@router.put("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("products:write")),
):
    obj = crud.get(db, product_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    payload = data.model_dump(exclude_unset=True)
    # Pricing fields are split out so each change is audited.
    pricing_payload = {
        k: payload.pop(k)
        for k in list(payload)
        if k in ("pricing_mode", "sale_price", "price_list_id", "price_category_code")
    }
    for field, value in payload.items():
        setattr(obj, field, value)
    if pricing_payload:
        pricing_service.apply_pricing_update(
            db, obj, pricing_payload, user_id=current_user.id
        )
    try:
        pricing_service.validate_pricing(db, obj, company_id=company_id)
    except pricing_service.PricingError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _with_prices(db, [obj], company_id)[0]


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    obj = crud.get(db, product_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    crud.remove(db, obj)
    return None


@router.post("/{product_id}/cost", response_model=ProductRead)
def change_cost(
    product_id: int,
    data: CostUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("products:write")),
):
    """Change a product's cost (audited + recorded in cost_history)."""
    obj = crud.get(db, product_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    try:
        obj = pricing_service.change_cost(
            db, obj, data.new_cost, user_id=current_user.id, note=data.note
        )
    except pricing_service.PricingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return _with_prices(db, [obj], company_id)[0]


@router.get("/{product_id}/cost-history", response_model=list[CostHistoryRead])
def cost_history(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    return pricing_service.list_cost_history(
        db, company_id=company_id, product_id=product_id
    )
