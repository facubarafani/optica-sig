"""Factory that builds a standard company-scoped CRUD router for an entity.

Used for simple master-data tables (branches, suppliers, catalog, customers,
price categories/lists). Anything with business rules has a bespoke router.

NOTE: this module intentionally does *not* use ``from __future__ import
annotations`` — FastAPI must resolve the schema types at decoration time.
"""
from typing import Type

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission


def build_crud_router(
    *,
    prefix: str,
    tags: list[str],
    crud: CRUDBase,
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    permission: str,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=tags)
    read_perm = f"{permission}:read"
    write_perm = f"{permission}:write"

    @router.get("", response_model=list[read_schema])
    def list_items(
        skip: int = 0,
        limit: int = 100,
        include_inactive: bool = False,
        db: Session = Depends(get_db),
        company_id: int = Depends(get_company_id),
        _: object = Depends(require_permission(read_perm)),
    ):
        return crud.list(
            db,
            company_id=company_id,
            skip=skip,
            limit=limit,
            include_inactive=include_inactive,
        )

    @router.post("", response_model=read_schema, status_code=status.HTTP_201_CREATED)
    def create_item(
        data: create_schema,
        db: Session = Depends(get_db),
        company_id: int = Depends(get_company_id),
        _: object = Depends(require_permission(write_perm)),
    ):
        return crud.create(db, data, company_id=company_id)

    @router.get("/{item_id}", response_model=read_schema)
    def get_item(
        item_id: int,
        db: Session = Depends(get_db),
        company_id: int = Depends(get_company_id),
        _: object = Depends(require_permission(read_perm)),
    ):
        obj = crud.get(db, item_id, company_id=company_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        return obj

    @router.put("/{item_id}", response_model=read_schema)
    def update_item(
        item_id: int,
        data: update_schema,
        db: Session = Depends(get_db),
        company_id: int = Depends(get_company_id),
        _: object = Depends(require_permission(write_perm)),
    ):
        obj = crud.get(db, item_id, company_id=company_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        return crud.update(db, obj, data)

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(
        item_id: int,
        db: Session = Depends(get_db),
        company_id: int = Depends(get_company_id),
        _: object = Depends(require_permission(write_perm)),
    ):
        obj = crud.get(db, item_id, company_id=company_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        crud.remove(db, obj)
        return None

    return router
