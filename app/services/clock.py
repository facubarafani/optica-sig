"""The shop's calendar: what day it is, and where a day starts, in its zone.

The server runs on UTC (Render does), three hours ahead of Argentina, so
``date.today()`` there turns into tomorrow at 21:00 local time: a payment
promised for today shows as overdue all evening, and a sale rung up at 22:00
lands on the next day's report. Anything that asks "today?" or filters by
calendar day goes through here instead, with the zone chosen in
``company_settings.timezone``.

Timestamps stay stored in UTC; only the day boundaries move.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import CompanySettings

DEFAULT_TIMEZONE = "America/Argentina/Buenos_Aires"
# Argentina has no daylight saving, so a fixed offset is exact for it: the last
# resort if the host has no timezone database at all.
_ARGENTINA = timezone(timedelta(hours=-3), "ART")


def is_valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def zone(name: str | None) -> tzinfo:
    """The zone called ``name``, falling back to Buenos Aires. Never raises: a
    bad setting must not take the sales screens down with it."""
    for candidate in (name, DEFAULT_TIMEZONE):
        if candidate and is_valid_zone(candidate):
            return ZoneInfo(candidate)
    return _ARGENTINA


def company_zone(db: Session, company_id: int) -> tzinfo:
    name = db.execute(
        select(CompanySettings.timezone).where(CompanySettings.company_id == company_id)
    ).scalar()
    return zone(name)


def _now() -> datetime:
    """The one place the clock is read, so tests can stop it."""
    return datetime.now(timezone.utc)


def today(db: Session, company_id: int) -> date:
    """The shop's date right now."""
    return _now().astimezone(company_zone(db, company_id)).date()


def day_start(day: date, tz: tzinfo) -> datetime:
    """Midnight at the start of ``day`` in ``tz``, as a UTC instant, ready to
    compare with a stored timestamp."""
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
