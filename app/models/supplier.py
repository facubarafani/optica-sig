"""Suppliers / third parties: merchandise providers, labs and workshops."""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import SupplierType


class Supplier(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    supplier_type: Mapped[SupplierType] = mapped_column(
        SAEnum(SupplierType, name="supplier_type"), nullable=False
    )
    tax_id: Mapped[str | None] = mapped_column(String(20))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(String(500))
