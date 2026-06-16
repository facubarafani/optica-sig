from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.company import Company, CompanySettings
from app.schemas.company import (
    CompanyRead,
    CompanySettingsRead,
    CompanySettingsUpdate,
    CompanyUpdate,
)

router = APIRouter(prefix="/company", tags=["company"])


def _get_company(db: Session, company_id: int) -> Company:
    obj = db.get(Company, company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return obj


@router.get("", response_model=CompanyRead)
def get_company(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("company:read")),
):
    return _get_company(db, company_id)


@router.put("", response_model=CompanyRead)
def update_company(
    data: CompanyUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("company:write")),
):
    obj = _get_company(db, company_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/settings", response_model=CompanySettingsRead)
def get_settings(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("company:read")),
):
    obj = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    if obj is None:
        obj = CompanySettings(company_id=company_id)
        db.add(obj)
        db.commit()
        db.refresh(obj)
    return obj


@router.put("/settings", response_model=CompanySettingsRead)
def update_settings(
    data: CompanySettingsUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("company:write")),
):
    obj = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    if obj is None:
        obj = CompanySettings(company_id=company_id)
        db.add(obj)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
