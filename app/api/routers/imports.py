"""Bulk import: upload -> map columns -> preview -> commit.

The upload is staged in ``import_batches`` so the preview and the confirmation
work on the same parsed data without re-uploading, and so there is a record of
what was imported.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_company_id, get_current_user, require_permission
from app.models.auth import User
from app.models.imports import ImportBatch
from app.schemas.imports import (
    ImportBatchRead,
    ImportFieldRead,
    ImportOptions,
    ImportPreviewRead,
    ImportResultRead,
    ImportSpecRead,
    ImportUploadRead,
)
from app.services.importer import engine, exporters, readers, templates
from app.services.importer.specs import SPECS, ImportSpec, get_spec

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _spec_or_404(spec_key: str) -> ImportSpec:
    spec = get_spec(spec_key)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown import '{spec_key}'")
    return spec


def _authorize(spec: ImportSpec, user: User) -> None:
    codes = user.permission_codes
    if "*" not in codes and spec.permission not in codes:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Missing required permission: {spec.permission}",
        )


def _authorize_read(spec: ImportSpec, user: User) -> None:
    """Exporting only needs the read half of the spec's permission."""
    needed = spec.permission.replace(":write", ":read")
    codes = user.permission_codes
    if "*" not in codes and needed not in codes:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Missing required permission: {needed}"
        )


def _spec_read(spec: ImportSpec) -> ImportSpecRead:
    return ImportSpecRead(
        key=spec.key,
        label=spec.label,
        description=spec.description,
        permission=spec.permission,
        fields=[
            ImportFieldRead(
                key=f.key, label=f.label, kind=f.kind, required=f.required,
                creatable=f.creatable, choices=f.choices, help=f.help,
            )
            for f in spec.fields
        ],
    )


@router.get("/specs", response_model=list[ImportSpecRead])
def list_specs(current_user: User = Depends(get_current_user)):
    """Import targets this user may use, with their columns (drives the UI)."""
    codes = current_user.permission_codes
    return [
        _spec_read(s)
        for s in SPECS.values()
        if "*" in codes or s.permission in codes
    ]


@router.get("/{spec_key}/template")
def download_template(
    spec_key: str,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(get_current_user),
):
    spec = _spec_or_404(spec_key)
    _authorize(spec, current_user)
    content = templates.build_template(db, spec, company_id=company_id)
    filename = f"plantilla-{spec.key}.xlsx"
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{spec_key}/upload", response_model=ImportUploadRead)
async def upload(
    spec_key: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(get_current_user),
):
    """Stage a file and suggest a column mapping. Nothing is written yet."""
    spec = _spec_or_404(spec_key)
    _authorize(spec, current_user)

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El archivo supera los {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    try:
        headers, rows = readers.read_table(file.filename or "", content)
    except readers.ReaderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    suggested = engine.suggest_mapping(spec, headers)
    batch = ImportBatch(
        company_id=company_id,
        spec_key=spec.key,
        filename=file.filename or "archivo",
        row_count=len(rows),
        headers=json.dumps(headers),
        rows=json.dumps(rows),
        mapping=json.dumps(suggested),
        created_by_user_id=current_user.id,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    return ImportUploadRead(
        batch_id=batch.id,
        spec_key=spec.key,
        filename=batch.filename,
        row_count=batch.row_count,
        headers=headers,
        suggested_mapping=suggested,
        sample_rows=rows[:5],
    )


def _load_batch(db: Session, batch_id: int, company_id: int) -> ImportBatch:
    batch = db.execute(
        select(ImportBatch).where(
            ImportBatch.id == batch_id, ImportBatch.company_id == company_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import batch not found")
    return batch


@router.post("/batches/{batch_id}/preview", response_model=ImportPreviewRead)
def preview(
    batch_id: int,
    options: ImportOptions,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(get_current_user),
):
    """Report exactly what a commit would do. Writes nothing."""
    batch = _load_batch(db, batch_id, company_id)
    spec = _spec_or_404(batch.spec_key)
    _authorize(spec, current_user)

    try:
        result = engine.analyze(
            db, spec,
            json.loads(batch.headers), json.loads(batch.rows), options.mapping,
            company_id=company_id, decimal_format=options.decimal_format,
        )
    except engine.ImportError_ as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    batch.mapping = json.dumps(options.mapping)
    db.commit()

    return ImportPreviewRead(
        batch_id=batch.id,
        total=result.total,
        to_create=result.to_create,
        to_update=result.to_update,
        errors=[e.__dict__ for e in result.errors],
        missing_refs=[m.__dict__ for m in result.missing_refs],
        ok=result.ok,
    )


@router.post("/batches/{batch_id}/commit", response_model=ImportResultRead)
def commit_batch(
    batch_id: int,
    options: ImportOptions,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(get_current_user),
):
    """Apply the batch — every row or none."""
    batch = _load_batch(db, batch_id, company_id)
    spec = _spec_or_404(batch.spec_key)
    _authorize(spec, current_user)
    if batch.status == "committed":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Este lote ya fue importado."
        )

    try:
        result = engine.commit(
            db, spec,
            json.loads(batch.headers), json.loads(batch.rows), options.mapping,
            company_id=company_id, user_id=current_user.id,
            decimal_format=options.decimal_format,
            create_missing=options.create_missing,
        )
    except engine.ImportError_ as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except Exception:
        db.rollback()
        raise

    batch.status = "committed"
    batch.mapping = json.dumps(options.mapping)
    batch.result = json.dumps(
        {k: v for k, v in result.items() if k != "created_refs"}
    )
    db.commit()

    return ImportResultRead(
        batch_id=batch.id,
        created=result.get("created", 0),
        updated=result.get("updated", 0),
        created_refs=result.get("created_refs", {}),
    )


@router.get("/{spec_key}/export", include_in_schema=True)
def export(
    spec_key: str,
    format: str = "xlsx",
    include_inactive: bool = False,
    product_type_id: int | None = None,
    brand_id: int | None = None,
    model_id: int | None = None,
    supplier_id: int | None = None,
    branch_id: int | None = None,
    price_list_id: int | None = None,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(get_current_user),
):
    """Export the current data using the *import* column layout.

    The file that comes out is a file this same endpoint's importer accepts, so
    "export → edit in Excel → re-import" round-trips.
    """
    spec = _spec_or_404(spec_key)
    _authorize_read(spec, current_user)
    try:
        rows = exporters.build_rows(
            db, spec, company_id=company_id,
            include_inactive=include_inactive,
            product_type_id=product_type_id, brand_id=brand_id,
            model_id=model_id, supplier_id=supplier_id,
            branch_id=branch_id, price_list_id=price_list_id,
        )
        content, media_type = exporters.render(spec, rows, format)
    except exporters.ExportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    filename = f"{spec.key}.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Row-Count": str(len(rows)),
        },
    )


@router.get("/batches", response_model=list[ImportBatchRead])
def list_batches(
    limit: int = 30,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    """History: what was imported, when and by whom."""
    return list(
        db.execute(
            select(ImportBatch)
            .where(ImportBatch.company_id == company_id)
            .order_by(ImportBatch.id.desc())
            .limit(limit)
        ).scalars()
    )
