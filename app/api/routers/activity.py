"""Actividad: what the shop changed, and undo / redo of it (services.journal)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.auth import User
from app.models.journal import Operation
from app.schemas.activity import (
    OperationDetailRead,
    OperationRead,
    RevertRead,
    RevertRequest,
)
from app.services import journal

router = APIRouter(prefix="/activity", tags=["activity"])


def _visible(db: Session, operation_id: int, user: User) -> Operation:
    """Your own operations; everybody's for an admin. Otherwise it is a 404,
    not a 403, so ids of other people's work do not leak."""
    op = db.get(Operation, operation_id)
    if (op is None or op.company_id != user.company_id
            or (op.user_id != user.id and not journal.is_admin(user))):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operación no encontrada.")
    return op


def _originals(user: User, *, mine: bool):
    stmt = select(Operation).where(
        Operation.company_id == user.company_id, Operation.reverts_id.is_(None)
    )
    if mine or not journal.is_admin(user):
        stmt = stmt.where(Operation.user_id == user.id)
    return stmt


@router.get("", response_model=list[OperationRead])
def list_operations(
    mine: bool = False,
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    journal.purge(db, current_user.company_id)
    stmt = _originals(current_user, mine=mine)
    if before_id is not None:
        stmt = stmt.where(Operation.id < before_id)
    ops = db.execute(stmt.order_by(Operation.id.desc()).limit(limit)).scalars().all()
    return journal.summaries(db, ops, current_user)


@router.get("/latest", response_model=OperationRead | None)
def latest(
    action: Literal["undo", "redo"],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Your next Ctrl+Z (the newest change still in effect) or Ctrl+Shift+Z
    (the newest undo still in effect).

    ``null`` when there is none. Not a 404: the console's top bar asks after
    every save, and a browser logs each 404 as an error.
    """
    if action == "undo":
        ops = db.execute(_originals(current_user, mine=True)
                         .order_by(Operation.id.desc()).limit(50)).scalars()
        for op in ops:
            if not journal.is_undone(db, op) and journal.refusal(db, current_user, op) is None:
                return journal.summaries(db, [op], current_user)[0]
        return None

    undos = db.execute(
        select(Operation).where(
            Operation.company_id == current_user.company_id,
            Operation.user_id == current_user.id, Operation.reverts_id.is_not(None),
        ).order_by(Operation.id.desc()).limit(50)
    ).scalars()
    for undo in undos:
        target = db.get(Operation, undo.reverts_id)
        if (target is not None and target.reverts_id is None
                and target.reverted_by_id == undo.id and journal.is_undone(db, target)
                and journal.refusal(db, current_user, target) is None):
            return journal.summaries(db, [target], current_user)[0]
    return None


@router.get("/{operation_id}", response_model=OperationDetailRead)
def get_operation(
    operation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    op = _visible(db, operation_id, current_user)
    return journal.detail(db, op, current_user)


def _run(db: Session, op: Operation, target: Operation, user: User, dry_run: bool) -> dict:
    problem = journal.refusal(db, user, op)
    if problem:
        raise HTTPException(status.HTTP_403_FORBIDDEN, problem)
    label = op.label
    try:
        outcome = journal.revert(db, target, user=user, dry_run=dry_run)
    except journal.JournalError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {
        "applied": outcome.applied, "operation_id": outcome.operation_id,
        "skipped": [{"entity": s.entity, "reason": s.reason} for s in outcome.skipped],
        "label": label, "dry_run": outcome.dry_run,
    }


@router.post("/{operation_id}/undo", response_model=RevertRead)
def undo(
    operation_id: int,
    body: RevertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    op = _visible(db, operation_id, current_user)
    if op.reverts_id is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Esto ya es un deshacer o un rehacer: se maneja desde el cambio original.",
        )
    if journal.is_undone(db, op):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya está deshecho.")
    return _run(db, op, op, current_user, body.dry_run)


@router.post("/{operation_id}/redo", response_model=RevertRead)
def redo(
    operation_id: int,
    body: RevertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    op = _visible(db, operation_id, current_user)
    if op.reverts_id is not None or not journal.is_undone(db, op):
        raise HTTPException(status.HTTP_409_CONFLICT, "No está deshecho.")
    reverter = db.get(Operation, op.reverted_by_id)
    return _run(db, op, reverter, current_user, body.dry_run)
