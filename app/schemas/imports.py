from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ImportFieldRead(BaseModel):
    key: str
    label: str
    kind: str
    required: bool
    creatable: bool = False
    choices: list[str] | None = None
    help: str | None = None


class ImportSpecRead(BaseModel):
    key: str
    label: str
    description: str
    permission: str
    fields: list[ImportFieldRead]


class ImportBatchRead(BaseModel):
    id: int
    spec_key: str
    filename: str
    status: str
    row_count: int
    created_at: datetime
    created_by_user_id: int | None = None


class ImportUploadRead(BaseModel):
    """What the mapping step needs after a file is uploaded."""

    batch_id: int
    spec_key: str
    filename: str
    row_count: int
    headers: list[str]
    suggested_mapping: dict[str, str]
    sample_rows: list[list]


class ImportOptions(BaseModel):
    mapping: dict[str, str]
    # "es" -> 1.234,56 · "en" -> 1,234.56. Chosen, never guessed: with one
    # separator "1.500" is ambiguous and a wrong guess is a 1000x error.
    decimal_format: str = "es"
    create_missing: bool = True


class RowErrorRead(BaseModel):
    row: int
    field: str | None = None
    message: str


class MissingRefRead(BaseModel):
    ref: str
    label: str
    name: str
    creatable: bool


class ImportPreviewRead(BaseModel):
    batch_id: int
    total: int
    to_create: int
    to_update: int
    errors: list[RowErrorRead]
    missing_refs: list[MissingRefRead]
    ok: bool


class ImportResultRead(BaseModel):
    batch_id: int
    created: int
    updated: int
    created_refs: dict[str, list[str]] = {}
