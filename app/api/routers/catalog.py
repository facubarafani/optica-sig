"""Catalogue support entities: product types and brands."""
from fastapi import APIRouter

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.models.product import Brand, ProductType
from app.schemas.product import (
    BrandCreate,
    BrandRead,
    BrandUpdate,
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
