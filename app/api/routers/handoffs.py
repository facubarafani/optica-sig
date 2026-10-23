"""Phone handoff: the PC asks for a photo, the phone sends it.

Every route needs a shop login except ``POST /upload``, which the phone calls
with the token from the QR instead. With forgot-password and set-password it
is one of the only writes anyone can make without credentials, so it is rate
limited the same way.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core import ratelimit
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.handoff import PhotoHandoff
from app.schemas.handoff import HandoffCreated, HandoffState
from app.services import handoffs

router = APIRouter(prefix="/handoffs", tags=["handoffs"])

_STATUS = {
    "unknown": status.HTTP_404_NOT_FOUND,
    "used": status.HTTP_409_CONFLICT,
    "expired": status.HTTP_410_GONE,
    "suspended": status.HTTP_403_FORBIDDEN,
    "too_big": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "not_photo": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}


def _get(db: Session, company_id: int, handoff_id: int) -> PhotoHandoff:
    row = handoffs.get(db, company_id, handoff_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Handoff not found")
    return row


@router.post("", response_model=HandoffCreated, status_code=status.HTTP_201_CREATED)
def create_handoff(
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("customers:write")),
):
    row, raw = handoffs.create(db, company_id=company_id, user_id=current_user.id)
    url = handoffs.phone_url(raw)
    return HandoffCreated(
        id=row.id, url=url, qr_svg=handoffs.qr_svg(url), expires_at=row.expires_at
    )


@router.get("/{handoff_id}", response_model=HandoffState)
def handoff_state(
    handoff_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:write")),
):
    row = _get(db, company_id, handoff_id)
    return HandoffState(status=handoffs.state(row), expires_at=row.expires_at)


@router.get("/{handoff_id}/photo")
def handoff_photo(
    handoff_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:write")),
):
    row = _get(db, company_id, handoff_id)
    if row.photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todavía no llegó la foto.")
    return Response(
        content=row.photo, media_type=row.photo_type,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/{handoff_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_handoff(
    handoff_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("customers:write")),
):
    """The PC has the photo, or gave up on it. Gone either way, and asking
    twice is fine: a closing modal and a finished fetch can both call this."""
    row = handoffs.get(db, company_id, handoff_id)
    if row is not None:
        handoffs.discard(db, row)
    return None


@router.post("/upload")
async def upload_photo(request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    """The phone's photo, sent with the token from the QR (multipart fields
    ``token`` and ``photo``).

    Async and parsed by hand, unlike every other route, so an oversized body
    is refused from its declared length before anything is read: this is the
    one upload anyone can make without logging in.
    """
    ratelimit.enforce(
        f"handoff-upload:{ratelimit.client_ip(request)}", limit=20, window_seconds=600,
        detail="Demasiados intentos. Esperá unos minutos y probá de nuevo.",
    )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > handoffs.MAX_PHOTO_BYTES + 64_000:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "La foto es muy pesada. Probá sacarla de nuevo.",
        )
    form = await request.form(max_files=1, max_fields=2)
    try:
        token, photo = form.get("token"), form.get("photo")
        if not isinstance(token, str) or not isinstance(photo, UploadFile):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Falta la foto o el código.")
        data = await photo.read(handoffs.MAX_PHOTO_BYTES + 1)
    finally:
        await form.close()
    try:
        await run_in_threadpool(handoffs.receive, db, token, data)
    except handoffs.HandoffError as exc:
        raise HTTPException(_STATUS[exc.kind], str(exc)) from exc
    return {"ok": True}
