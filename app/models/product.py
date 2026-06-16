"""Product catalogue: product types, brands and products."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin


class ProductType(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Tipo de producto (e.g. frames, sunglasses, contact lenses, accessories)."""

    __tablename__ = "product_types"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_product_type_name"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))


class Brand(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_brand_name"),)

    name: Mapped[str] = mapped_column(String(80), nullable=False)


class Product(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_product_code"),)

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str | None] = mapped_column(String(120))
    color: Mapped[str | None] = mapped_column(String(60))

    product_type_id: Mapped[int] = mapped_column(
        ForeignKey("product_types.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL")
    )
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    price_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_categories.id", ondelete="SET NULL")
    )

    # Current cost snapshot; full trail lives in cost_history.
    current_cost: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    # Default minimum stock; can be overridden per branch in stock_levels.
    min_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    product_type: Mapped["ProductType"] = relationship(lazy="joined")
    brand: Mapped["Brand | None"] = relationship(lazy="joined")
