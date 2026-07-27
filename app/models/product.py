"""Product catalogue: product types, brands, models and products."""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import PricingMode


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


class ProductModel(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Modelo / forma del producto (clipper, aviador, redondo...).

    Shown as "Modelo" in the UI. Scoping it to a product type is optional: a row
    with ``product_type_id IS NULL`` applies to every type.
    """

    __tablename__ = "product_models"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_product_model_name"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    product_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_types.id", ondelete="SET NULL")
    )


class Product(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_product_code"),)

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    color: Mapped[str | None] = mapped_column(String(60))

    product_type_id: Mapped[int] = mapped_column(
        ForeignKey("product_types.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL")
    )
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_models.id", ondelete="SET NULL")
    )
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL")
    )

    # --- selling price -----------------------------------------------------
    # MANUAL      -> use ``sale_price``.
    # PRICE_LIST  -> look up ``price_category_code`` in ``price_list_id``; when
    #                that is NULL, fall back to the company's default list.
    # Resolution lives in services.pricing.resolve_price().
    pricing_mode: Mapped[PricingMode] = mapped_column(
        SAEnum(PricingMode, name="pricing_mode"),
        default=PricingMode.PRICE_LIST,
        # SAEnum stores member *names* (see the other enums: INBOUND, MERCHANDISE…),
        # so the server default is the name, not the value.
        server_default=PricingMode.PRICE_LIST.name,
        nullable=False,
    )
    sale_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_lists.id", ondelete="SET NULL")
    )
    # The category *code* ("AB"), not a row id: categories belong to a list, and
    # tagging by code is what lets one product be priced by any list that has
    # that step. See app/models/pricing.py.
    price_category_code: Mapped[str | None] = mapped_column(String(8))

    # Current cost snapshot; full trail lives in cost_history.
    current_cost: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    # Default minimum stock; can be overridden per branch in stock_levels.
    min_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    product_type: Mapped["ProductType"] = relationship(lazy="joined")
    brand: Mapped["Brand | None"] = relationship(lazy="joined")
    model: Mapped["ProductModel | None"] = relationship(lazy="joined")
