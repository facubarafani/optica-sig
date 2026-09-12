# Mi Óptica Digital

Componentes de un ERP para ópticas en Argentina. Toda la interfaz va en español.
Las pantallas son tablas densas de plata y stock que la gente del mostrador mira
ocho horas por día: prioridad a la legibilidad y a la densidad, no al efecto.

## Cómo montar

No hay provider ni theme. Los componentes se usan directos; los estilos y los
tokens entran por `styles.css`, que ya trae todo lo demás.

```jsx
import { AppShell, Sidebar, NavItem, Topbar, PageHead, Button } from "@mi-optica/ui";

<AppShell
  sidebar={<Sidebar company="Óptica Belgrano" footer="Sucursal: Belgrano">
    <NavItem label="Productos" active />
    <NavItem label="Ventas" />
  </Sidebar>}
  topbar={<Topbar crumb="Productos" user={{ name: "Martina Rossi", initials: "MR" }} />}
>
  <PageHead title="Productos" sub="1.284 activos"
            actions={<Button variant="primary">Nuevo producto</Button>} />
</AppShell>
```

`AppShell` ya arma la grilla de barra lateral más área de trabajo. No le pongas
tope de ancho: las grillas de datos usan la ventana entera.

## Cómo se estila

Tokens CSS para los valores y clases `mo-*` para las piezas. No inventes colores:
si no está en esta lista, no existe en el sistema.

| Para | Tokens |
|---|---|
| Superficies | `--bg` `--panel` `--border` `--ink` `--hover` `--press` |
| Texto sobre el casco | `--on-ink` `--on-ink-muted` `--on-ink-faint` `--on-ink-dim` `--on-ink-line` |
| Texto | `--text` `--muted` |
| Acción (el botón principal) | `--action` `--action-600` `--action-bloom` `--action-bloom-press` `--action-bloom-border` `--action-ring` |
| Acción del sistema (enlaces, foco, chapas) | `--primary` `--primary-600` `--primary-700` `--primary-200` `--primary-50` |
| Estado | `--danger` `--danger-200` `--danger-50` `--ok` `--ok-50` `--warn` `--warn-50` |
| Marca | `--brand-cyan` `--brand-sky` `--brand-blue` `--brand-indigo` `--brand-violet` |
| Forma | `--radius` `--radius-sm` `--radius-control` `--radius-pill` `--radius-lg` `--shadow` `--shadow-lg` |
| Marco | `--sidebar` `--topbar` |
| Tipografía | `--sans` `--mono` `--brand-font` |

Clases útiles para tu propio maquetado: `mo-num` (números a la derecha, cifras de
ancho fijo), `mo-mono` (códigos), `mo-trunc` (texto largo cortado), `mo-p2` y
`mo-p3` (columnas que se esconden abajo de 1250 y 1460 px), `mo-ic` (íconos svg),
`mo-grow` (empujar al resto).

## Tres reglas que no se negocian

1. **El rojo y el verde significan algo.** `--danger` es deuda y stock agotado,
   `--ok` es cobrado y en stock. No los uses para decorar ni para marcar. Por eso
   la marca va de cian a violeta y no los toca.
   Adentro de la aplicación el espectro pinta lo que avanza: el botón principal
   (`--action` en reposo, el tramo al tocarlo) y lo ya recorrido en el mapa de
   pasos de un asistente. Nada más, y nunca un estado. Funciona porque el
   espectro se corta antes del rojo y del verde.
2. **Una sola acción principal por pantalla.** `variant="primary"` una vez; el
   resto en el estilo por defecto. Si todo es azul, nada resalta.
3. **Los números van a la derecha y en cifras de ancho fijo.** Plata y cantidades
   con `num: true` en la columna, o `mo-num` a mano. Formato argentino:
   `128.400,00`.

Además: nada se borra, se desactiva (`isInactive` en la tabla lo atenúa), y la
tipografía de marca `--brand-font` es sólo para el lockup, nunca adentro de una
tabla.

## Dónde está la verdad

- `_ds/<carpeta>/styles.css` y lo que importa: los tokens y las clases reales.
- `components/<grupo>/<Nombre>/<Nombre>.prompt.md`: props y ejemplos por componente.
- `components/<grupo>/<Nombre>/<Nombre>.d.ts`: el contrato exacto.

Leé el archivo antes de estilar. Vale más que cualquier resumen.

## Un ejemplo completo

```jsx
import { Table, Badge, Button, SwatchList } from "@mi-optica/ui";

// Ojo con ARM-001: es un estilo con variantes, así que no lleva precio ni stock.
// Un estilo no se vende ni se stockea, sólo sus variantes. La grilla dibuja esa
// regla en vez de explicarla.
<Table
  columns={[
    { key: "code", label: "Código", mono: true, width: 132 },
    { key: "desc", label: "Descripción", trunc: true },
    { key: "colors", label: "Colores", priority: 2,
      render: r => <SwatchList colors={r.colors} /> },
    { key: "price", label: "Precio", num: true, render: r => r.price ?? "-" },
    { key: "active", label: "Estado", priority: 3,
      render: r => <Badge tone={r.active ? "green" : "gray"}>
        {r.active ? "Activo" : "Inactivo"}</Badge> },
  ]}
  rows={rows}
  rowKey={r => r.code}
  isInactive={r => !r.active}
  actions={() => <Button small>Abrir</Button>}
/>
```
