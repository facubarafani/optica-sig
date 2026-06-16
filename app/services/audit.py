"""Change-history recording for critical fields (price, cost, category, stock)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import ChangeHistory


def _as_str(value: Any) -> str | None:
    return None if value is None else str(value)


def record_change(
    db: Session,
    *,
    company_id: int,
    entity_type: str,
    entity_id: int,
    field_name: str,
    old_value: Any,
    new_value: Any,
    user_id: int | None = None,
    commit: bool = False,
) -> ChangeHistory:
    """Append a change-history row. Caller usually commits as part of a unit of
    work, so ``commit`` defaults to False."""
    entry = ChangeHistory(
        company_id=company_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        old_value=_as_str(old_value),
        new_value=_as_str(new_value),
        changed_by_user_id=user_id,
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


def list_changes(
    db: Session,
    *,
    company_id: int,
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 100,
) -> list[ChangeHistory]:
    stmt = select(ChangeHistory).where(ChangeHistory.company_id == company_id)
    if entity_type is not None:
        stmt = stmt.where(ChangeHistory.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(ChangeHistory.entity_id == entity_id)
    stmt = stmt.order_by(ChangeHistory.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())
