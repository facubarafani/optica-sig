from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel

from app.models.enums import HandoffStatus


class HandoffCreated(BaseModel):
    id: int
    # What the QR says, so the PC can also offer it as a link.
    url: str
    qr_svg: str
    expires_at: datetime


class HandoffState(BaseModel):
    status: HandoffStatus
    expires_at: datetime
