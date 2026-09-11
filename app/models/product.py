"""Product catalogue: product types, brands, models and products."""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Numeric, String, Table, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import PricingMode

# --- association table ----------------------------------------------------
# Which colours a product comes in. The same frame is usually stocked in
# several, so the link is N-N rather than a column on the product. A link
# either exists or it doesn't, hence no soft delete; and no company_id, since
# both sides are already company-scoped (same rationale as ``supplier_brands``).
product_colors = Table(
    "product_colors",
    Base.metadata,
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"),
           primary_key=True),
    Column("color_id", ForeignKey("colors.id", ondelete="CASCADE"),
           primary_key=True),
)


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


class Color(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A colour in the shop's palette ("Negro", "Havana", "Carey").

    Master data rather than free text on the product: it keeps one canonical
    spelling, makes "todos los armazones negros" a real filter, and gives the
    console a swatch to draw. A product may carry several of them, since the
    same frame is usually stocked in more than one (``product_colors``).

    ``hex_code`` is that swatch — presentation only, nothing resolves against
    it, so it may be NULL for a colour nobody has picked a shade for yet.
    """

    __tablename__ = "colors"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_color_name"),
        UniqueConstraint("company_id", "code", name="uq_color_code"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Short tag ("NEG", "HAV") that suffixes a variant's product code:
    # ARM-001 + HAV -> ARM-001-HAV. Derived from the name by
    # services.products.derive_color_code when not given, but editable — a shop
    # with its own supplier coding must be able to impose it.
    code: Mapped[str | None] = mapped_column(String(8))
    # "#rrggbb", lower-cased by the schema validator.
    hex_code: Mapped[str | None] = mapped_column(String(7))


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
    """A sellable article — and, when it has variants, the style they share.

    The same frame is stocked in several colours, and each colour is its own
    article: its own code, its own stock, its own line on a sale. So a variant
    is a ``products`` row like any other, pointed at its style by ``parent_id``,
    rather than a separate table — everything that references a product
    (stock_levels, stock_movements, sale_items, cost_history) keeps working
    without knowing the family exists.

    A row with variants is the style, not an article: it must not be sold or
    stocked, or the same shirt's stock ends up split between "ARM-001" and
    "ARM-001-NEG" with neither number true. ``services.products.assert_sellable``
    is the single place that enforces it.
    """

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_product_code"),)

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))

    # NULL = a style, or a plain article with no variants. RESTRICT rather than
    # SET NULL: silently promoting orphaned variants to styles would be worse
    # than refusing the delete.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )

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
    # selectin, not joined: a collection joined onto a list query multiplies the
    # rows. This costs one extra query for the whole page instead.
    colors: Mapped[list["Color"]] = relationship(
        secondary=product_colors, lazy="selectin", order_by="Color.name"
    )

    parent: Mapped["Product | None"] = relationship(
        "Product", remote_side="Product.id", back_populates="variants"
    )
    variants: Mapped[list["Product"]] = relationship(
        back_populates="parent", order_by="Product.code"
    )

    @property
    def color_ids(self) -> list[int]:
        """Flat id list — what the API reads and writes (see ProductRead)."""
        return [c.id for c in self.colors]
