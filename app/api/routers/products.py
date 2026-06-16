from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.product import Product
from app.schemas.pricing import CostHistoryRead
from app.schemas.product import CostUpdate, ProductCreate, ProductRead, ProductUpdate
from app.services import pricing as pricing_service

router = APIRouter(prefix="/products", tags=["products"])
crud = CRUDBase(Product)


@router.get("", response_model=list[ProductRead])
def list_products(
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
    product_type_id: int | None = None,
    brand_id: int | None = None,
    supplier_id: int | None = None,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    return crud.list(
        db,
        company_id=company_id,
        skip=skip,
        limit=limit,
        include_inactive=include_inactive,
        filters={
            "product_type_id": product_type_id,
            "brand_id": brand_id,
            "supplier_id": supplier_id,
        },
    )


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    return crud.create(db, data, company_id=company_id)


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
    return obj


@router.put("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    obj = crud.get(db, product_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return crud.update(db, obj, data)


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
        return pricing_service.change_cost(
            db, obj, data.new_cost, user_id=current_user.id, note=data.note
        )
    except pricing_service.PricingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


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
