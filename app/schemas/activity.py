from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OperationRead(BaseModel):
    id: int
    label: str
    area: str
    area_label: str
    user_id: int | None = None
    user_name: str | None = None
    created_at: datetime
    change_count: int
    import_batch_id: int | None = None
    undone: bool
    can_undo: bool
    can_redo: bool
    # Why neither button applies (not yours, older than 90 days...).
    blocked_reason: str | None = None


class FieldChangeRead(BaseModel):
    field: str
    label: str
    before: str | None = None
    after: str | None = None


class EntityChangeRead(BaseModel):
    entity_type: str
    entity_id: int
    noun: str
    name: str
    # create | update | deactivate | reactivate
    action: str
    fields: list[FieldChangeRead] = []


class OperationDetailRead(OperationRead):
    entity_count: int
    entities: list[EntityChangeRead]


class RevertRequest(BaseModel):
    # True: run it and roll back, to show what confirming would do.
    dry_run: bool = False


class SkipRead(BaseModel):
    entity: str
    reason: str


class RevertRead(BaseModel):
    applied: int
    skipped: list[SkipRead]
    operation_id: int | None = None
    label: str
    dry_run: bool
