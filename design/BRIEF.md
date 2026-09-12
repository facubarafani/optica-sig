# Brief for the Claude Design agent — Mi Óptica Digital

Paste this whole file as the opening prompt at claude.ai/design, then iterate.

---

## The product

**Mi Óptica Digital** is a management system (ERP) for optics shops in Argentina.
Multi-tenant SaaS: one deployment serves many independent shops. All UI text is
**Argentine Spanish**.

**Who uses it:** counter staff in a shop, eight hours a day. They are ringing up
sales, checking whether a frame is in stock, and chasing customers who owe money.
They are not analysts and not designers. Speed and legibility beat delight.

**What it is not:** a consumer app, a marketing site, or a dashboard product.
It is a working tool with dense tables of money and stock.

---

## Screens, in priority order

Design these. The first three carry the product.

1. **Nueva venta** — the transactional heart. Pick customer, add product lines,
   see the running total, take payment, leave a balance owing.
2. **Productos** — the catalogue list. Carries the hardest domain idea (below).
3. **Cuentas pendientes** — who owes what, promised payment dates, reminders.
4. **Cliente (ficha)** — personal data plus the optical prescription.
5. **Stock** — levels per branch and the movement history.
6. **Inicio** — the opening screen.

Secondary, only if the language is already settled: Catálogo, Precios,
Proveedores, Sucursales, Usuarios y roles, Empresa.

---

## Real data — use these exact fields and values

**Money:** always two decimals, Argentine format with dot thousands and comma
decimals: `128.400,00`. Currency is ARS (a shop can also hold a USD price list).
Never invent a currency symbol placement; use `$ 128.400,00`.

**Venta**
`número` (auto-assigned, never typed by a user) · `estado` · `fecha` ·
`cliente` · `sucursal` · `vendedor` · `subtotal` · `descuento` (a fixed amount
**or** a percentage) · `total` · `pagado` · `saldo` ·
`fecha prometida de pago` · `recordatorio` · `notas`

Estados de venta: **presupuesto · confirmada · pendiente · entregada · cancelada**

**Línea de venta**
`producto` · `cantidad` · `precio unitario` · `precio modificado` (a flag: the
salesperson overrode the resolved price) · `descuento` · `total línea`

**Pago**
`importe` · `medio` (**efectivo · transferencia · tarjeta**) · `cuenta` ·
`referencia` · `fecha`

**Producto**
`código` (e.g. `ARM-001`) · `descripción` · `tipo` · `marca` · `modelo` ·
`proveedor` · `modo de precio` (**manual** o **lista de precios**) ·
`precio` · `costo actual` · `stock mínimo` · `colores` (each colour has a real
hex value, so show actual colour chips)

**Cliente**
`nombre` · `apellido` · `DNI` o `CUIT` · `teléfono` · `email` · `dirección` ·
`fecha de nacimiento`

**Receta (prescription)** — this is the optical-specific data, design it properly
as a two-eye grid, not a flat form:

|        | esfera | cilindro | eje | adición |
|--------|--------|----------|-----|---------|
| **OD** | -1,25  | -0,75    | 180 | +2,00   |
| **OI** | -1,50  | -0,50    | 175 | +2,00   |

plus `DNP` (distancia naso-pupilar), `médico`, `fecha`.

**Movimiento de stock:** ingreso · egreso · ajuste · transferencia (between branches)

**Sample values to populate with** (real shapes, not lorem):
Marcas: Vulk, Infinit, Rusty, Ray-Ban, Bausch & Lomb ·
Productos: `ARM-001` Armazón acetato full rim 52, `LC-0042` Lente de contacto
mensual -1.25 · Sucursales: Belgrano, Centro · Vendedora: Martina Rossi ·
Cliente: Laura Giménez, DNI 32.145.678

---

## Domain rules the design must make visible

These are enforced in the backend. A design that contradicts them is wrong, however
good it looks.

1. **A product is a style; each colour it is sold in is its own article.**
   `ARM-001` is a style. `ARM-001-HAV` (Havana) and `ARM-001-NEG` (Negro) are its
   articles. Variant codes are built from the style code plus the colour code.
   **A style with variants can never be sold or stocked** — so in the products
   table, a parent row shows its colour chips and a variant count, and shows **no
   price and no stock**. Only the variants carry those. Families are exactly two
   levels deep, never three.

2. **A price is resolved, never simply stored.** A product is priced either
   manually or through a price list plus a category code. The UI should make clear
   *where a price came from*, and flag on a sale line when the salesperson
   overrode it.

3. **A sale is never edited into a different amount.** Totals are snapshots taken
   at the moment of sale. Money is corrected by **cancelling and re-issuing**, not
   by editing. So a saved sale's detail screen offers status, reminder and notes,
   and offers no way to change a total. Design that constraint as a feature, not
   an omission.

4. **Document numbers are assigned by the system.** Never draw an editable
   "number" field on a new sale.

5. **Nothing is ever deleted**, only deactivated. Lists show active records by
   default with a way to reveal inactive ones.

6. **Stock changes only through movements.** No screen edits a stock number
   directly; it registers an ingreso, egreso, ajuste or transferencia.

---

## Design constraints

**Rejected already — do not produce these.** A previous round failed on exactly
this list: cream backgrounds, serif display type, washed-out or muted accent
colours, 10px rounded corners, and soft drop shadows. Avoid all five.

**Density is the point.** These are wide tables: a product row carries code,
description, type, brand, model, colour, price, cost and stock at once. Compact
rows (around 12 to 13px body text, tight vertical padding) and a plan for how a
wide table degrades on a narrower screen by dropping secondary columns rather than
scrolling sideways.

**Numbers are tabular.** Money and quantity columns align right, in a font with
tabular figures, digit under digit.

**Reserve colour for judgment.** Accent colours should mean something specific:
a balance owed, stock at zero, an overdue promise. If the primary action button
is the same colour as the "stock agotado" tag, the colour has stopped carrying
information. Keep the main action neutral so the alert colours stay loud. You
choose the palette; that discipline is what matters.

**Language:** all interface text in Argentine Spanish. One hard rule: **never use
an em dash (—) in any user-facing string** — not in labels, buttons, headings,
empty states or messages. Use a colon, a comma, brackets or a full stop. An empty
table cell is a plain hyphen.

---

## What to produce

Start with **Nueva venta** and **Productos** as one pair, in a single visual
language, with real data filling every row. Show me the whole screen including
navigation, not isolated components.

Then hold: I want to react to the language before you carry it to the rest.
