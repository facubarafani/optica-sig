"""Bulk import batches.

An upload is staged as a row here so the preview and the confirmation are two
separate requests over the same parsed data (no re-upload), and so there is a
history of what was imported, when and by whom.

``mapping`` and ``rows`` hold JSON in a plain ``Text`` column rather than JSONB:
the test suite runs on SQLite, so the schema must stay portable (CLAUDE.md).
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, TimestampMixin


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
