"""Catalogue support entities: product types, brands and colours."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.product import Brand, Color, ProductType
from app.schemas.product import (
    BrandCreate,
    BrandRead,
    BrandUpdate,
    ColorCreate,
    ColorRead,
    ColorUpdate,
    ProductTypeCreate,
    ProductTypeRead,
    ProductTypeUpdate,
)
from app.services import products as products_service

router = APIRouter()

router.include_router(
    build_crud_router(
        prefix="/product-types",
        tags=["catalog"],
        crud=CRUDBase(ProductType),
        create_schema=ProductTypeCreate,
        update_schema=ProductTypeUpdate,
        read_schema=ProductTypeRead,
        permission="products",
    )
)

router.include_router(
    build_crud_router(
        prefix="/brands",
        tags=["catalog"],
        crud=CRUDBase(Brand),
        create_schema=BrandCreate,
        update_schema=BrandUpdate,
        read_schema=BrandRead,
        permission="products",
    )
)

# Colours reuse the generic router for list/get/delete, but create and update
# are bespoke: `code` is the tag that ends up inside a variant's product code
# (ARM-001-HAV), so it is derived from the name when nobody supplies one.
_colors = CRUDBase(Color)
colors_router = build_crud_router(
    prefix="/colors",
    tags=["catalog"],
    crud=_colors,
    create_schema=ColorCreate,
    update_schema=ColorUpdate,
    read_schema=ColorRead,
    permission="products",
)
# Drop the generic write routes so the ones below own those paths.
colors_router.routes = [
    r for r in colors_router.routes
    if not (r.path == "/colors" and "POST" in r.methods)
    and not (r.path == "/colors/{item_id}" and "PUT" in r.methods)
]


@colors_router.post("", response_model=ColorRead, status_code=status.HTTP_201_CREATED)
def create_color(
    data: ColorCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    payload = data.model_dump(exclude_unset=True)
    if not payload.get("code"):
        payload["code"] = products_service.derive_color_code(
            db, payload.get("name", ""), company_id=company_id
        )
    obj = Color(**payload, company_id=company_id)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@colors_router.put("/{item_id}", response_model=ColorRead)
def update_color(
    item_id: int,
    data: ColorUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    obj = _colors.get(db, item_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    payload = data.model_dump(exclude_unset=True)
    # Renaming a colour that never had a code is the moment to give it one;
    # a code already in use is left alone, since product codes carry it.
    if payload.get("name") and not obj.code and "code" not in payload:
        payload["code"] = products_service.derive_color_code(
            db, payload["name"], company_id=company_id, exclude_id=obj.id
        )
    for field, value in payload.items():
        setattr(obj, field, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


router.include_router(colors_router)
