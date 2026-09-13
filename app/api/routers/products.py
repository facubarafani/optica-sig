from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import search
from app.core.crud import CRUDBase
from app.core.database import get_db
from app.core.deps import get_company_id, require_permission
from app.models.auth import User
from app.models.product import Color, Product
from app.schemas.pricing import CostHistoryRead
from app.schemas.product import (
    CostUpdate,
    ProductCreate,
    ProductPriceRead,
    ProductRead,
    ProductUpdate,
    VariantsCreate,
)
from app.services import pricing as pricing_service
from app.services import products as products_service

router = APIRouter(prefix="/products", tags=["products"])
crud = CRUDBase(Product)


def _decorate(db: Session, products: list[Product], company_id: int) -> list[dict]:
    """Attach the resolved price and the family facts to each product.

    Both are batched — one extra query for the whole page rather than one per
    row — because a products grid is the one place where an N+1 is felt.
    """
    resolved = pricing_service.resolve_prices(db, products, company_id=company_id)
    counts = products_service.variant_counts(db, [p.id for p in products])
    parent_codes = _parent_codes(db, products, company_id)
    out = []
    for p in products:
        data = ProductRead.model_validate(p, from_attributes=True).model_dump()
        r = resolved[p.id]
        data["resolved_sale_price"] = r.price
        data["price_source"] = r.source
        data["price_reason"] = r.reason
        data["price_currency"] = r.currency
        data["variant_count"] = counts.get(p.id, 0)
        data["parent_code"] = parent_codes.get(p.parent_id)
        out.append(data)
    return out


def _parent_codes(
    db: Session, products: list[Product], company_id: int
) -> dict[int, str]:
    """{id: code} for the styles the page's variants belong to."""
    ids = {p.parent_id for p in products if p.parent_id}
    if not ids:
        return {}
    rows = db.execute(
        select(Product.id, Product.code).where(
            Product.id.in_(ids), Product.company_id == company_id
        )
    ).all()
    return {pid: code for pid, code in rows}


def _get(db: Session, product_id: int, company_id: int) -> Product:
    obj = crud.get(db, product_id, company_id=company_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return obj


@router.get("", response_model=list[ProductRead])
def list_products(
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
    product_type_id: int | None = None,
    brand_id: int | None = None,
    model_id: int | None = None,
    supplier_id: int | None = None,
    color_id: int | None = None,
    parent_id: int | None = None,
    only_base: bool = False,
    sellable_only: bool = False,
    q: str | None = None,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    """``q`` matches the code or the description, ignoring case and accents.

    Three family filters, because a products grid and a sales picker want
    different slices of the same table:

    * ``parent_id`` — the variants of one style.
    * ``only_base`` — styles and plain articles, hiding the variants that hang
      off them; what the Products grid lists so a family reads as one line.
    * ``sellable_only`` — everything that can actually go on a sale: variants
      and plain articles, never a style.
    """
    term = search.matches(q, Product.code, Product.description)
    where = [term] if term is not None else []
    if parent_id is not None:
        where.append(Product.parent_id == parent_id)
    if only_base:
        where.append(Product.parent_id.is_(None))
    if sellable_only:
        # A style is a row that has at least one live variant.
        where.append(~Product.variants.any(Product.is_active.is_(True)))
    # "Has this colour", not "is this colour": the link is N-N, so it is an
    # EXISTS rather than the plain equality `filters` can express.
    if color_id is not None:
        where.append(Product.colors.any(Color.id == color_id))
    products = crud.list(
        db,
        company_id=company_id,
        skip=skip,
        limit=limit,
        include_inactive=include_inactive,
        filters={
            "product_type_id": product_type_id,
            "brand_id": brand_id,
            "model_id": model_id,
            "supplier_id": supplier_id,
        },
        extra_where=where or None,
    )
    return _decorate(db, products, company_id)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("products:write")),
):
    payload = data.model_dump(exclude_unset=True)
    # Not a column: the colours are a relationship, set once the row exists.
    color_ids = payload.pop("color_ids", None)
    obj = Product(**payload, company_id=company_id)
    try:
        products_service.assert_valid_parent(
            db, None, obj.parent_id, company_id=company_id
        )
        products_service.set_colors(db, obj, color_ids, company_id=company_id)
        pricing_service.validate_pricing(db, obj, company_id=company_id)
        db.add(obj)
        db.flush()
        # More than one colour means more than one article: the colours ticked
        # here *are* the variants, so they are made now rather than in a second
        # step somebody has to remember.
        products_service.sync_variants(
            db, obj, company_id=company_id, user_id=current_user.id,
            previous_color_ids=[],
        )
    except products_service.ProductError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except pricing_service.PricingError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.commit()
    db.refresh(obj)
    return _decorate(db, [obj], company_id)[0]


@router.get("/{product_id}", response_model=ProductRead)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    return _decorate(db, [_get(db, product_id, company_id)], company_id)[0]


@router.get("/{product_id}/price", response_model=ProductPriceRead)
def get_product_price(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    """Explain where this product's selling price comes from."""
    obj = _get(db, product_id, company_id)
    r = pricing_service.resolve_price(db, obj, company_id=company_id)
    return ProductPriceRead(
        product_id=obj.id,
        price=r.price,
        source=r.source,
        price_list_id=r.price_list_id,
        currency=r.currency,
        reason=r.reason,
    )


@router.put("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("products:write")),
):
    obj = _get(db, product_id, company_id)
    payload = data.model_dump(exclude_unset=True)
    # Absent = leave the colours as they are; [] = clear them.
    color_ids = payload.pop("color_ids", None)
    # Captured before the write: once the new set is on the row, nothing else
    # knows which colour the stock on the shelf actually is.
    previous_color_ids = list(obj.color_ids)
    # Pricing fields are split out so each change is audited.
    pricing_payload = {
        k: payload.pop(k)
        for k in list(payload)
        if k in ("pricing_mode", "sale_price", "price_list_id", "price_category_code")
    }
    for field, value in payload.items():
        setattr(obj, field, value)
    try:
        if "parent_id" in payload:
            products_service.assert_valid_parent(
                db, obj, obj.parent_id, company_id=company_id
            )
        if color_ids is not None or "multicolor" in payload:
            if color_ids is not None:
                products_service.set_colors(db, obj, color_ids, company_id=company_id)
            db.flush()
            # Flipping "multicolor" changes what the same colours mean, so it
            # re-runs the split exactly as a colour change does.
            products_service.sync_variants(
                db, obj, company_id=company_id, user_id=current_user.id,
                previous_color_ids=previous_color_ids,
            )
    except products_service.ProductError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if pricing_payload:
        pricing_service.apply_pricing_update(
            db, obj, pricing_payload, user_id=current_user.id
        )
    try:
        pricing_service.validate_pricing(db, obj, company_id=company_id)
    except pricing_service.PricingError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _decorate(db, [obj], company_id)[0]


@router.get("/{product_id}/variants", response_model=list[ProductRead])
def list_variants(
    product_id: int,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    """The colours this style is stocked in."""
    _get(db, product_id, company_id)
    variants = crud.list(
        db, company_id=company_id, limit=500,
        include_inactive=include_inactive,
        filters={"parent_id": product_id},
        # Code order, matching Product.variants — a family reads as a list of
        # colours, not as the order somebody happened to add them.
        order_by=Product.code,
    )
    return _decorate(db, variants, company_id)


@router.post(
    "/{product_id}/variants",
    response_model=list[ProductRead],
    status_code=status.HTTP_201_CREATED,
)
def create_variants(
    product_id: int,
    data: VariantsCreate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    """Turn a style into one article per colour.

    Each variant inherits the style's type, brand, model, supplier, pricing and
    cost — it is the same article in another colour — and gets its own code
    (ARM-001 + HAV -> ARM-001-HAV) and its own stock.

    The whole batch is one transaction: a code clash on the last colour leaves
    no half-generated family behind.
    """
    parent = _get(db, product_id, company_id)
    try:
        products_service.assert_stock_free(db, parent, company_id=company_id)
        created = products_service.create_variants(
            db, parent, data.specs(), company_id=company_id
        )
    except products_service.ProductError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.commit()
    for v in created:
        db.refresh(v)
    return _decorate(db, created, company_id)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:write")),
):
    obj = _get(db, product_id, company_id)
    crud.remove(db, obj)
    return None


@router.post("/{product_id}/cost", response_model=ProductRead)
def change_cost(
    product_id: int,
    data: CostUpdate,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    current_user: User = Depends(require_permission("products:write")),
):
    """Change a product's cost (audited + recorded in cost_history)."""
    obj = _get(db, product_id, company_id)
    try:
        obj = pricing_service.change_cost(
            db, obj, data.new_cost, user_id=current_user.id, note=data.note
        )
    except pricing_service.PricingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return _decorate(db, [obj], company_id)[0]


@router.get("/{product_id}/cost-history", response_model=list[CostHistoryRead])
def cost_history(
    product_id: int,
    db: Session = Depends(get_db),
    company_id: int = Depends(get_company_id),
    _: object = Depends(require_permission("products:read")),
):
    return pricing_service.list_cost_history(
        db, company_id=company_id, product_id=product_id
    )
