from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import DebtLight, DocumentType, IvaCondition, TreatmentType
from app.schemas.common import ORMBase, SoftDeleteRead


def _canonical_document_type(value: str | None) -> str | None:
    """A known spelling becomes the controlled value ("d.n.i." -> "DNI").

    Anything else is kept as typed, so a customer saved before the field was a
    list still saves; invoicing is what refuses a type ARCA does not accept.
    """
    if value is None or not value.strip():
        return None
    known = DocumentType.parse(value)
    return known.value if known else value.strip()


# Treatments and prescriptions come ahead of the customer schemas, because a
# new customer can bring them along.

# --- treatment history ----------------------------------------------------
class TreatmentHistoryCreate(BaseModel):
    treatment_type: TreatmentType
    description: str | None = Field(default=None, max_length=500)
    diagnosed_at: date | None = None


class TreatmentHistoryRead(ORMBase):
    id: int
    customer_id: int
    treatment_type: TreatmentType
    description: str | None = None
    diagnosed_at: date | None = None
    created_at: datetime


# --- prescription ---------------------------------------------------------
class PrescriptionBase(BaseModel):
    prescribed_at: date | None = None
    doctor_name: str | None = Field(default=None, max_length=120)
    right_sphere: Decimal | None = None
    right_cylinder: Decimal | None = None
    right_axis: int | None = None
    right_addition: Decimal | None = None
    left_sphere: Decimal | None = None
    left_cylinder: Decimal | None = None
    left_axis: int | None = None
    left_addition: Decimal | None = None
    pupillary_distance: Decimal | None = None
    notes: str | None = Field(default=None, max_length=500)


# What a Numeric(5, 2) column holds: past it Postgres refuses the row with a
# 500. A capacity, not a medical range: the receta grid flags odd values.
_DIOPTRE = {"default": None, "ge": Decimal("-999.99"), "le": Decimal("999.99")}


class PrescriptionCreate(PrescriptionBase):
    # Checked on the way in only. Recetas typed before these checks may hold an
    # axis past 180, and reading them back must never fail.
    right_sphere: Decimal | None = Field(**_DIOPTRE)
    right_cylinder: Decimal | None = Field(**_DIOPTRE)
    right_axis: int | None = Field(default=None, ge=0, le=180)
    right_addition: Decimal | None = Field(**_DIOPTRE)
    left_sphere: Decimal | None = Field(**_DIOPTRE)
    left_cylinder: Decimal | None = Field(**_DIOPTRE)
    left_axis: int | None = Field(default=None, ge=0, le=180)
    left_addition: Decimal | None = Field(**_DIOPTRE)
    pupillary_distance: Decimal | None = Field(**_DIOPTRE)


class PrescriptionRead(ORMBase, PrescriptionBase):
    id: int
    customer_id: int
    created_by_user_id: int | None = None
    created_at: datetime


# --- customer -------------------------------------------------------------
class CustomerBase(BaseModel):
    # The max_lengths mirror the columns (see tests/test_schema_lengths.py).
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    document_type: str | None = Field(default=None, max_length=20)
    document_number: str | None = Field(default=None, max_length=30)
    # Empty is a consumidor final. Decides A or B for a Responsable Inscripto.
    iva_condition: IvaCondition | None = None
    email: EmailStr | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    birth_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)

    _document_type = field_validator("document_type")(_canonical_document_type)


class CustomerCreate(CustomerBase):
    # The new-customer form's optional steps. Written in the same transaction
    # as the customer, so a refused one leaves no customer behind.
    treatments: list[TreatmentHistoryCreate] = []
    prescription: PrescriptionCreate | None = None


class CustomerUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    document_type: str | None = Field(default=None, max_length=20)
    document_number: str | None = Field(default=None, max_length=30)
    iva_condition: IvaCondition | None = None
    email: EmailStr | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    birth_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None

    _document_type = field_validator("document_type")(_canonical_document_type)


class CustomerRead(SoftDeleteRead, CustomerBase):
    pass


class CustomerDebt(BaseModel):
    """What a customer owes, under the light of their worst debt.

    ``due`` is that debt's promised date (the most overdue when red, the
    soonest due otherwise), or None when it has none.
    """

    light: DebtLight
    due: date | None = None
    owed: Decimal
    count: int


class CustomerListRead(CustomerRead):
    # Only for whoever may see sales; None also when nothing is owed.
    debt: CustomerDebt | None = None
    # Each kind of treatment on file, once, in TreatmentType's order: what the
    # list's Tratamientos column draws. Customer data, so everyone gets it.
    treatments: list[TreatmentType] = []
