"""Phone handoff: a photo taken on the phone lands on the form open on the PC.

The receta scanner is the one user today. The PC asks for a handoff and shows
its link as a QR; the phone opens it with no login (the token is the
credential), takes the photo and uploads it; the PC fetches it and deletes the
row. Nothing reads the photo for the seller: they type the receta looking at
it, which keeps the feature free to run.

What this file is responsible for, because a receta is health data:

- **The token is never stored**, only its SHA-256, like invitation links.
- **It works once, for TTL_MINUTES.** A second upload is refused.
- **The photo is gone in minutes.** The PC deletes the row as soon as it has
  the photo. A row left behind (a closed tab, a crash) is never served once it
  is RETENTION_MINUTES old, and the app deletes it at startup and every
  SWEEP_MINUTES (``sweep_forever``), not only when someone asks for a QR.
- **An upload proves it is a photo** by its first bytes, never by the type the
  phone claims.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import segno
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.handoff import PhotoHandoff

logger = logging.getLogger("app.handoffs")

TOKEN_BYTES = 32
TTL_MINUTES = 10
RETENTION_MINUTES = 30
SWEEP_MINUTES = 5
# A phone photo shrunk by the page is a few hundred KB; this leaves room for a
# browser that sends the original.
MAX_PHOTO_BYTES = 8 * 1024 * 1024


class HandoffError(Exception):
    """An upload the phone cannot make. ``kind`` says why, for the router."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; they are UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _sniff(data: bytes) -> str | None:
    """The media type, read from the first bytes of what a phone can send."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def create(db: Session, *, company_id: int, user_id: int) -> tuple[PhotoHandoff, str]:
    """A new handoff and its raw token, which goes in the QR and nowhere else."""
    sweep(db)
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    row = PhotoHandoff(
        company_id=company_id,
        created_by_user_id=user_id,
        token_hash=_hash(raw),
        expires_at=_now() + timedelta(minutes=TTL_MINUTES),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def get(db: Session, company_id: int, handoff_id: int) -> PhotoHandoff | None:
    return db.execute(
        select(PhotoHandoff).where(
            PhotoHandoff.id == handoff_id, PhotoHandoff.company_id == company_id
        )
    ).scalar_one_or_none()


def past_retention(row: PhotoHandoff) -> bool:
    return _aware(row.created_at) < _now() - timedelta(minutes=RETENTION_MINUTES)


def state(row: PhotoHandoff) -> str:
    """waiting, received or expired. A photo that arrived in time stays
    fetchable after the upload window closes, until the PC deletes it or it
    is RETENTION_MINUTES old, whichever comes first."""
    if past_retention(row):
        return "expired"
    if row.received_at is not None:
        return "received"
    if _aware(row.expires_at) < _now():
        return "expired"
    return "waiting"


def receive(db: Session, raw_token: str, data: bytes) -> PhotoHandoff:
    """Store the phone's photo on the handoff its token opens, or raise."""
    row = db.execute(
        select(PhotoHandoff).where(PhotoHandoff.token_hash == _hash(raw_token or ""))
    ).scalar_one_or_none()
    if row is None:
        raise HandoffError("unknown", "Este código no sirve. Generá otro en la compu.")
    if row.received_at is not None:
        raise HandoffError(
            "used", "Este código ya se usó. Para mandar otra foto, generá otro en la compu."
        )
    if _aware(row.expires_at) < _now():
        raise HandoffError("expired", "El código venció. Generá otro en la compu.")
    company = db.get(Company, row.company_id)
    if company is None or not company.is_active:
        raise HandoffError("suspended", "La cuenta está suspendida. Contactá a soporte.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HandoffError("too_big", "La foto es muy pesada. Probá sacarla de nuevo.")
    kind = _sniff(data)
    if kind is None:
        raise HandoffError("not_photo", "Eso no parece una foto. Probá sacarla de nuevo.")
    # Only if nobody got there first: two phones (or one retrying) sending at
    # once must not both succeed, each overwriting the other's photo.
    done = db.execute(
        update(PhotoHandoff)
        .where(PhotoHandoff.id == row.id, PhotoHandoff.received_at.is_(None))
        .values(photo=data, photo_type=kind, received_at=_now())
    )
    if done.rowcount != 1:
        db.rollback()
        raise HandoffError(
            "used", "Este código ya se usó. Para mandar otra foto, generá otro en la compu."
        )
    db.commit()
    db.refresh(row)
    return row


def discard(db: Session, row: PhotoHandoff) -> None:
    db.delete(row)
    db.commit()


def sweep(db: Session) -> None:
    """Drop every handoff older than RETENTION_MINUTES, whatever the shop.

    The one statement here not scoped to a company. It reads nothing; it only
    deletes photos past their time, and doing it shop by shop would leave a
    photo behind in a shop that never scans again. The caller commits.
    """
    cutoff = _now() - timedelta(minutes=RETENTION_MINUTES)
    db.execute(delete(PhotoHandoff).where(PhotoHandoff.created_at < cutoff))


def sweep_once(session_factory=SessionLocal) -> None:
    db = session_factory()
    try:
        sweep(db)
        db.commit()
    finally:
        db.close()


async def sweep_forever() -> None:
    """Sweep at startup and every SWEEP_MINUTES while the app runs, so a
    left-behind photo does not wait for the next QR anyone asks for. While the
    instance sleeps nothing runs; startup catches up when it wakes."""
    while True:
        try:
            await asyncio.to_thread(sweep_once)
        except Exception:  # one failed sweep must not stop the next ones
            logger.exception("Photo handoff sweep failed")
        await asyncio.sleep(SWEEP_MINUTES * 60)


def phone_url(raw_token: str) -> str:
    """Where the QR points. The token rides in the fragment, which the phone's
    browser never sends to the server, so it stays out of access logs.

    On a developer's machine the public URL is localhost, which a phone cannot
    reach, so the machine's own address on the Wi-Fi stands in for it (the
    server has to listen on it: ``uvicorn ... --host 0.0.0.0``).
    """
    base = settings.public_base_url.rstrip("/")
    if settings.environment == "local":
        base = _reachable_from_lan(base)
    return f"{base}/foto#{quote(raw_token)}"


def _reachable_from_lan(base: str) -> str:
    parts = urlsplit(base)
    if parts.hostname not in ("localhost", "127.0.0.1"):
        return base
    ip = _lan_ip()
    if ip is None:
        return base
    netloc = f"{ip}:{parts.port}" if parts.port else ip
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _lan_ip() -> str | None:
    # Connecting a UDP socket sends nothing: it only makes the OS choose the
    # interface it would route through, whose address the phone can reach.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def qr_svg(url: str) -> str:
    """The QR as inline SVG, drawn here because the console loads nothing from
    outside. No fixed size (a viewBox instead), so CSS decides how big."""
    return segno.make(url, error="m").svg_inline(dark="#0f172a", border=2, omitsize=True)
