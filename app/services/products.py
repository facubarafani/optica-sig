"""Product rules that are more than a column assignment.

Two things live here:

* **Colours.** Which colours an article comes in (an N-N link), and the short
  ``code`` that names a colour inside a variant's product code.
* **Variants.** The same style in several colours. Each variant is its own
  ``products`` row with its own code and its own stock; the style they share is
  the row they point at through ``parent_id``. A style is not an article, so
  nothing may sell or stock it — ``assert_sellable`` is the one gate that says
  so, and both services.sales and services.stock go through it.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import StockMovementType
from app.models.product import Color, Product


class ProductError(Exception):
    """Raised on an invalid product write (unknown colour, style sold...)."""


# --- colours ---------------------------------------------------------------

def resolve_colors(
    db: Session, color_ids: list[int] | None, *, company_id: int
) -> list[Color]:
    """Load colours by id, keeping the order given and dropping repeats.

    ``db.get`` rather than one ``IN`` query: the ids repeat across the rows of
    an import, and the identity map turns every repeat into a free lookup.
    """
    out: list[Color] = []
    seen: set[int] = set()
    for cid in color_ids or []:
        if cid in seen:
            continue
        seen.add(cid)
        color = db.get(Color, cid)
        # A colour from another company must read as "does not exist" — leaking
        # its existence through a different message would defeat the scoping.
        if color is None or color.company_id != company_id:
            raise ProductError(f"El color #{cid} no existe.")
        out.append(color)
    return out


def set_colors(
    db: Session, product: Product, color_ids: list[int] | None, *, company_id: int
) -> list[Color]:
    """Replace the product's whole colour set. Does not commit."""
    product.colors = resolve_colors(db, color_ids, company_id=company_id)
    return product.colors


def _slug(text: str) -> str:
    """Fold accents and drop anything that cannot live in a code."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]", "", ascii_only).upper()


def derive_color_code(
    db: Session, name: str, *, company_id: int, exclude_id: int | None = None
) -> str | None:
    """Propose a free short code for a colour name ("Havana" -> "HAV").

    Three letters is the sweet spot for reading a code like ARM-001-HAV at a
    glance. Where three collide it lengthens before it starts numbering, so
    "Negro"/"Negro mate" become NEG and NEGR rather than NEG and NEG2. A name
    already shorter than three ("C1") is its own code: starting the loop at 3
    would skip it and number straight away, turning "C1" into C12.
    """
    base = _slug(name)
    if not base:
        return None
    stmt = select(func.upper(Color.code)).where(
        Color.company_id == company_id, Color.code.is_not(None)
    )
    if exclude_id is not None:
        stmt = stmt.where(Color.id != exclude_id)
    taken = set(db.execute(stmt).scalars())

    for size in range(min(3, len(base)), min(len(base), 8) + 1):
        if (candidate := base[:size]) not in taken:
            return candidate
    stem = base[:6]
    for n in range(2, 100):
        if (candidate := f"{stem}{n}") not in taken:
            return candidate
    return None


def color_code_or_slug(color: Color) -> str:
    """The tag to put in a product code, even for a colour with no code set."""
    return (color.code or _slug(color.name)[:3] or "X").upper()


# --- variants --------------------------------------------------------------

def variant_counts(db: Session, parent_ids: list[int]) -> dict[int, int]:
    """{parent_id: how many active variants} — one query for a whole page."""
    if not parent_ids:
        return {}
    rows = db.execute(
        select(Product.parent_id, func.count(Product.id))
        .where(Product.parent_id.in_(parent_ids), Product.is_active.is_(True))
        .group_by(Product.parent_id)
    ).all()
    return {pid: n for pid, n in rows}


def stock_totals(
    db: Session, products: list[Product], *, company_id: int
) -> dict[int, Decimal]:
    """{product_id: units on hand across every branch} — one query for a page.

    A style holds no stock of its own, so its figure is the sum of its active
    variants: the number a grid wants on the line that stands for the family.
    """
    from app.models.stock import StockLevel

    ids = {p.id for p in products}
    totals = {pid: Decimal("0") for pid in ids}
    if not ids:
        return totals
    rows = db.execute(
        select(Product.id, Product.parent_id, Product.is_active,
               func.sum(StockLevel.quantity))
        .join(StockLevel, StockLevel.product_id == Product.id)
        .where(StockLevel.company_id == company_id,
               Product.id.in_(ids) | Product.parent_id.in_(ids))
        .group_by(Product.id, Product.parent_id, Product.is_active)
    ).all()
    for pid, parent_id, is_active, qty in rows:
        if pid in ids:
            totals[pid] += qty
        if parent_id in ids and is_active:
            totals[parent_id] += qty
    return totals


def has_variants(db: Session, product: Product) -> bool:
    return bool(
        db.execute(
            select(Product.id)
            .where(Product.parent_id == product.id, Product.is_active.is_(True))
            .limit(1)
        ).scalar_one_or_none()
    )


def assert_sellable(db: Session, product: Product) -> None:
    """A style is a grouping, not an article. Refuse to move money or stock on it.

    Called by services.sales and services.stock, so there is exactly one
    definition of "this row is not a thing you can sell".
    """
    if has_variants(db, product):
        raise ProductError(
            f'"{product.code}" es un producto base: se vende y se stockea por '
            "color. Elegí una de sus variantes."
        )


def _stock_on_hand(db: Session, product: Product, *, company_id: int):
    """Everything this product holds across every branch."""
    # Imported here: services.stock imports this module for assert_sellable, so
    # a module-level import would close the cycle.
    from app.models.stock import StockLevel

    return db.execute(
        select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(
            StockLevel.company_id == company_id, StockLevel.product_id == product.id
        )
    ).scalar_one()


def assert_stock_free(db: Session, product: Product, *, company_id: int) -> None:
    """Refuse to turn a stocked article into a style by hand.

    The generate-variants endpoint has no idea which colour the stock is, so it
    makes the shop say. Editing a product's colours does know — see
    sync_variants, which moves the stock rather than refusing.
    """
    on_hand = _stock_on_hand(db, product, company_id=company_id)
    if on_hand:
        raise ProductError(_stocked_style(product.code, on_hand))


def _stocked_style(code: str, on_hand) -> str:
    return (
        f'"{code}" tiene {on_hand:g} de stock. Un producto base no lleva stock '
        "propio: ajustalo a cero y cargalo en la variante que corresponda."
    )


def deactivation_refusal(code: str, *, active_variants: int) -> str | None:
    """Why a product may not be switched off; None when it may.

    A base whose variants stay active would leave them hanging off a product
    nobody can see or pick. Stock is deliberately not a refusal: a product
    taken out of the catalogue may still have units on the shelf, and the
    stock screen shows inactive products on request.
    """
    if active_variants:
        return (
            f'"{code}" es un producto base con {active_variants} variante(s) '
            "activa(s): desactivalas también, o dejalo activo."
        )
    return None


def assert_deactivatable(db: Session, product: Product) -> None:
    """The single delete's side of deactivation_refusal."""
    active = db.execute(
        select(func.count()).select_from(Product).where(
            Product.parent_id == product.id, Product.is_active.is_(True))
    ).scalar_one()
    refusal = deactivation_refusal(product.code, active_variants=active)
    if refusal:
        raise ProductError(refusal)


def multicolor_refusal(code: str) -> str:
    return (
        f'"{code}" ya tiene variantes, así que no puede ser un solo artículo '
        "de varios colores."
    )


def parent_refusal(
    code: str | None,
    parent_code: str,
    *,
    is_self: bool,
    parent_is_variant: bool,
    has_own_variants: bool,
    parent_is_multicolor: bool = False,
    parent_on_hand=0,
) -> str | None:
    """Why a product may not hang under ``parent_code``; None when it may.

    Families are exactly two levels deep. Anything else (a style demoted to a
    variant, a variant of a variant, a product parented to itself) leaves rows
    that no screen can render and no rule can reason about. And naming a parent
    makes that row a style, which may not hold stock: assert_sellable would
    strand whatever sits on it, unsellable and unmovable.

    Only the rule, with the facts handed in. assert_valid_parent looks them up
    for one product; the importer reads them for a whole file in three queries.
    Both come through here, so a form and a spreadsheet are refused for the
    same reasons in the same words.
    """
    if is_self:
        return "Un producto no puede ser su propio producto base."
    if parent_is_variant:
        return f'"{parent_code}" ya es una variante; las variantes no se anidan.'
    if parent_is_multicolor:
        return (
            f'"{parent_code}" es un solo artículo de varios colores, no un producto '
            "base. Desmarcá multicolor para usarlo de base."
        )
    if has_own_variants:
        return (
            f'"{code}" ya tiene variantes propias, así que no puede ser '
            "variante de otro producto."
        )
    if parent_on_hand:
        return _stocked_style(parent_code, parent_on_hand)
    return None


def assert_valid_parent(
    db: Session, product: Product | None, parent_id: int | None, *, company_id: int
) -> None:
    """Vet a hand-set ``parent_id`` — the API and the console both allow one.

    POST /{id}/variants refuses a stocked style too (assert_stock_free); the
    hand-set parent_id on create and update has to refuse it the same way, or
    the two ways of building a family disagree.
    """
    if parent_id is None:
        return
    parent = db.get(Product, parent_id)
    if parent is None or parent.company_id != company_id:
        raise ProductError(f"El producto base #{parent_id} no existe.")
    refusal = parent_refusal(
        product.code if product is not None else None,
        parent.code,
        is_self=product is not None and parent.id == product.id,
        parent_is_variant=parent.parent_id is not None,
        parent_is_multicolor=bool(parent.multicolor),
        has_own_variants=(
            product is not None and product.id is not None
            and has_variants(db, product)
        ),
        parent_on_hand=_stock_on_hand(db, parent, company_id=company_id),
    )
    if refusal:
        raise ProductError(refusal)


def build_variant_code(
    db: Session, parent: Product, colors: list[Color], *, company_id: int
) -> str:
    """``ARM-001`` + Havana -> ``ARM-001-HAV``; bicolour joins both tags.

    Collisions get a numeric bump rather than an error: re-running a generation
    after renaming a colour must not fail halfway through a batch.
    """
    suffix = "-".join(color_code_or_slug(c) for c in colors) or "VAR"
    limit = Product.__table__.c.code.type.length
    base = f"{parent.code}-{suffix}"[:limit]
    taken = {
        c.upper() for c in db.execute(
            select(Product.code).where(Product.company_id == company_id)
        ).scalars()
    }
    if base.upper() not in taken:
        return base
    for n in range(2, 1000):
        tail = f"-{n}"
        candidate = f"{base[:limit - len(tail)]}{tail}"
        if candidate.upper() not in taken:
            return candidate
    raise ProductError(f'No hay un código libre para una variante de "{parent.code}".')


def _drain_stock(
    db: Session, product: Product, *, company_id: int, user_id: int | None
) -> dict[int, "object"]:
    """Take a splitting article's stock off it, returning {branch_id: quantity}.

    Written as real ADJUSTMENT movements rather than an UPDATE, so the ledger
    still explains where the stock went. Runs while the row is still a plain
    article — a moment later it is a style and nothing may move stock on it.
    """
    from app.models.stock import StockLevel
    from app.schemas.stock import StockMovementCreate
    from app.services import stock as stock_service

    levels = db.execute(
        select(StockLevel).where(
            StockLevel.company_id == company_id, StockLevel.product_id == product.id
        )
    ).scalars().all()
    moved = {lvl.branch_id: lvl.quantity for lvl in levels if lvl.quantity}
    for branch_id, qty in moved.items():
        stock_service.apply_movement(
            db,
            StockMovementCreate(
                product_id=product.id, branch_id=branch_id,
                movement_type=StockMovementType.ADJUSTMENT, quantity=-qty,
                reference="SPLIT",
                note=f"Se separa {product.code} por color",
            ),
            company_id=company_id, user_id=user_id,
            allow_negative=True, commit=False,
        )
    return moved


def _refill_stock(
    db: Session, target: Product, moved: dict, source_code: str,
    *, company_id: int, user_id: int | None,
) -> None:
    """Put the drained stock onto the colour the article already was."""
    from app.schemas.stock import StockMovementCreate
    from app.services import stock as stock_service

    for branch_id, qty in moved.items():
        stock_service.apply_movement(
            db,
            StockMovementCreate(
                product_id=target.id, branch_id=branch_id,
                movement_type=StockMovementType.ADJUSTMENT, quantity=qty,
                reference="SPLIT",
                note=f"Viene de {source_code}",
            ),
            company_id=company_id, user_id=user_id,
            allow_negative=True, commit=False,
        )


def sync_variants(
    db: Session,
    product: Product,
    *,
    company_id: int,
    user_id: int | None = None,
    previous_color_ids: list[int] | None = None,
) -> list[Product]:
    """Make every colour the product is offered in a real, countable article.

    The colours ticked on a product *are* its variants — there is no second
    step to remember and no way for the two to disagree. Adding a colour to a
    style adds an article; a product that has never had more than one colour
    stays a plain article, because splitting a single-colour product into a
    family of one helps nobody.

    Add-only on purpose. Unticking a colour leaves its article alone: it may
    hold stock or sit on last month's sales, and quietly retiring it would be a
    destructive answer to what reads like an edit. Deactivate it from the grid
    instead.

    ``previous_color_ids`` is what the product was offered in *before* this
    edit. It is how the stock on a splitting article finds its colour: the
    caller is the only one who still knows, since by now the new set is
    already on the row.

    Returns what it created, so the caller can say so.
    """
    if product.parent_id is not None:
        return []                       # a variant's colours are its own
    colors = list(product.colors)
    existing = db.execute(
        select(Product).where(
            Product.parent_id == product.id, Product.is_active.is_(True)
        )
    ).scalars().all()
    if product.multicolor:
        # One article in several colours (a bicolour frame): nothing to split.
        # A style cannot be one as well, or its colours would mean two things.
        if existing:
            raise ProductError(multicolor_refusal(product.code))
        return []
    if len(colors) <= 1 and not existing:
        return []                       # a plain article, and staying one

    # A bicolour variant covers both of its colours, so "covered" — not "one
    # variant per colour" — is what decides whether anything is missing.
    covered = {c.id for v in existing for c in v.colors}
    missing = [c for c in colors if c.id not in covered]
    if not missing:
        return []

    moved: dict = {}
    origin: int | None = None
    if not existing:                    # the first split: stock has to move
        on_hand = _stock_on_hand(db, product, company_id=company_id)
        if on_hand:
            # The stock belongs to the colour the article already was. One
            # previous colour names it; none or several, and only the shop
            # knows — better to stop than to put it on a guess.
            previous = previous_color_ids if previous_color_ids is not None else []
            if len(previous) != 1:
                raise ProductError(
                    f'"{product.code}" tiene {on_hand:g} de stock y no se sabe de '
                    "qué color es. Ajustalo a cero y cargalo en la variante que "
                    "corresponda."
                )
            origin = previous[0]
            if origin not in {c.id for c in missing}:
                raise ProductError(
                    f'El color actual de "{product.code}" ya no está en la lista, '
                    "así que su stock quedaría sin dueño. Dejalo marcado."
                )
            moved = _drain_stock(db, product, company_id=company_id, user_id=user_id)

    created = create_variants(
        db, product, [([c.id], None) for c in missing], company_id=company_id
    )
    if moved:
        target = next(v for v in created if origin in {c.id for c in v.colors})
        _refill_stock(db, target, moved, product.code,
                      company_id=company_id, user_id=user_id)
    return created


# Copied onto every variant: a variant is the same article in another colour,
# so it starts life identical to its style and is edited from there. Stock and
# code are deliberately absent — those are what make it its own article.
INHERITED = (
    "description", "product_type_id", "brand_id", "model_id", "supplier_id",
    "pricing_mode", "sale_price", "price_list_id", "price_category_code",
    "current_cost", "min_stock",
)


def create_variants(
    db: Session,
    parent: Product,
    specs: list[tuple[list[int], str | None]],
    *,
    company_id: int,
) -> list[Product]:
    """Create one variant per spec ``(color_ids, code or None)``. No commit.

    The caller owns the transaction, so a batch that fails on its last row
    leaves no half-generated family behind.
    """
    if parent.parent_id is not None:
        raise ProductError(
            f'"{parent.code}" ya es una variante: las variantes no se anidan.'
        )
    if not specs:
        raise ProductError("Elegí al menos un color.")

    created: list[Product] = []
    for color_ids, code in specs:
        colors = resolve_colors(db, color_ids, company_id=company_id)
        if not colors:
            raise ProductError("Cada variante necesita al menos un color.")
        variant = Product(
            company_id=company_id,
            parent_id=parent.id,
            code=(code or "").strip()
                 or build_variant_code(db, parent, colors, company_id=company_id),
            **{f: getattr(parent, f) for f in INHERITED},
        )
        variant.colors = colors
        db.add(variant)
        # Flushed per row so the next code lookup sees this one and two colours
        # cannot both claim ARM-001-NEG.
        db.flush()
        created.append(variant)
    return created
