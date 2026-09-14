"""Operation journal: one row per undoable request, one per row it changed.

How rows get here and how they are replayed lives in services/journal.py.
Snapshots are JSON in ``Text``, not JSONB, so the schema stays portable to the
SQLite test suite (CLAUDE.md).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin
from app.models.enums import ChangeAction


class Operation(IDMixin, CompanyMixin, Base):
    """One write request by a shop user, as the shop reads it: "Cambios en
    producto ARM-001", "Importación de lista.xlsx".

    Undo and redo are operations too. ``reverts_id`` points at what one
    reverses; ``reverted_by_id`` at the latest operation that reversed this one.
    An operation is undone when its reverter is itself still in effect, so a
    redo is simply the undo being reverted.
    """

    __tablename__ = "operations"

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # First path segment of the request ("products", "imports"): which screen
    # it came from, and which write permission undoing it needs.
    area: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    change_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    reverts_id: Mapped[int | None] = mapped_column(
        ForeignKey("operations.id", ondelete="SET NULL")
    )
    reverted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("operations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class OperationChange(IDMixin, Base):
    """One row's columns before and after. No company_id: its operation has it."""

    __tablename__ = "operation_changes"

    operation_id: Mapped[int] = mapped_column(
        ForeignKey("operations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Order within the operation: undo walks it backwards.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)  # table
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[ChangeAction] = mapped_column(
        SAEnum(ChangeAction, name="change_action"), nullable=False
    )
    before: Mapped[str | None] = mapped_column(Text)   # JSON {column: value}
    after: Mapped[str | None] = mapped_column(Text)    # JSON {column: value}
