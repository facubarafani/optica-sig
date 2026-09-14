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
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import PricingMode, StockMovementType
from app.models.pricing import PriceCategory
from app.models.product import Product
from app.models.stock import StockLevel
from app.schemas.stock import StockMovementCreate
from app.services import pricing as pricing_service
from app.services import products as products_service
from app.services import stock as stock_service
from app.services.importer import code_colors as code_colors_service
from app.services.importer.readers import parse_decimal
from app.services.importer.specs import REFS, Field, ImportSpec


# --- helpers ---------------------------------------------------------------

def _norm(text: str) -> str:
    """Fold case, accents and surrounding space so "MARCA" == " Marca "."""
    s = unicodedata.normalize("NFKD", str(text or "").strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _split_multi(text: str) -> list[str]:
    """Split a multi-value cell ("Negro, Havana") into distinct names.

    Comma-separated because that is what a person types and what the exporter
    writes; repeats are folded so "Negro, negro" is one colour, not two.
    """
    out: list[str] = []
    seen: set[str] = set()
    for part in str(text or "").split(","):
        name = part.strip()
        if name and _norm(name) not in seen:
            seen.add(_norm(name))
            out.append(name)
    return out


# What a person types in a yes/no column. Anything else is an error, not a no.
_BOOL = {
    "si": True, "s": True, "yes": True, "y": True, "true": True, "x": True,
    "1": True, "1.0": True,
    "no": False, "n": False, "false": False, "0": False, "0.0": False,
}


def _ref_names(field: Field, value) -> list[str]:
    """The names one ref cell points at — one, or several when ``multi``."""
    return list(value) if field.multi else [value]


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
    # Families read out of the codes (code_colors.plan), for the review step.
    families: list[dict] = field(default_factory=list)
    # "Activo" in a products file: what the confirmation must spell out.
    to_deactivate: int = 0
    to_reactivate: int = 0
    deactivate_with_stock: int = 0
    deactivate_sample: list[str] = field(default_factory=list)

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
        elif f.kind == "ref" and f.multi:
            names = _split_multi(text)
            if names:
                out[f.key] = names
            elif f.required:
                errors.append(RowError(row_no, f.key, f'Falta "{f.label}".'))
                failed = True
        elif f.kind == "bool":
            flag = _BOOL.get(_norm(text))
            if flag is None:
                errors.append(RowError(
                    row_no, f.key,
                    f'{f.label}: "{text}" no es válido (esperado: sí o no).'))
                failed = True
            else:
                out[f.key] = flag
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
    code_colors: code_colors_service.Choices | None = None,
    allow_deactivate: bool = True,
) -> tuple[list[tuple[int, dict]], list[RowError], _Resolver, list[dict]]:
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

    families: list[dict] = []
    if spec.key == "products":
        if code_colors is not None:
            # Before anything checks "Producto base": a family read out of the
            # codes is vetted exactly like one typed into that column.
            parsed, plan_errors, families = code_colors_service.plan(
                db, parsed, code_colors, company_id=company_id)
            errors.extend(RowError(*e) for e in plan_errors)
        errors.extend(_family_errors(db, parsed, company_id=company_id))
        errors.extend(_deactivation_errors(db, parsed, company_id=company_id,
                                           allow=allow_deactivate))

    return parsed, errors, _Resolver(db, company_id), families


def _family_errors(
    db: Session, parsed: list[tuple[int, dict]], *, company_id: int
) -> list[RowError]:
    """Rows whose "Producto base" a form would refuse, found before any write.

    Same rule as a hand-set parent_id (products.parent_refusal), so a file
    cannot build what the API may not: a variant of a variant, or a style left
    holding stock nothing can sell or move. Checked here, not while applying,
    so the preview says so instead of reading "ok" and failing on confirm; and
    commit runs it again on fresh data. Three queries however long the file.
    """
    linked = [(n, v) for n, v in parsed if v.get("parent")]
    flagged = [(n, v) for n, v in parsed if v.get("multicolor")]
    if not linked and not flagged:
        return []
    existing = {
        _norm(code): (pid, parent_id, multicolor)
        for pid, code, parent_id, multicolor in db.execute(
            select(Product.id, Product.code, Product.parent_id, Product.multicolor)
            .where(Product.company_id == company_id)
        ).all()
    }
    children = dict(db.execute(
        select(Product.parent_id, func.count(Product.id))
        .where(Product.company_id == company_id,
               Product.parent_id.is_not(None), Product.is_active.is_(True))
        .group_by(Product.parent_id)
    ).all())
    on_hand = dict(db.execute(
        select(StockLevel.product_id, func.sum(StockLevel.quantity))
        .where(StockLevel.company_id == company_id)
        .group_by(StockLevel.product_id)
    ).all())
    # A file can make a row a variant but never unmake one (an empty cell
    # leaves parent_id alone), so the database plus this map is the final word.
    file_parent = {_norm(v["code"]): _norm(v["parent"]) for _, v in linked}
    # A "Multicolor" cell in this file wins over what the row says today.
    file_multicolor = {
        _norm(v["code"]): v["multicolor"] for _, v in parsed if "multicolor" in v
    }

    errors: list[RowError] = []
    for row_no, v in linked:
        code, parent_code = _norm(v["code"]), _norm(v["parent"])
        product_id, _, _ = existing.get(code, (None, None, False))
        parent_id, grandparent_id, multicolor = existing.get(
            parent_code, (None, None, False))
        refusal = products_service.parent_refusal(
            v["code"], v["parent"],
            is_self=code == parent_code,
            parent_is_variant=grandparent_id is not None or parent_code in file_parent,
            parent_is_multicolor=file_multicolor.get(parent_code, bool(multicolor)),
            has_own_variants=bool(children.get(product_id)),
            parent_on_hand=on_hand.get(parent_id) or 0,
        )
        if refusal:
            errors.append(RowError(row_no, "parent", refusal))
    # One article in several colours cannot also be a style with variants.
    bases = set(file_parent.values())
    for row_no, v in flagged:
        code = _norm(v["code"])
        product_id, _, _ = existing.get(code, (None, None, False))
        if children.get(product_id) or code in bases:
            errors.append(RowError(row_no, "multicolor",
                                   products_service.multicolor_refusal(v["code"])))
    return errors


def _deactivation_errors(
    db: Session, parsed: list[tuple[int, dict]], *, company_id: int, allow: bool
) -> list[RowError]:
    """Rows whose "Activo" says no: who may, and what may not be switched off.

    A spreadsheet reaches hundreds of products at once, so it needs its own
    permission ("Eliminar productos en masa"), not just the import's. What is
    refused is the single delete's rule (products.deactivation_refusal), with
    one allowance a file needs: a base goes if its active variants go in the
    same file. Stock is not refused; the review step reports it.
    """
    off = [(n, v) for n, v in parsed if v.get("is_active") is False]
    if not off:
        return []
    if not allow:
        return [RowError(
            off[0][0], "is_active",
            'Desactivar productos desde una planilla requiere el permiso '
            '"Eliminar productos en masa".')]
    ids = {
        _norm(code): pid for pid, code in db.execute(
            select(Product.id, Product.code).where(Product.company_id == company_id)
        ).all()
    }
    active_kids: dict[int, set[str]] = defaultdict(set)
    for parent_id, code in db.execute(
        select(Product.parent_id, Product.code).where(
            Product.company_id == company_id, Product.parent_id.is_not(None),
            Product.is_active.is_(True))
    ).all():
        active_kids[parent_id].add(_norm(code))
    going = {_norm(v["code"]) for _, v in off}

    errors: list[RowError] = []
    for row_no, v in off:
        pid = ids.get(_norm(v["code"]))
        if pid is None:
            errors.append(RowError(
                row_no, "is_active",
                f'"{v["code"]}" no existe, así que no hay nada que desactivar.'))
            continue
        refusal = products_service.deactivation_refusal(
            v["code"], active_variants=len(active_kids.get(pid, set()) - going))
        if refusal:
            errors.append(RowError(row_no, "is_active", refusal))
    return errors


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
    code_colors: code_colors_service.Choices | None = None,
    allow_deactivate: bool = True,
) -> Preview:
    """Report what a commit would do. Never writes."""
    parsed, errors, resolver, families = _collect(
        db, spec, headers, rows, mapping,
        company_id=company_id, decimal_format=decimal_format,
        code_colors=code_colors, allow_deactivate=allow_deactivate,
    )
    preview = Preview(total=len(rows), errors=errors, families=families)

    # Codes this file itself will create — a deferred ref may point at one.
    own_codes = {_norm(v["code"]) for _, v in parsed if v.get("code")}

    missing: dict[tuple[str, str], MissingRef] = {}
    for row_no, values in parsed:
        for f in spec.fields:
            if f.kind != "ref" or f.key not in values:
                continue
            if f.deferred:
                name = values[f.key]
                if resolver.resolve(f.ref, name) is None and _norm(name) not in own_codes:
                    errors.append(RowError(
                        row_no, f.key,
                        f'{f.label} "{name}" no existe ni está en el archivo.'))
                continue
            for name in _ref_names(f, values[f.key]):
                if resolver.resolve(f.ref, name) is not None:
                    continue
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
            _norm(code): (pid, active)
            for pid, code, active in db.execute(
                select(Product.id, Product.code, Product.is_active)
                .where(Product.company_id == company_id)
            ).all()
        }
        switched_off: list[int] = []
        for _, values in good:
            hit = existing.get(_norm(values.get("code", "")))
            if hit is None:
                preview.to_create += 1
                continue
            preview.to_update += 1
            pid, active = hit
            if active and values.get("is_active") is False:
                preview.to_deactivate += 1
                switched_off.append(pid)
                if len(preview.deactivate_sample) < 12:
                    preview.deactivate_sample.append(values["code"])
            elif not active and values.get("is_active") is True:
                preview.to_reactivate += 1
        if switched_off:
            preview.deactivate_with_stock = db.execute(
                select(func.count(func.distinct(StockLevel.product_id))).where(
                    StockLevel.product_id.in_(switched_off), StockLevel.quantity != 0)
            ).scalar_one()
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
    code_colors: code_colors_service.Choices | None = None,
    allow_deactivate: bool = True,
) -> dict:
    """Apply the batch. All rows or none — the caller's transaction is rolled
    back on any error."""
    parsed, errors, resolver, families = _collect(
        db, spec, headers, rows, mapping,
        company_id=company_id, decimal_format=decimal_format,
        code_colors=code_colors, allow_deactivate=allow_deactivate,
    )
    if errors:
        raise ImportError_(
            f"El archivo tiene {len(errors)} fila(s) con errores. "
            "Corregilas y volvé a previsualizar."
        )

    # Resolve (and optionally create) every referenced entity up front.
    for row_no, values in parsed:
        for f in spec.fields:
            if f.kind != "ref" or f.deferred or f.key not in values:
                continue
            ids = []
            for name in _ref_names(f, values[f.key]):
                found = resolver.resolve(f.ref, name)
                if found is None:
                    if f.creatable and create_missing:
                        found = resolver.create(f.ref, name)
                    else:
                        raise ImportError_(
                            f'Fila {row_no}: {f.label} "{name}" no existe.'
                        )
                ids.append(found)
            values[f.key] = ids if f.multi else ids[0]

    applier = {
        "products": _apply_products,
        "costs": _apply_costs,
        "stock": _apply_stock,
        "price_list_items": _apply_price_list_items,
    }[spec.key]
    result = applier(db, parsed, company_id=company_id, user_id=user_id)
    if code_colors is not None and spec.key == "products":
        db.flush()
        code_colors_service.remember(db, code_colors, company_id=company_id)
        result["families"] = len(families)
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
    # Captured up front: sync_variants needs to know which colour a splitting
    # article's stock belongs to, and by then the new set is already on the row.
    previous_colors = {p.id: list(p.color_ids) for p in by_code.values()}
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
            ("description", "description"),
            ("product_type", "product_type_id"), ("brand", "brand_id"),
            ("model", "model_id"), ("supplier", "supplier_id"),
            ("min_stock", "min_stock"), ("sale_price", "sale_price"),
            ("price_list", "price_list_id"), ("multicolor", "multicolor"),
            ("is_active", "is_active"),
        ):
            if src in v:
                setattr(product, dst, v[src])
        if "color" in v:
            # The whole set, so re-importing an edited export is a replacement
            # rather than an ever-growing list.
            products_service.set_colors(db, product, v["color"], company_id=company_id)
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

    # Styles are wired last, so a file can list "ARM-001" and the variants that
    # point at it in any order — by now every row of the batch has an id.
    # Whether each link is allowed was settled by _family_errors before commit
    # wrote anything.
    db.flush()
    for row_no, v in parsed:
        if "parent" not in v:
            continue
        product = by_code[_norm(v["code"])]
        parent = by_code.get(_norm(v["parent"]))
        if parent is None:
            raise ImportError_(
                f'Fila {row_no}: el producto base "{v["parent"]}" no existe.')
        product.parent_id = parent.id

    # Same rule as the API (CLAUDE.md rule 9): a row offered in several colours
    # is a style, and its articles are made here rather than by hand later. A
    # row that names a "Producto base" is itself a variant — several colours on
    # it means bicolour, not a family — so sync_variants leaves it alone.
    db.flush()
    for row_no, v in parsed:
        product = by_code[_norm(v["code"])]
        if not product.is_active:
            continue            # taken out of the catalogue: nothing to split
        try:
            products_service.sync_variants(
                db, product, company_id=company_id, user_id=user_id,
                previous_color_ids=previous_colors.get(product.id, []),
            )
        except products_service.ProductError as exc:
            # A refusal is the row's fault, reported like any other: never a 500.
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
