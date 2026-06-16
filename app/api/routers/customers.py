from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.customer import Customer, Prescription, TreatmentHistory
from app.schemas.customer import (
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    PrescriptionCreate,
    PrescriptionRead,
    TreatmentHistoryCreate,
    TreatmentHistoryRead,
)

router = APIRouter(prefix="/customers", tags=["customers"])
crud = CRUDBase(Customer)


# --- customers ------------------------------------------------------------
@router.get("", response_model=list[CustomerRead])
def list_customers(
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:read")),
):
    return crud.list(
        db, company_id=company_id, skip=skip, limit=limit,
        include_inactive=include_inactive,
    )


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    data: CustomerCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:write")),
):
    return crud.create(db, data, company_id=company_id)


def _get_customer(db: Session, company_id: int, customer_id: int) -> Customer:
    obj = crud.get(db, customer_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return obj


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:read")),
):
    return _get_customer(db, company_id, customer_id)


@router.put("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:write")),
):
    obj = _get_customer(db, company_id, customer_id)
    return crud.update(db, obj, data)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:write")),
):
    obj = _get_customer(db, company_id, customer_id)
    crud.remove(db, obj)
    return None


# --- prescriptions --------------------------------------------------------
@router.get("/{customer_id}/prescriptions", response_model=list[PrescriptionRead])
def list_prescriptions(
    customer_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:read")),
):
    _get_customer(db, company_id, customer_id)
    return list(
        db.execute(
            select(Prescription).where(
                Prescription.company_id == company_id,
                Prescription.customer_id == customer_id,
            ).order_by(Prescription.id.desc())
        ).scalars().all()
    )


@router.post(
    "/{customer_id}/prescriptions",
    response_model=PrescriptionRead,
    status_code=status.HTTP_201_CREATED,
)
def add_prescription(
    customer_id: int,
    data: PrescriptionCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("customers:write")),
):
    _get_customer(db, company_id, customer_id)
    obj = Prescription(
        company_id=company_id,
        customer_id=customer_id,
        created_by_user_id=current_user.id,
        **data.model_dump(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# --- treatment history ----------------------------------------------------
@router.get("/{customer_id}/treatments", response_model=list[TreatmentHistoryRead])
def list_treatments(
    customer_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:read")),
):
    _get_customer(db, company_id, customer_id)
    return list(
        db.execute(
            select(TreatmentHistory).where(
                TreatmentHistory.company_id == company_id,
                TreatmentHistory.customer_id == customer_id,
            ).order_by(TreatmentHistory.id.desc())
        ).scalars().all()
    )


@router.post(
    "/{customer_id}/treatments",
    response_model=TreatmentHistoryRead,
    status_code=status.HTTP_201_CREATED,
)
def add_treatment(
    customer_id: int,
    data: TreatmentHistoryCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:write")),
):
    _get_customer(db, company_id, customer_id)
    obj = TreatmentHistory(
        company_id=company_id, customer_id=customer_id, **data.model_dump()
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
