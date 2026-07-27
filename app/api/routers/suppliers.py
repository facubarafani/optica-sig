"""Suppliers + the brands each one provides."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.product import Brand
from app.models.supplier import Supplier, supplier_brands
from app.schemas.product import BrandRead
from app.schemas.supplier import (
    SupplierBrandsUpdate,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)

router = build_crud_router(
    prefix="/suppliers",
    tags=["suppliers"],
    crud=CRUDBase(Supplier),
    create_schema=SupplierCreate,
    update_schema=SupplierUpdate,
    read_schema=SupplierRead,
    permission="suppliers",
)

_suppliers = CRUDBase(Supplier)


def _get_supplier(db: Session, supplier_id: int, company_id: int) -> Supplier:
    obj = _suppliers.get(db, supplier_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    return obj


def _brands_of(db: Session, supplier_id: int, company_id: int) -> list[Brand]:
    stmt = (
        select(Brand)
        .join(supplier_brands, supplier_brands.c.brand_id == Brand.id)
        .where(
            supplier_brands.c.supplier_id == supplier_id,
            Brand.company_id == company_id,
            Brand.is_active.is_(True),
        )
        .order_by(Brand.name)
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/{supplier_id}/brands", response_model=list[BrandRead])
def list_supplier_brands(
    supplier_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("suppliers:read")),
):
    """Brands this supplier provides — drives the filtered brand dropdown."""
    _get_supplier(db, supplier_id, company_id)
    return _brands_of(db, supplier_id, company_id)


@router.put("/{supplier_id}/brands", response_model=list[BrandRead])
def set_supplier_brands(
    supplier_id: int,
    data: SupplierBrandsUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("suppliers:write")),
):
    """Replace the supplier's whole brand set."""
    _get_supplier(db, supplier_id, company_id)

    brand_ids = sorted(set(data.brand_ids))
    if brand_ids:
        # Reject brands from another company (or that simply do not exist).
        found = set(
            db.execute(
                select(Brand.id).where(
                    Brand.id.in_(brand_ids), Brand.company_id == company_id
                )
            ).scalars()
        )
        missing = [b for b in brand_ids if b not in found]
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown brand id(s): {', '.join(map(str, missing))}",
            )

    db.execute(
        delete(supplier_brands).where(supplier_brands.c.supplier_id == supplier_id)
    )
    if brand_ids:
        db.execute(
            insert(supplier_brands),
            [{"supplier_id": supplier_id, "brand_id": b} for b in brand_ids],
        )
    db.commit()
    return _brands_of(db, supplier_id, company_id)
