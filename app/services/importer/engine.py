"""Import engine: map columns, validate into a preview, then apply atomically.

The two-phase shape is deliberate. ``analyze`` never writes; it reports exactly
what would happen (created / updated / failed, plus which catalog entries are
missing). ``commit`` then applies the whole batch in a single transaction —
either every row lands or none does.

Business rules are never bypassed: costs go through ``pricing.change_cost`` so
they reach ``cost_history``, and stock goes through ``stock.apply_movement`` so
a ``stock_movement`` row is written.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import PricingMode, StockMovementType
from app.models.pricing import PriceCategory
from app.models.product import Product
from app.schemas.stock import StockMovementCreate
from app.services import pricing as pricing_service
from app.services import stock as stock_service
from app.services.importer.readers import parse_decimal
from app.services.importer.specs import REFS, Field, ImportSpec


# --- helpers ---------------------------------------------------------------

def _norm(text: str) -> str:
    """Fold case, accents and surrounding space so "MARCA" == " Marca "."""
    s = unicodedata.normalize("NFKD", str(text or "").strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _category_code(text: str) -> str:
    """Category codes are stored and matched upper-cased ("ab" -> "AB")."""
    return str(text or "").strip().upper()


def suggest_mapping(spec: ImportSpec, headers: list[str]) -> dict[str, str]:
    """Guess {field_key: header} by matching the template labels and keys."""
    taken: set[str] = set()
    out: dict[str, str] = {}
    for f in spec.fields:
        candidates = {_norm(f.label), _norm(f.key)}
        for h in headers:
            if h and h not in taken and _norm(h) in candidates:
                out[f.key] = h
                taken.add(h)
                break
    return out


@dataclass
class RowError:
    row: int          # 1-based, as shown to the user (header is row 1)
    field: str | None
    message: str


@dataclass
class MissingRef:
    ref: str
    label: str
    name: str
    creatable: bool


@dataclass
class Preview:
    total: int = 0
    to_create: int = 0
    to_update: int = 0
    errors: list[RowError] = field(default_factory=list)
    missing_refs: list[MissingRef] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class ImportError_(Exception):
    """Raised when a batch cannot be applied."""


# --- parsing ---------------------------------------------------------------

class _Resolver:
    """Looks up referenced entities by name, case/accent-insensitively."""

    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
        self._cache: dict[str, dict[str, int]] = {}
        self.created: dict[str, dict[str, int]] = {}

    def _index(self, ref: str) -> dict[str, int]:
        if ref not in self._cache:
            model, _, _ = REFS[ref]
            # Products are referenced by code, everything else by name.
            attr = model.code if ref == "product" else model.name
            rows = self.db.execute(
                select(attr, model.id).where(model.company_id == self.company_id)
            ).all()
            self._cache[ref] = {_norm(r[0]): r[1] for r in rows}
        return self._cache[ref]

    def resolve(self, ref: str, name: str) -> int | None:
        return self._index(ref).get(_norm(name))

    def create(self, ref: str, name: str) -> int:
        model, _, _ = REFS[ref]
        obj = model(company_id=self.company_id, name=str(name).strip())
        self.db.add(obj)
        self.db.flush()
        self._index(ref)[_norm(name)] = obj.id
        self.created.setdefault(ref, {})[str(name).strip()] = obj.id
        return obj.id


def _cell(row: list, headers: list[str], header: str | None):
    if not header or header not in headers:
        return ""
    return row[headers.index(header)]


def _parse_row(
    spec: ImportSpec,
    row: list,
    headers: list[str],
    mapping: dict[str, str],
    *,
    decimal_format: str,
    row_no: int,
    errors: list[RowError],
) -> dict | None:
    """Turn one raw row into {field_key: python value}. None if unusable."""
    out: dict = {}
    failed = False
    for f in spec.fields:
        raw = _cell(row, headers, mapping.get(f.key))
        text = str(raw).strip()
        if not text:
            if f.required:
                errors.append(RowError(row_no, f.key, f'Falta "{f.label}".'))
                failed = True
            continue
        if f.kind == "decimal":
            try:
                out[f.key] = parse_decimal(raw, decimal_format=decimal_format)
            except ValueError as exc:
                errors.append(RowError(row_no, f.key, f"{f.label}: {exc}"))
                failed = True
        elif f.kind == "enum":
            if text not in (f.choices or []):
                errors.append(RowError(
                    row_no, f.key,
                    f'{f.label}: "{text}" no es válido '
                    f'(esperado: {", ".join(f.choices or [])}).'))
                failed = True
            else:
                out[f.key] = text
        else:
            out[f.key] = text
    return None if failed else out


def _collect(
    db: Session,
    spec: ImportSpec,
    headers: list[str],
    rows: list[list],
    mapping: dict[str, str],
    *,
    company_id: int,
    decimal_format: str,
) -> tuple[list[tuple[int, dict]], list[RowError], _Resolver]:
    """Parse every row and validate structure. No writes."""
    errors: list[RowError] = []
    parsed: list[tuple[int, dict]] = []

    missing_cols = [
        f.label for f in spec.fields if f.required and not mapping.get(f.key)
    ]
    if missing_cols:
        raise ImportError_(
            "Faltan columnas obligatorias sin asignar: " + ", ".join(missing_cols)
        )

    for i, row in enumerate(rows):
        row_no = i + 2          # +1 for the header, +1 for 1-based numbering
        values = _parse_row(
            spec, row, headers, mapping,
            decimal_format=decimal_format, row_no=row_no, errors=errors,
        )
        if values is not None:
            parsed.append((row_no, values))

    # Duplicate keys within the same file: the last one silently winning is
    # exactly the kind of surprise an import must not produce.
    dedupe_key = _dedupe_key(spec)
    if dedupe_key:
        seen: dict[tuple, int] = {}
        for row_no, values in parsed:
            k = tuple(_norm(str(values.get(f, ""))) for f in dedupe_key)
            if any(k):
                if k in seen:
                    errors.append(RowError(
                        row_no, dedupe_key[0],
                        f"Repetido en el archivo (ya está en la fila {seen[k]})."))
                else:
                    seen[k] = row_no

    return parsed, errors, _Resolver(db, company_id)


def _dedupe_key(spec: ImportSpec) -> list[str]:
    return {
        "products": ["code"],
        "costs": ["product"],
        "stock": ["product", "branch"],
        "price_list_items": ["price_list", "price_category"],
    }.get(spec.key, [])


# --- analyze ---------------------------------------------------------------

def analyze(
    db: Session,
    spec: ImportSpec,
    headers: list[str],
    rows: list[list],
    mapping: dict[str, str],
    *,
    company_id: int,
    decimal_format: str = "es",
) -> Preview:
    """Report what a commit would do. Never writes."""
    parsed, errors, resolver = _collect(
        db, spec, headers, rows, mapping,
        company_id=company_id, decimal_format=decimal_format,
    )
    preview = Preview(total=len(rows), errors=errors)

    missing: dict[tuple[str, str], MissingRef] = {}
    for row_no, values in parsed:
        for f in spec.fields:
            if f.kind != "ref" or f.key not in values:
                continue
            name = values[f.key]
            if resolver.resolve(f.ref, name) is None:
                if f.creatable:
                    missing.setdefault(
                        (f.ref, _norm(name)),
                        MissingRef(f.ref, REFS[f.ref][1], str(name), True),
                    )
                else:
                    errors.append(RowError(
                        row_no, f.key,
                        f'{f.label} "{name}" no existe. Creala primero.'))
    preview.missing_refs = list(missing.values())

    # Rows that already failed parsing are excluded — only rows that would
    # actually be applied are counted here.
    good = [(n, v) for n, v in parsed if n not in {e.row for e in errors}]

    if spec.key == "products":
        existing = {
            _norm(c) for c in db.execute(
                select(Product.code).where(Product.company_id == company_id)
            ).scalars()
        }
        for _, values in good:
            if _norm(values.get("code", "")) in existing:
                preview.to_update += 1
            else:
                preview.to_create += 1
    elif spec.key == "price_list_items":
        # A (list, code) pair the list already has is an update; anything else
        # gets appended to that list's ladder.
        existing_cats = {
            (r[0], r[1].strip().upper())
            for r in db.execute(
                select(PriceCategory.price_list_id, PriceCategory.code).where(
                    PriceCategory.company_id == company_id
                )
            ).all()
        }
        for _, values in good:
            list_id = resolver.resolve("price_list", values.get("price_list", ""))
            key = (list_id, _category_code(values.get("price_category", "")))
            if key in existing_cats:
                preview.to_update += 1
            else:
                preview.to_create += 1
    else:
        preview.to_update = len(good)

    preview.errors = errors
    return preview


# --- commit ----------------------------------------------------------------

def commit(
    db: Session,
    spec: ImportSpec,
    headers: list[str],
    rows: list[list],
    mapping: dict[str, str],
    *,
    company_id: int,
    user_id: int | None = None,
    decimal_format: str = "es",
    create_missing: bool = True,
) -> dict:
    """Apply the batch. All rows or none — the caller's transaction is rolled
    back on any error."""
    parsed, errors, resolver = _collect(
        db, spec, headers, rows, mapping,
        company_id=company_id, decimal_format=decimal_format,
    )
    if errors:
        raise ImportError_(
            f"El archivo tiene {len(errors)} fila(s) con errores. "
            "Corregilas y volvé a previsualizar."
        )

    # Resolve (and optionally create) every referenced entity up front.
    for row_no, values in parsed:
        for f in spec.fields:
            if f.kind != "ref" or f.key not in values:
                continue
            name = values[f.key]
            found = resolver.resolve(f.ref, name)
            if found is None:
                if f.creatable and create_missing:
                    found = resolver.create(f.ref, name)
                else:
                    raise ImportError_(
                        f'Fila {row_no}: {f.label} "{name}" no existe.'
                    )
            values[f.key] = found

    applier = {
        "products": _apply_products,
        "costs": _apply_costs,
        "stock": _apply_stock,
        "price_list_items": _apply_price_list_items,
    }[spec.key]
    result = applier(db, parsed, company_id=company_id, user_id=user_id)
    result["created_refs"] = {
        REFS[ref][1]: list(names) for ref, names in resolver.created.items()
    }
    db.commit()
    return result


def _apply_products(db, parsed, *, company_id, user_id) -> dict:
    by_code = {
        _norm(p.code): p
        for p in db.execute(
            select(Product).where(Product.company_id == company_id)
        ).scalars()
    }
    created = updated = 0
    for row_no, v in parsed:
        product = by_code.get(_norm(v["code"]))
        is_new = product is None
        if is_new:
            product = Product(company_id=company_id, code=v["code"],
                              product_type_id=v["product_type"])
            db.add(product)
            by_code[_norm(v["code"])] = product

        for src, dst in (
            ("description", "description"), ("color", "color"),
            ("product_type", "product_type_id"), ("brand", "brand_id"),
            ("model", "model_id"), ("supplier", "supplier_id"),
            ("min_stock", "min_stock"), ("sale_price", "sale_price"),
            ("price_list", "price_list_id"),
        ):
            if src in v:
                setattr(product, dst, v[src])
        if "price_category" in v:
            product.price_category_code = _category_code(v["price_category"])
        if "pricing_mode" in v:
            product.pricing_mode = PricingMode(v["pricing_mode"])

        if is_new:
            # A new product needs its cost set directly; there is no previous
            # value to historise.
            product.current_cost = v.get("current_cost", Decimal("0"))
            db.flush()
            created += 1
        else:
            if "current_cost" in v and Decimal(product.current_cost) != v["current_cost"]:
                pricing_service.change_cost(
                    db, product, v["current_cost"], user_id=user_id,
                    note="Importación masiva", commit=False,
                )
            updated += 1

        try:
            pricing_service.validate_pricing(db, product, company_id=company_id)
        except pricing_service.PricingError as exc:
            raise ImportError_(f"Fila {row_no}: {exc}")
    return {"created": created, "updated": updated}


def _apply_costs(db, parsed, *, company_id, user_id) -> dict:
    changed = 0
    for _row_no, v in parsed:
        product = db.get(Product, v["product"])
        if Decimal(product.current_cost) == v["new_cost"]:
            continue
        pricing_service.change_cost(
            db, product, v["new_cost"], user_id=user_id,
            note=v.get("note") or "Importación masiva", commit=False,
        )
        changed += 1
    return {"created": 0, "updated": changed}


def _apply_stock(db, parsed, *, company_id, user_id) -> dict:
    """Set each product's stock to the given quantity.

    An ADJUSTMENT with the delta needed to reach the target, not an INBOUND of
    the quantity: re-importing the same file must not double the stock.
    """
    changed = 0
    for _row_no, v in parsed:
        level = stock_service.get_level(
            db, company_id=company_id,
            product_id=v["product"], branch_id=v["branch"],
        )
        current = Decimal(level.quantity) if level else Decimal("0")
        delta = v["quantity"] - current
        if delta == 0:
            continue
        stock_service.apply_movement(
            db,
            StockMovementCreate(
                product_id=v["product"], branch_id=v["branch"],
                movement_type=StockMovementType.ADJUSTMENT, quantity=delta,
                reference="IMPORT", note="Importación de stock inicial",
            ),
            company_id=company_id, user_id=user_id,
            allow_negative=True, commit=False,
        )
        changed += 1
    return {"created": 0, "updated": changed}


def _apply_price_list_items(db, parsed, *, company_id, user_id) -> dict:
    """Upsert one category price inside a list, keyed by (list, code).

    Prices go through the pricing service so each change is audited, and a code
    the list does not have yet is appended to its ladder — that is what makes an
    exported list round-trip after being edited in Excel.
    """
    created = updated = 0
    for _row_no, v in parsed:
        code = _category_code(v["price_category"])
        cat = db.execute(
            select(PriceCategory).where(
                PriceCategory.company_id == company_id,
                PriceCategory.price_list_id == v["price_list"],
                func.upper(PriceCategory.code) == code,
            )
        ).scalar_one_or_none()
        if cat is None:
            cat = pricing_service.add_category(
                db,
                company_id=company_id,
                price_list_id=v["price_list"],
                code=code,
                description=v.get("description"),
                price=v["price"],
                commit=False,
            )
            created += 1
            continue
        if "description" in v:
            cat.description = v["description"]
            db.add(cat)
        if pricing_service.set_price(
            db, cat, v["price"], company_id=company_id, user_id=user_id
        ):
            updated += 1
    return {"created": created, "updated": updated}
