"""Customers plus optical data: prescriptions and treatment history."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import TreatmentType


class Customer(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "customers"

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(20))  # DNI, CUIT...
    document_number: Mapped[str | None] = mapped_column(String(30), index=True)
    email: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(255))
    birth_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(500))


class Prescription(IDMixin, CompanyMixin, Base):
    """Receta óptica. Right eye = OD (ojo derecho), Left eye = OI (ojo izquierdo)."""

    __tablename__ = "prescriptions"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prescribed_at: Mapped[date | None] = mapped_column(Date)
    doctor_name: Mapped[str | None] = mapped_column(String(120))

    # Right eye (OD)
    right_sphere: Mapped[float | None] = mapped_column(Numeric(5, 2))
    right_cylinder: Mapped[float | None] = mapped_column(Numeric(5, 2))
    right_axis: Mapped[int | None] = mapped_column(Integer)
    right_addition: Mapped[float | None] = mapped_column(Numeric(5, 2))

    # Left eye (OI)
    left_sphere: Mapped[float | None] = mapped_column(Numeric(5, 2))
    left_cylinder: Mapped[float | None] = mapped_column(Numeric(5, 2))
    left_axis: Mapped[int | None] = mapped_column(Integer)
    left_addition: Mapped[float | None] = mapped_column(Numeric(5, 2))

    pupillary_distance: Mapped[float | None] = mapped_column(Numeric(5, 2))  # DNP
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TreatmentHistory(IDMixin, CompanyMixin, Base):
    """Historial de tratamiento óptico (e.g. miopía, astigmatismo)."""

    __tablename__ = "treatment_histories"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    treatment_type: Mapped[TreatmentType] = mapped_column(
        SAEnum(TreatmentType, name="treatment_type"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(500))
    diagnosed_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
