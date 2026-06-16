from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr

from app.models.enums import TreatmentType
from app.schemas.common import ORMBase, SoftDeleteRead


# --- customer -------------------------------------------------------------
class CustomerBase(BaseModel):
    first_name: str
    last_name: str
    document_type: str | None = None
    document_number: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    birth_date: date | None = None
    notes: str | None = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    document_type: str | None = None
    document_number: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    birth_date: date | None = None
    notes: str | None = None
    is_active: bool | None = None


class CustomerRead(SoftDeleteRead, CustomerBase):
    pass


# --- prescription ---------------------------------------------------------
class PrescriptionBase(BaseModel):
    prescribed_at: date | None = None
    doctor_name: str | None = None
    right_sphere: Decimal | None = None
    right_cylinder: Decimal | None = None
    right_axis: int | None = None
    right_addition: Decimal | None = None
    left_sphere: Decimal | None = None
    left_cylinder: Decimal | None = None
    left_axis: int | None = None
    left_addition: Decimal | None = None
    pupillary_distance: Decimal | None = None
    notes: str | None = None


class PrescriptionCreate(PrescriptionBase):
    pass


class PrescriptionRead(ORMBase, PrescriptionBase):
    id: int
    customer_id: int
    created_by_user_id: int | None = None
    created_at: datetime


# --- treatment history ----------------------------------------------------
class TreatmentHistoryCreate(BaseModel):
    treatment_type: TreatmentType
    description: str | None = None
    diagnosed_at: date | None = None


class TreatmentHistoryRead(ORMBase):
    id: int
    customer_id: int
    treatment_type: TreatmentType
    description: str | None = None
    diagnosed_at: date | None = None
    created_at: datetime
