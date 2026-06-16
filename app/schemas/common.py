"""Shared schema base classes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    """Read schemas inherit this to allow ORM-object serialization."""

    model_config = ConfigDict(from_attributes=True)


class TimestampedRead(ORMBase):
    id: int
    created_at: datetime
    updated_at: datetime


class SoftDeleteRead(TimestampedRead):
    is_active: bool
