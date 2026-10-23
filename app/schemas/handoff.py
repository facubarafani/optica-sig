from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HandoffCreated(BaseModel):
    id: int
    # What the QR says, so the PC can also offer it as a link.
    url: str
    qr_svg: str
    expires_at: datetime


class HandoffState(BaseModel):
    status: Literal["waiting", "received", "expired"]
    expires_at: datetime
