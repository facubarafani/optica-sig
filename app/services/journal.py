"""Operation journal: what each request changed, so it can be undone and redone.

A shop edits shared data, so undo cannot live in the browser. Every write from
a shop user to the catalogue, prices, stock or an import becomes an
``Operation``, and every row it touches an ``OperationChange`` holding that
row's columns before and after. Undo replays "before", redo replays "after",
and each is recorded as an operation of its own.

Capturing without touching the routers
    ``attach`` (called from core.deps.get_current_user) puts a journal on the
    request's session when the path is in ``AREAS``. The session's
    ``after_flush`` event sees every tracked row written, with attribute history
    still intact; ``before_commit`` writes the operation in the same
    transaction, so a request that rolls back leaves no entry and one that
    commits always has one. A new endpoint in those areas is journaled by
    construction; a new table joins by adding it to ``TRACKED``.

Replaying without bypassing the rules (CLAUDE.md rules 3, 4, 10)
    Nothing is deleted: a row the operation created is deactivated. Stock is
    never rewritten: a movement is undone by a compensating ADJUSTMENT through
    services.stock. Costs and prices go back through services.pricing, so
    cost_history and change_history stay whole. Sales, payments, users, logins
    and provider actions are outside the journal on purpose.

Conflicts
    Data is shared, so a row may have moved on since. Each row is compared with
    the operation's "after" before it is touched. One that changed, is still in
    use, or would leave stock negative is skipped with a reason and the rest is
    applied. ``revert(dry_run=True)`` runs everything and rolls back, so the
    preview is exactly what confirming would do.
"""
from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, delete, event, func, inspect, select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.branch import Branch
from app.models.company import CompanySettings
from app.models.enums import ChangeAction, PricingMode, StockMovementType
from app.models.imports import ImportBatch
from app.models.journal import Operation, OperationChange
from app.models.pricing import PriceCategory, PriceList
from app.models.product import (
    Brand,
    Color,
    Product,
    ProductModel,
    ProductType,
    product_colors,
)
from app.models.sales import SaleItem
from app.models.stock import StockLevel, StockMovement
from app.models.supplier import Supplier
from app.schemas.stock import StockMovementCreate
from app.services import pricing as pricing_service
from app.services import products as products_service
from app.services import stock as stock_service

RETENTION = timedelta(days=90)
# A column whose old value SQLAlchemy could not tell us (it was never loaded).
UNKNOWN = {"$unknown": True}
_SKIP = frozenset({"id", "company_id", "created_at", "updated_at"})
_PRICING_FIELDS = ("pricing_mode", "sale_price", "price_list_id", "price_category_code")


class JournalError(Exception):
    """An undo or redo that cannot be applied at all."""


@dataclass(frozen=True)
class Tracked:
    model: type
    noun: str                                    # what the shop calls one row
    name_attr: str | None
    collections: tuple[tuple[str, str], ...] = ()  # (relationship, snapshot key)


TRACKED: dict[str, Tracked] = {
    t.model.__tablename__: t for t in (
        Tracked(Product, "producto", "code", (("colors", "color_ids"),)),
        Tracked(Color, "color", "name"),
        Tracked(Brand, "marca", "name"),
        Tracked(ProductModel, "modelo", "name"),
        Tracked(ProductType, "tipo de producto", "name"),
        Tracked(Supplier, "proveedor", "name"),
        Tracked(Branch, "sucursal", "name"),
        Tracked(PriceList, "lista de precios", "name"),
        Tracked(PriceCategory, "categoría de precio", "code"),
        Tracked(StockMovement, "movimiento de stock", None),
    )
}
_BY_CLASS = {t.model: (name, t) for name, t in TRACKED.items()}

# Path segment -> (what the shop calls it, permission undoing it needs).
# An allowlist on purpose: a new area is outside the journal until it is
# thought about, rather than undoable by accident (a sale must never be).
AREAS: dict[str, tuple[str, str | None]] = {
    "products": ("Productos", "products:write"),
    "colors": ("Colores", "products:write"),
    "brands": ("Marcas", "products:write"),
    "product-types": ("Tipos de producto", "products:write"),
    "product-models": ("Modelos", "products:write"),
    "suppliers": ("Proveedores", "suppliers:write"),
    "branches": ("Sucursales", "branches:write"),
    "price-lists": ("Precios", "pricing:write"),
    "stock": ("Stock", "stock:write"),
    "imports": ("Importación", None),      # the imported spec's own permission
}
_IMPORT_COMMIT = re.compile(r"/api/imports/batches/(\d+)/commit/?$")

FIELD_LABELS = {
    "code": "Código", "description": "Descripción", "name": "Nombre",
    "parent_id": "Producto base", "color_ids": "Colores", "multicolor": "Multicolor",
    "product_type_id": "Tipo de producto", "brand_id": "Marca", "model_id": "Modelo",
    "supplier_id": "Proveedor", "pricing_mode": "Modo de precio",
    "sale_price": "Precio de venta", "price_list_id": "Lista de precios",
    "price_category_code": "Categoría de precio", "current_cost": "Costo",
    "min_stock": "Stock mínimo", "is_active": "Activo", "hex_code": "Tono",
    "price": "Precio", "quantity": "Cantidad", "product_id": "Producto",
    "branch_id": "Sucursal", "movement_type": "Tipo de movimiento",
}
_FK_DISPLAY = {
    "parent_id": (Product, "code"), "product_id": (Product, "code"),
    "product_type_id": (ProductType, "name"), "brand_id": (Brand, "name"),
    "model_id": (ProductModel, "name"), "supplier_id": (Supplier, "name"),
    "price_list_id": (PriceList, "name"), "branch_id": (Branch, "name"),
}
_VALUE_LABELS = {
    "pricing_mode": {PricingMode.PRICE_LIST.value: "por lista", PricingMode.MANUAL.value: "manual"},
    "movement_type": {
        StockMovementType.INBOUND.value: "ingreso", StockMovementType.OUTBOUND.value: "egreso",
        StockMovementType.ADJUSTMENT.value: "ajuste", StockMovementType.TRANSFER.value: "transferencia",
    },
}


# --- values ----------------------------------------------------------------

def _dump(value):
    """A column value as JSON, normalised so equal values compare equal
    (Decimal("20000") and a database's Decimal("20000.00") are the same cost)."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        value = Decimal(str(value))
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _load(model, key: str, raw):
    """The inverse of _dump for one column."""
    if raw is None:
        return None
    col_type = model.__table__.c[key].type
    if isinstance(col_type, SAEnum) and col_type.enum_class is not None:
        return col_type.enum_class(raw)
    if isinstance(col_type, Numeric):
        return Decimal(raw)
    if isinstance(col_type, DateTime):
        return datetime.fromisoformat(raw)
    return raw


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _col(model, key: str, value):
    """_dump by column type: a numeric column set to the int 0 (a column
    default) must read the same as the Decimal("0.00") the database returns."""
    if value is not None and not isinstance(value, bool) and isinstance(
            model.__table__.c[key].type, Numeric):
        value = Decimal(str(value))
    return _dump(value)


def _snapshot(obj, t: Tracked, *, new: bool = False) -> dict:
    state = inspect(obj)
    data = {
        a.key: _col(t.model, a.key, getattr(obj, a.key))
        for a in state.mapper.column_attrs if a.key not in _SKIP
    }
    for rel, key in t.collections:
        # A new row whose collection was never touched has none; reading it
        # would only fire a query in the middle of a flush.
        if new and rel in state.unloaded:
            data[key] = []
        else:
            data[key] = sorted(o.id for o in getattr(obj, rel))
    return data


def _diff(obj, t: Tracked) -> tuple[dict, dict]:
    state = inspect(obj)
    before, after = {}, {}
    for attr in state.mapper.column_attrs:
        key = attr.key
        if key in _SKIP:
            continue
        hist = state.attrs[key].history
        if not hist.has_changes():
            continue
        new = _col(t.model, key, hist.added[0]) if hist.added else None
        if hist.deleted:
            old = _col(t.model, key, hist.deleted[0])
            if old == new:
                continue
            before[key] = old
        else:
            before[key] = UNKNOWN
        after[key] = new
    for rel, key in t.collections:
        hist = state.attrs[rel].history
        if not hist.has_changes():
            continue
        old = sorted(o.id for o in (*hist.unchanged, *hist.deleted))
        new = sorted(o.id for o in (*hist.unchanged, *hist.added))
        if old != new:
            before[key], after[key] = old, new
    return before, after


# --- capture ---------------------------------------------------------------

@dataclass
class _Change:
    entity_type: str
    entity_id: int
    action: ChangeAction
    before: dict | None
    after: dict | None


@dataclass
class _Journal:
    company_id: int
    user_id: int
    area: str
    method: str
    path: str
    import_batch_id: int | None = None
    reverts_id: int | None = None
    pending: list[_Change] = field(default_factory=list)
    staged_id: int | None = None       # written, transaction not yet committed
    operation_id: int | None = None    # committed: later commits append to it
    seq: int = 0


def attach(db: Session, *, method: str, path: str, user: User) -> None:
    """Journal this request's writes, if it is one the shop can undo."""
    if method in ("GET", "HEAD", "OPTIONS"):
        return
    segments = [s for s in path.split("/") if s]
    area = segments[1] if len(segments) > 1 and segments[0] == "api" else ""
    if area not in AREAS:
        return
    batch_id = None
    if area == "imports":
        match = _IMPORT_COMMIT.search(path)
        if match is None:
            return              # uploads and previews change no business data
        batch_id = int(match.group(1))
    db.info["journal"] = _Journal(
        company_id=user.company_id, user_id=user.id, area=area, method=method,
        path=path[:200], import_batch_id=batch_id,
    )


@event.listens_for(Session, "after_flush")
def _capture(session: Session, flush_context) -> None:
    journal = session.info.get("journal")
    if journal is None:
        return
    for obj in session.new:
        hit = _BY_CLASS.get(type(obj))
        if hit:
            name, t = hit
            journal.pending.append(
                _Change(name, obj.id, ChangeAction.CREATE, None, _snapshot(obj, t, new=True)))
    for obj in session.dirty:
        hit = _BY_CLASS.get(type(obj))
        if hit:
            name, t = hit
            before, after = _diff(obj, t)
            if after:
                journal.pending.append(
                    _Change(name, obj.id, ChangeAction.UPDATE, before, after))


@event.listens_for(Session, "before_commit")
def _write(session: Session) -> None:
    journal = session.info.get("journal")
    if journal is None:
        return
    # commit() fires this hook *before* its own flush, so a request that sets a
    # field and commits straight away has captured nothing yet. Flush first.
    session.flush()
    if not journal.pending:
        return
    pending, journal.pending = journal.pending, []
    op_id = journal.staged_id or journal.operation_id
    if op_id is None:
        op = Operation(
            company_id=journal.company_id, user_id=journal.user_id,
            area=journal.area, method=journal.method, path=journal.path,
            import_batch_id=journal.import_batch_id, reverts_id=journal.reverts_id,
            label="", change_count=0,
        )
        session.add(op)
        session.flush()
        journal.staged_id = op.id
        if journal.reverts_id is not None:
            target = session.get(Operation, journal.reverts_id)
            if target is not None:
                target.reverted_by_id = op.id
    else:
        op = session.get(Operation, op_id)
    for change in pending:
        journal.seq += 1
        session.add(OperationChange(
            operation_id=op.id, seq=journal.seq, entity_type=change.entity_type,
            entity_id=change.entity_id, action=change.action,
            before=json.dumps(change.before) if change.before is not None else None,
            after=json.dumps(change.after) if change.after is not None else None,
        ))
    op.change_count = (op.change_count or 0) + len(pending)
    session.flush()
    op.label = describe(session, op)[:255]
    session.flush()


@event.listens_for(Session, "after_commit")
def _committed(session: Session) -> None:
    journal = session.info.get("journal")
    if journal is not None and journal.staged_id is not None:
        journal.operation_id, journal.staged_id = journal.staged_id, None


@event.listens_for(Session, "after_rollback")
def _rolled_back(session: Session) -> None:
    journal = session.info.get("journal")
    if journal is not None:
        journal.pending.clear()
        journal.staged_id = None


# --- describing ------------------------------------------------------------

def _display(db: Session, t: Tracked, entity_id: int) -> str:
    obj = db.get(t.model, entity_id)
    if obj is None:
        return f"#{entity_id}"
    if t.model is StockMovement:
        product = db.get(Product, obj.product_id)
        return product.code if product else f"#{entity_id}"
    return str(getattr(obj, t.name_attr)) if t.name_attr else f"#{entity_id}"


def _counts(created: int, updated: int) -> str:
    parts = []
    if created:
        parts.append(f"{created} alta(s)")
    if updated:
        parts.append(f"{updated} cambio(s)")
    return " y ".join(parts) or "sin cambios"


def describe(db: Session, op: Operation) -> str:
    """What the shop reads in Actividad. No em dashes (CLAUDE.md)."""
    if op.reverts_id is not None:
        target = db.get(Operation, op.reverts_id)
        if target is None:
            return "Deshacer"
        if target.reverts_id is None:
            return f"Deshiciste: {target.label}"
        original = db.get(Operation, target.reverts_id)
        return f"Rehiciste: {(original or target).label}"

    rows = db.execute(
        select(OperationChange).where(OperationChange.operation_id == op.id)
        .order_by(OperationChange.seq)
    ).scalars().all()
    entities: dict[tuple[str, int], str] = {}
    for r in rows:
        key = (r.entity_type, r.entity_id)
        kind = entities.get(key)
        if r.action == ChangeAction.CREATE:
            entities[key] = "create"
        elif kind is None or kind == "update":
            after = json.loads(r.after or "{}")
            before = json.loads(r.before or "{}")
            entities[key] = ("deactivate" if after.get("is_active") is False
                             and before.get("is_active") is True else "update")
    created = sum(1 for k in entities.values() if k == "create")
    updated = len(entities) - created

    if op.import_batch_id is not None:
        batch = db.get(ImportBatch, op.import_batch_id)
        return f"Importación de {batch.filename if batch else 'un archivo'}: {_counts(created, updated)}"
    if not entities:
        return AREAS.get(op.area, (op.area, None))[0]
    (etype, eid), kind = next(iter(entities.items()))
    t = TRACKED[etype]
    if t.model is StockMovement:
        head = f"Movimiento de stock de {_display(db, t, eid)}"
    else:
        verb = {"create": "Alta de", "deactivate": "Baja de"}.get(kind, "Cambios en")
        head = f"{verb} {t.noun} {_display(db, t, eid)}"
    return head if len(entities) == 1 else f"{head} y {len(entities) - 1} más"


# --- state and permission --------------------------------------------------

def is_admin(user: User) -> bool:
    """Who may undo anybody's change: whoever manages the shop's people."""
    codes = user.permission_codes
    return "*" in codes or "users:write" in codes


def is_undone(db: Session, op: Operation) -> bool:
    if op.reverted_by_id is None:
        return False
    reverter = db.get(Operation, op.reverted_by_id)
    return reverter is not None and not is_undone(db, reverter)


def _write_permission(db: Session, op: Operation) -> str | None:
    if op.area == "imports":
        from app.services.importer.specs import get_spec

        batch = db.get(ImportBatch, op.import_batch_id) if op.import_batch_id else None
        spec = get_spec(batch.spec_key) if batch else None
        return spec.permission if spec else "products:write"
    return AREAS.get(op.area, (None, None))[1]


def refusal(db: Session, user: User, op: Operation) -> str | None:
    """Why ``user`` may not undo or redo ``op``; None when they may."""
    if op.user_id != user.id and not is_admin(user):
        return "Sólo quien hizo el cambio o un administrador puede deshacerlo."
    codes = user.permission_codes
    perm = _write_permission(db, op)
    if perm and "*" not in codes and perm not in codes:
        return f"Falta el permiso {perm}."
    if _aware(op.created_at) < datetime.now(timezone.utc) - RETENTION:
        return "Pasaron más de 90 días: ya no se puede deshacer."
    return None


def purge(db: Session, company_id: int) -> None:
    """Forget operations older than the retention window."""
    cutoff = datetime.now(timezone.utc) - RETENTION
    old = select(Operation.id).where(
        Operation.company_id == company_id, Operation.created_at < cutoff
    )
    db.execute(delete(OperationChange).where(OperationChange.operation_id.in_(old)))
    db.execute(delete(Operation).where(Operation.id.in_(old)))
    db.commit()


# --- reading ---------------------------------------------------------------

@dataclass
class _Entity:
    entity_type: str
    entity_id: int
    first_seq: int
    action: ChangeAction
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)


def _merged(db: Session, op_id: int) -> list[_Entity]:
    """One entry per row, however many flushes touched it: earliest "before",
    latest "after", and "create" if the operation made it."""
    entities: dict[tuple[str, int], _Entity] = {}
    for r in db.execute(
        select(OperationChange).where(OperationChange.operation_id == op_id)
        .order_by(OperationChange.seq)
    ).scalars():
        key = (r.entity_type, r.entity_id)
        ent = entities.get(key)
        if ent is None:
            ent = entities[key] = _Entity(r.entity_type, r.entity_id, r.seq, r.action)
        elif r.action == ChangeAction.CREATE:
            ent.action = ChangeAction.CREATE
        for k, v in json.loads(r.before or "{}").items():
            ent.before.setdefault(k, v)
        ent.after.update(json.loads(r.after or "{}"))
    return list(entities.values())


def _show(db: Session, key: str, value) -> str | None:
    if value is None:
        return None
    if value == UNKNOWN:
        return "?"
    if key == "color_ids":
        names = [c.name for cid in value if (c := db.get(Color, cid)) is not None]
        return ", ".join(names) or "(ninguno)"
    if key in _FK_DISPLAY:
        model, attr = _FK_DISPLAY[key]
        obj = db.get(model, value)
        return str(getattr(obj, attr)) if obj is not None else f"#{value}"
    if isinstance(value, bool):
        return "sí" if value else "no"
    return _VALUE_LABELS.get(key, {}).get(value, str(value))


def summaries(db: Session, ops: list[Operation], user: User) -> list[dict]:
    ids = {op.user_id for op in ops if op.user_id}
    names = {
        u.id: u.full_name or u.email
        for u in db.execute(select(User).where(User.id.in_(ids))).scalars()
    } if ids else {}
    out = []
    for op in ops:
        undone = is_undone(db, op)
        problem = refusal(db, user, op)
        out.append({
            "id": op.id, "label": op.label, "area": op.area,
            "area_label": AREAS.get(op.area, (op.area, None))[0],
            "user_id": op.user_id, "user_name": names.get(op.user_id),
            "created_at": op.created_at, "change_count": op.change_count,
            "import_batch_id": op.import_batch_id, "undone": undone,
            "can_undo": not undone and problem is None,
            "can_redo": undone and problem is None,
            "blocked_reason": problem,
        })
    return out


def detail(db: Session, op: Operation, user: User, *, limit: int = 300) -> dict:
    entities = sorted(_merged(db, op.id), key=lambda e: e.first_seq)
    rows = []
    for ent in entities[:limit]:
        t = TRACKED.get(ent.entity_type)
        if t is None:
            continue
        if ent.action == ChangeAction.CREATE:
            action = "create"
            keys = ["quantity", "branch_id"] if t.model is StockMovement else []
        else:
            action = "update"
            if ent.after.get("is_active") is False and ent.before.get("is_active") is True:
                action = "deactivate"
            elif ent.after.get("is_active") is True and ent.before.get("is_active") is False:
                action = "reactivate"
            keys = list(ent.after)
        rows.append({
            "entity_type": ent.entity_type, "entity_id": ent.entity_id,
            "noun": t.noun, "name": _display(db, t, ent.entity_id), "action": action,
            "fields": [
                {"field": k, "label": FIELD_LABELS.get(k, k),
                 "before": _show(db, k, ent.before.get(k)),
                 "after": _show(db, k, ent.after.get(k))}
                for k in keys
            ],
        })
    return {**summaries(db, [op], user)[0], "entity_count": len(entities), "entities": rows}


# --- undo and redo ---------------------------------------------------------

@dataclass
class Skip:
    entity: str
    reason: str


@dataclass
class RevertOutcome:
    applied: int
    skipped: list[Skip]
    operation_id: int | None
    dry_run: bool


def _allow_negative(db: Session, company_id: int) -> bool:
    cfg = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    return bool(cfg and cfg.allow_negative_stock)


def _count(db: Session, stmt) -> int:
    return int(db.execute(stmt).scalar_one() or 0)


def _in_use(db: Session, obj) -> str | None:
    """Why a row this operation created cannot be deactivated yet."""
    if isinstance(obj, Product):
        if _count(db, select(func.count()).select_from(Product).where(
                Product.parent_id == obj.id, Product.is_active.is_(True))):
            return "todavía tiene variantes activas"
        on_hand = Decimal(str(db.execute(
            select(func.coalesce(func.sum(StockLevel.quantity), 0))
            .where(StockLevel.product_id == obj.id)).scalar_one()))
        if on_hand:
            return f"tiene {format(on_hand.normalize(), 'f')} de stock"
        if _count(db, select(func.count()).select_from(SaleItem).where(
                SaleItem.product_id == obj.id)):
            return "ya se vendió"
        return None
    if isinstance(obj, Color):
        used = _count(db, select(func.count()).select_from(
            product_colors.join(Product.__table__,
                                Product.__table__.c.id == product_colors.c.product_id)
        ).where(product_colors.c.color_id == obj.id, Product.is_active.is_(True)))
        return f"lo usan {used} producto(s)" if used else None
    columns = {
        Brand: Product.brand_id, ProductModel: Product.model_id,
        ProductType: Product.product_type_id, Supplier: Product.supplier_id,
        PriceList: Product.price_list_id,
    }
    if type(obj) in columns:
        used = _count(db, select(func.count()).select_from(Product).where(
            columns[type(obj)] == obj.id, Product.is_active.is_(True)))
        return f"lo usan {used} producto(s)" if used else None
    if isinstance(obj, Branch):
        if _count(db, select(func.count()).select_from(StockLevel).where(
                StockLevel.branch_id == obj.id, StockLevel.quantity != 0)):
            return "tiene stock"
    return None


def _compensate(db: Session, mv: StockMovement, user: User) -> tuple[str | None, bool]:
    delta = Decimal(mv.quantity)
    level = db.execute(select(StockLevel).where(
        StockLevel.company_id == user.company_id, StockLevel.product_id == mv.product_id,
        StockLevel.branch_id == mv.branch_id)).scalar_one_or_none()
    have = Decimal(level.quantity) if level else Decimal("0")
    if have - delta < 0 and not _allow_negative(db, user.company_id):
        return f"dejaría el stock en {format((have - delta).normalize(), 'f')}", True
    try:
        stock_service.apply_movement(
            db,
            StockMovementCreate(
                product_id=mv.product_id, branch_id=mv.branch_id,
                movement_type=StockMovementType.ADJUSTMENT, quantity=-delta,
                reference="DESHACER", note=f"Revierte el movimiento #{mv.id}",
            ),
            company_id=user.company_id, user_id=user.id,
            allow_negative=True, commit=False,
        )
    except stock_service.StockError:
        return "el producto ya no lleva stock propio (ahora es un producto base)", False
    return None, False


def _restore(db: Session, obj, t: Tracked, values: dict, user: User) -> None:
    values = dict(values)
    if isinstance(obj, Product):
        if "color_ids" in values:
            products_service.set_colors(db, obj, values.pop("color_ids"),
                                        company_id=user.company_id)
        if "current_cost" in values:
            pricing_service.change_cost(db, obj, Decimal(values.pop("current_cost")),
                                        user_id=user.id, note="Deshacer", commit=False)
        pricing = {k: _load(Product, k, values.pop(k)) for k in _PRICING_FIELDS if k in values}
        if pricing:
            pricing_service.apply_pricing_update(db, obj, pricing, user_id=user.id)
    if isinstance(obj, PriceCategory) and "price" in values:
        pricing_service.set_price(db, obj, Decimal(values.pop("price")),
                                  company_id=user.company_id, user_id=user.id)
    for key, raw in values.items():
        setattr(obj, key, _load(t.model, key, raw))
    if isinstance(obj, Product):
        db.flush()
        try:
            pricing_service.validate_pricing(db, obj, company_id=user.company_id)
        except pricing_service.PricingError as exc:
            raise JournalError(f"{obj.code}: {exc}") from exc


def _revert_entity(db: Session, ent: _Entity, user: User) -> tuple[str | None, bool]:
    """Put one row back. Returns (why it was skipped, whether only because it
    is still in use, which another row's revert may yet resolve)."""
    t = TRACKED.get(ent.entity_type)
    if t is None:
        return "no se puede revertir", False
    obj = db.get(t.model, ent.entity_id)
    if obj is None or obj.company_id != user.company_id:
        return "ya no existe", False
    if t.model is StockMovement:
        return _compensate(db, obj, user)

    current = _snapshot(obj, t)
    drift = [k for k, v in ent.after.items() if current.get(k) != v]
    if drift:
        fields = ", ".join(FIELD_LABELS.get(k, k) for k in drift[:3])
        return f"cambió después ({fields})", False
    if ent.action == ChangeAction.CREATE:
        used = _in_use(db, obj)
        if used:
            return used, True
        obj.is_active = False
        return None, False
    if any(v == UNKNOWN for v in ent.before.values()):
        return "no quedó registrado cómo estaba antes", False
    for cid in ent.before.get("color_ids") or []:
        color = db.get(Color, cid)
        if color is None or color.company_id != user.company_id:
            return "un color que tenía ya no existe", False
    parent_id = ent.before.get("parent_id")
    if parent_id is not None and db.get(Product, parent_id) is None:
        return "su producto base ya no existe", False
    _restore(db, obj, t, ent.before, user)
    return None, False


def revert(db: Session, target: Operation, *, user: User, dry_run: bool = False) -> RevertOutcome:
    """Reverse ``target``: an original (undo) or an undo (redo).

    The caller has already checked ``refusal`` and the undone state.
    """
    entities = sorted(_merged(db, target.id), key=lambda e: e.first_seq, reverse=True)
    db.info["journal"] = _Journal(
        company_id=user.company_id, user_id=user.id, area="activity", method="POST",
        path=f"/api/activity/{target.id}", reverts_id=target.id,
    )
    try:
        applied, skipped = 0, []
        pending = entities
        while pending:
            deferred, progressed = [], False
            for ent in pending:
                reason, in_use = _revert_entity(db, ent, user)
                db.flush()
                if reason is None:
                    applied += 1
                    progressed = True
                elif in_use:
                    deferred.append((ent, reason))
                else:
                    skipped.append(Skip(_entity_name(db, ent), reason))
            if not deferred:
                break
            if not progressed:
                skipped.extend(Skip(_entity_name(db, ent), reason) for ent, reason in deferred)
                break
            pending = [ent for ent, _ in deferred]

        if dry_run or applied == 0:
            db.rollback()
            return RevertOutcome(applied, skipped, None, dry_run)
        db.commit()
        return RevertOutcome(applied, skipped, db.info["journal"].operation_id, False)
    except Exception:
        db.rollback()
        raise
    finally:
        db.info.pop("journal", None)


def _entity_name(db: Session, ent: _Entity) -> str:
    t = TRACKED.get(ent.entity_type)
    if t is None:
        return f"{ent.entity_type} #{ent.entity_id}"
    return f"{t.noun} {_display(db, t, ent.entity_id)}"
