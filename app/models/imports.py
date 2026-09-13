"""Bulk import batches.

An upload is staged as a row here so the preview and the confirmation are two
separate requests over the same parsed data (no re-upload), and so there is a
history of what was imported, when and by whom.

``mapping`` and ``rows`` hold JSON in a plain ``Text`` column rather than JSONB:
the test suite runs on SQLite, so the schema must stay portable (CLAUDE.md).
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, TimestampMixin
from app.models.enums import ColorAliasKind
from app.models.product import Color

# A tail can mean two colours at once ("BLACK BLUE"), hence N-N. Same shape and
# rationale as ``product_colors``: no company_id, both sides already carry one.
color_alias_colors = Table(
    "color_alias_colors",
    Base.metadata,
    Column("alias_id", ForeignKey("color_aliases.id", ondelete="CASCADE"),
           primary_key=True),
    Column("color_id", ForeignKey("colors.id", ondelete="CASCADE"),
           primary_key=True),
)


class ColorAlias(IDMixin, CompanyMixin, TimestampMixin, Base):
    """What a shop decided one code tail means, so the next import knows.

    ``phrase`` is the tail as services.importer.code_colors.norm keys it:
    upper-cased, accents folded ("NERO MATE", "C1"). A shop's suppliers spell
    colours their own way, so this table is where the importer learns that
    shop's dialect rather than guessing it again every time. Overwritten, not
    versioned: the latest confirmed answer is the one that counts.
    """

    __tablename__ = "color_aliases"
    __table_args__ = (
        UniqueConstraint("company_id", "phrase", name="uq_color_alias_phrase"),
    )

    phrase: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[ColorAliasKind] = mapped_column(
        SAEnum(ColorAliasKind, name="color_alias_kind"), nullable=False
    )
    colors: Mapped[list[Color]] = relationship(
        secondary=color_alias_colors, lazy="selectin"
    )


class ImportBatch(IDMixin, CompanyMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"

    spec_key: Mapped[str] = mapped_column(String(40), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="uploaded", nullable=False
    )  # uploaded | committed | cancelled
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    headers: Mapped[str] = mapped_column(Text, nullable=False)   # JSON list[str]
    rows: Mapped[str] = mapped_column(Text, nullable=False)      # JSON list[list]
    mapping: Mapped[str | None] = mapped_column(Text)            # JSON dict
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Filled in on commit: how many rows were created / updated.
    result: Mapped[str | None] = mapped_column(Text)             # JSON dict
