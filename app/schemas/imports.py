from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class TailDecision(BaseModel):
    kind: Literal["color", "supplier_number", "not_color"]
    # Colour names, existing or to be created; several for a bicolour.
    colors: list[str] = []


class CodeColorsOptions(BaseModel):
    """How the colour rides in the code, and what each tail means.

    Present only when the shop used the "Colores" step. Every tail in the file
    needs an answer, here or remembered from an earlier import; the preview
    refuses the batch otherwise.
    """

    separator: str = Field(min_length=1, max_length=4)
    max_words: int = Field(2, ge=1, le=3)
    decisions: dict[str, TailDecision] = {}


class ImportOptions(BaseModel):
    mapping: dict[str, str]
    # "es" -> 1.234,56 · "en" -> 1,234.56. Chosen, never guessed: with one
    # separator "1.500" is ambiguous and a wrong guess is a 1000x error.
    decimal_format: str = "es"
    create_missing: bool = True
    code_colors: CodeColorsOptions | None = None


class CodeColorsRequest(BaseModel):
    mapping: dict[str, str]
    # Omitted: the shop's remembered rule if it fits this file, else the best
    # detected one.
    separator: str | None = Field(None, min_length=1, max_length=4)
    max_words: int | None = Field(None, ge=1, le=3)


class SeparatorScoreRead(BaseModel):
    separator: str
    score: float


class CodeSplitRead(BaseModel):
    code: str
    stem: str
    tail: str


class CodeTailRead(BaseModel):
    phrase: str
    rows: int
    models: int
    examples: list[str]
    kind: str | None = None
    colors: list[str] = []
    # saved | catalog | synonyms | pattern, or partial: colours offered as a
    # hint with no kind, so the tail still needs an answer. None: nothing known.
    source: str | None = None


class ColorSwatchRead(BaseModel):
    name: str
    hex_code: str | None = None


class CodeColorsRead(BaseModel):
    separator: str | None
    max_words: int
    score: float
    likely: bool
    remembered: bool
    candidates: list[SeparatorScoreRead]
    examples: list[CodeSplitRead]
    tails: list[CodeTailRead]
    # The shop's colours, for the picker and the swatches.
    colors: list[ColorSwatchRead]
    rows_with_tail: int
    rows_without_tail: int


class RowErrorRead(BaseModel):
    row: int
    field: str | None = None
    message: str


class MissingRefRead(BaseModel):
    ref: str
    label: str
    name: str
    creatable: bool


class FamilyVariantRead(BaseModel):
    code: str
    colors: list[str] = []
    # file: a row of this file · moved: already in the catalogue, joins its
    # base · existing: already a variant of it.
    status: str


class FamilyRead(BaseModel):
    base: str
    new: bool
    variants: list[FamilyVariantRead]


class ImportPreviewRead(BaseModel):
    batch_id: int
    total: int
    to_create: int
    to_update: int
    errors: list[RowErrorRead]
    missing_refs: list[MissingRefRead]
    ok: bool
    family_count: int = 0
    families: list[FamilyRead] = []
    # "Activo" in a products file. The console asks for a swipe to confirm
    # whenever to_deactivate is not zero.
    to_deactivate: int = 0
    to_reactivate: int = 0
    deactivate_with_stock: int = 0
    deactivate_sample: list[str] = []


class ImportResultRead(BaseModel):
    batch_id: int
    created: int
    updated: int
    created_refs: dict[str, list[str]] = {}
