"""Product models ("Modelo": clipper, aviador, redondo...).

A dedicated router rather than ``build_crud_router`` because listing needs an
OR-condition the generic builder cannot express: when filtering by product type
we must also return the untyped models, which apply to every type.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.product import ProductModel
from app.schemas.product import (
    ProductModelCreate,
    ProductModelRead,
    ProductModelUpdate,
)

router = APIRouter(prefix="/product-models", tags=["catalog"])
crud = CRUDBase(ProductModel)


@router.get("", response_model=list[ProductModelRead])
def list_product_models(
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
    product_type_id: int | None = None,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    """List models. With ``product_type_id``, returns that type's models *plus*
    the untyped ones (which apply to every type)."""
    stmt = select(ProductModel).where(ProductModel.company_id == company_id)
    if not include_inactive:
        stmt = stmt.where(ProductModel.is_active.is_(True))
    if product_type_id is not None:
        stmt = stmt.where(
            or_(
                ProductModel.product_type_id == product_type_id,
                ProductModel.product_type_id.is_(None),
            )
        )
    stmt = stmt.order_by(ProductModel.name).offset(skip).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=ProductModelRead, status_code=status.HTTP_201_CREATED)
def create_product_model(
    data: ProductModelCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    return crud.create(db, data, company_id=company_id)


@router.get("/{item_id}", response_model=ProductModelRead)
def get_product_model(
    item_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    obj = crud.get(db, item_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product model not found")
    return obj


@router.put("/{item_id}", response_model=ProductModelRead)
def update_product_model(
    item_id: int,
    data: ProductModelUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    obj = crud.get(db, item_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product model not found")
    return crud.update(db, obj, data)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_model(
    item_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    obj = crud.get(db, item_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product model not found")
    crud.remove(db, obj)
    return None
