"""A photo taken on a phone for a form open on the PC (the receta scanner)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin


class PhotoHandoff(IDMixin, CompanyMixin, Base):
    """One photo on its way from a phone to the PC that asked for it.

    The PC creates the row and shows its link as a QR; the phone opens the
    link with no login and uploads one photo; the PC fetches it and deletes
    the row. A receta is health data, so a row lives minutes, not months: see
    services/handoffs.py.
    """

    __tablename__ = "photo_handoffs"

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # SHA-256 of the token in the QR. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    photo: Mapped[bytes | None] = mapped_column(LargeBinary)
    photo_type: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Until when the phone may upload. The photo itself goes sooner: the PC
    # deletes the row as soon as it has it.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
