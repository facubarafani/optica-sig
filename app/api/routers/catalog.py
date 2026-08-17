"""Catalogue support entities: product types, brands and colours."""
from fastapi import APIRouter

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
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

router.include_router(
    build_crud_router(
        prefix="/colors",
        tags=["catalog"],
        crud=CRUDBase(Color),
        create_schema=ColorCreate,
        update_schema=ColorUpdate,
        read_schema=ColorRead,
        permission="products",
    )
)
