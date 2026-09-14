"""Declarative description of what each import target accepts.

Adding a new import means adding an ImportSpec here plus an apply function in
engine.py — the reader, the column mapping, the preview, the template and the
UI all derive from this.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.branch import Branch
from app.models.pricing import PriceList
from app.models.product import Brand, Color, Product, ProductModel, ProductType
from app.models.supplier import Supplier

# Reference targets a column can point at, by name.
#   model, label, creatable  -> can a missing one be created on the fly?
# Price categories are deliberately absent: they belong to a list rather than to
# the company, and a product carries the plain code, so both are ordinary text.
REFS = {
    "product_type": (ProductType, "Tipo de producto", True),
    "brand": (Brand, "Marca", True),
    "model": (ProductModel, "Modelo", True),
    "color": (Color, "Color", True),
    "supplier": (Supplier, "Proveedor", False),
    "branch": (Branch, "Sucursal", False),
    "price_list": (PriceList, "Lista de precios", False),
    "product": (Product, "Producto", False),
}


@dataclass
class Field:
    key: str                       # target attribute (or ref key)
    label: str                     # header used in the template
    kind: str = "text"             # text | decimal | ref | enum | bool
    required: bool = False
    ref: str | None = None         # key into REFS when kind == "ref"
    # A ref that takes several values in one cell, comma-separated. The parsed
    # value is then a list of names (and, after commit resolves them, of ids).
    multi: bool = False
    # A ref the *applier* resolves, not the generic pass. Needed when a row can
    # point at something the same file creates further up (a variant naming its
    # style), which no up-front index can know about.
    deferred: bool = False
    choices: list[str] | None = None
    example: str = ""
    help: str | None = None

    @property
    def creatable(self) -> bool:
        return bool(self.ref) and REFS[self.ref][2]


@dataclass
class ImportSpec:
    key: str
    label: str
    description: str
    permission: str
    fields: list[Field] = field(default_factory=list)

    def field_by_key(self, key: str) -> Field | None:
        return next((f for f in self.fields if f.key == key), None)

    @property
    def required_keys(self) -> list[str]:
        return [f.key for f in self.fields if f.required]


# Switching products off from a file ("Activo" = no) needs this on top of the
# spec's own permission. See services.provisioning.PERMISSIONS.
BULK_DELETE_PERMISSION = "products:bulk_delete"

PRODUCTS = ImportSpec(
    key="products",
    label="Productos",
    description="Alta y actualización de productos. Se identifica por código: "
                "si el código ya existe, se actualiza.",
    permission="products:write",
    fields=[
        Field("code", "Código", required=True, example="ARM-001",
              help="Identifica el producto. Si ya existe, se actualiza."),
        Field("description", "Descripción", example="Armazón clásico negro"),
        Field("product_type", "Tipo de producto", kind="ref", ref="product_type",
              required=True, example="Armazones"),
        Field("brand", "Marca", kind="ref", ref="brand", example="Vulk"),
        Field("model", "Modelo", kind="ref", ref="model", example="Clipper"),
        Field("supplier", "Proveedor", kind="ref", ref="supplier",
              example="Distribuidora Óptica SA"),
        Field("color", "Colores", kind="ref", ref="color", multi=True,
              example="Negro, Havana",
              help="Uno o varios, separados por coma. Cada uno se busca en el "
                   "catálogo de colores; si no existe, se crea (sin tono, se "
                   "le puede asignar después)."),
        Field("multicolor", "Multicolor", kind="bool", example="no",
              help="sí = un solo artículo con todos esos colores (un armazón "
                   "bicolor). no = con dos o más colores se crea uno por color. "
                   "Vacío: queda como está (no, si es nuevo)."),
        Field("is_active", "Activo", kind="bool", example="sí",
              help="no = se desactiva: no se borra, deja de aparecer en listas, "
                   "ventas y exportaciones. Requiere el permiso Eliminar productos "
                   "en masa. sí = vuelve a activarlo. Vacío: queda como está."),
        Field("parent", "Producto base", kind="ref", ref="product", deferred=True,
              example="ARM-001",
              help="Código del producto del que este es una variante de color. "
                   "Vacío = producto suelto o base."),
        Field("current_cost", "Costo", kind="decimal", example="20000,00"),
        Field("min_stock", "Stock mínimo", kind="decimal", example="2"),
        Field("pricing_mode", "Modo de precio", kind="enum",
              choices=["price_list", "manual"], example="price_list",
              help="price_list = por lista y categoría · manual = precio propio"),
        Field("sale_price", "Precio de venta", kind="decimal", example="",
              help="Sólo si el modo es manual."),
        Field("price_list", "Lista de precios", kind="ref", ref="price_list",
              help="Vacío = lista por defecto de la empresa."),
        Field("price_category", "Categoría de precio", example="AB",
              help="El código de la categoría (AA, AB, AC…). Se busca dentro de "
                   "la lista que le corresponda al producto."),
    ],
)

COSTS = ImportSpec(
    key="costs",
    label="Costos",
    description="Actualiza el costo de productos existentes. Cada cambio queda "
                "en el historial de costos y auditado.",
    permission="products:write",
    fields=[
        Field("product", "Código", kind="ref", ref="product", required=True,
              example="ARM-001"),
        Field("new_cost", "Costo nuevo", kind="decimal", required=True,
              example="22500,00"),
        Field("note", "Nota", example="Lista julio"),
    ],
)

STOCK = ImportSpec(
    key="stock",
    label="Stock inicial",
    description="Fija la existencia de cada producto por sucursal. Se genera un "
                "movimiento de ajuste, así reimportar el mismo archivo no duplica.",
    permission="stock:write",
    fields=[
        Field("product", "Código", kind="ref", ref="product", required=True,
              example="ARM-001"),
        Field("branch", "Sucursal", kind="ref", ref="branch", required=True,
              example="Central"),
        Field("quantity", "Cantidad", kind="decimal", required=True, example="10"),
    ],
)

PRICE_LIST_ITEMS = ImportSpec(
    key="price_list_items",
    label="Precios de listas",
    description="Carga o actualiza el precio de cada categoría dentro de una "
                "lista. Si la categoría no existe en esa lista, se agrega al "
                "final de la escalera.",
    permission="pricing:write",
    fields=[
        Field("price_list", "Lista de precios", kind="ref", ref="price_list",
              required=True, example="Lista General"),
        Field("price_category", "Categoría", required=True, example="AB",
              help="Código de la categoría dentro de la lista (AA, AB, AC…)."),
        Field("price", "Precio", kind="decimal", required=True, example="50000,00"),
        Field("description", "Descripción", example="Armazones premium"),
    ],
)

SPECS: dict[str, ImportSpec] = {
    s.key: s for s in (PRODUCTS, COSTS, STOCK, PRICE_LIST_ITEMS)
}


def get_spec(key: str) -> ImportSpec | None:
    return SPECS.get(key)
