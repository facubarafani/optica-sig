"""Generic CRUD base for simple master-data entities.

Anything with real business rules (stock, auth, numbering) uses a dedicated
service instead. This handles the repetitive list/get/create/update/soft-delete
plumbing while always scoping by company and honouring soft deletes.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)
CreateT = TypeVar("CreateT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)


class CRUDBase(Generic[ModelT, CreateT, UpdateT]):
    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    # -- helpers -----------------------------------------------------------
    @property
    def _has_company(self) -> bool:
        return hasattr(self.model, "company_id")

    @property
    def _has_soft_delete(self) -> bool:
        return hasattr(self.model, "is_active")

    def _scoped(self, stmt, company_id: int | None, include_inactive: bool):
        if self._has_company and company_id is not None:
            stmt = stmt.where(self.model.company_id == company_id)
        if self._has_soft_delete and not include_inactive:
            stmt = stmt.where(self.model.is_active.is_(True))
        return stmt

    # -- reads -------------------------------------------------------------
    def get(
        self, db: Session, obj_id: int, *, company_id: int | None = None
    ) -> ModelT | None:
        stmt = select(self.model).where(self.model.id == obj_id)
        stmt = self._scoped(stmt, company_id, include_inactive=True)
        return db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        db: Session,
        *,
        company_id: int | None = None,
        skip: int = 0,
        limit: int = 100,
        include_inactive: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[ModelT]:
        stmt = select(self.model)
        stmt = self._scoped(stmt, company_id, include_inactive)
        for field, value in (filters or {}).items():
            if value is not None and hasattr(self.model, field):
                stmt = stmt.where(getattr(self.model, field) == value)
        stmt = stmt.order_by(self.model.id).offset(skip).limit(limit)
        return list(db.execute(stmt).scalars().all())

    # -- writes ------------------------------------------------------------
    def create(
        self, db: Session, data: CreateT, *, company_id: int | None = None
    ) -> ModelT:
        payload = data.model_dump(exclude_unset=True)
        if self._has_company and company_id is not None:
            payload.setdefault("company_id", company_id)
        obj = self.model(**payload)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, obj: ModelT, data: UpdateT) -> ModelT:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def remove(self, db: Session, obj: ModelT) -> ModelT:
        """Soft delete when supported, otherwise physical delete."""
        if self._has_soft_delete:
            obj.is_active = False
            db.add(obj)
        else:
            db.delete(obj)
        db.commit()
        return obj
