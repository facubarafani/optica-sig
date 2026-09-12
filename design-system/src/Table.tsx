import type { ReactNode } from "react";

/**
 * La grilla de datos. Es el componente que más importa del sistema: casi toda
 * la aplicación es una tabla ancha de plata y stock.
 *
 * La regla que hay que respetar es `priority`. Una columna marcada con 3
 * desaparece abajo de 1460 px de ventana y una marcada con 2 abajo de 1250,
 * así una grilla ancha se degrada mostrando menos columnas en vez de irse de
 * costado. Las columnas que identifican la fila (código, descripción) van sin
 * marcar: ésas no se caen nunca.
 */
export interface Column<Row> {
  key: string;
  label: string;
  /** 2 o 3. Sin valor, la columna no se esconde nunca. */
  priority?: 2 | 3;
  /** Números: a la derecha y con cifras de ancho fijo. */
  num?: boolean;
  /** Códigos y demás texto de máquina. */
  mono?: boolean;
  /** Corta el texto largo con puntos suspensivos en vez de ensanchar la grilla. */
  trunc?: boolean;
  width?: number | string;
  render?: (row: Row) => ReactNode;
}

export interface TableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row, i: number) => string | number;
  /** Se dibuja atenuada: es un registro dado de baja, no borrado. */
  isInactive?: (row: Row) => boolean;
  actions?: (row: Row) => ReactNode;
  empty?: ReactNode;
}

const cls = <Row,>(c: Column<Row>) =>
  [c.priority === 2 && "mo-p2", c.priority === 3 && "mo-p3",
   c.num && "mo-num", c.mono && "mo-mono", c.trunc && "mo-trunc"]
    .filter(Boolean).join(" ") || undefined;

export function Table<Row extends Record<string, any>>({
  columns, rows, rowKey, isInactive, actions, empty = "No hay nada para mostrar.",
}: TableProps<Row>) {
  if (rows.length === 0) return <div className="mo-empty">{empty}</div>;
  return (
    <div className="mo-tbl-wrap">
      <table className="mo-table">
        <thead>
          <tr>
            {columns.map(c => (
              <th key={c.key} className={cls(c)} style={c.width ? { width: c.width } : undefined}>
                {c.label}
              </th>
            ))}
            {actions && <th style={{ width: 96 }} />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={rowKey(row, i)} className={isInactive?.(row) ? "mo-inactive" : undefined}>
              {columns.map(c => (
                <td key={c.key} className={cls(c)}>
                  {c.render ? c.render(row) : (row[c.key] ?? "-")}
                </td>
              ))}
              {actions && <td className="mo-actions">{actions(row)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------- muestras de color */

export function Swatch({ hex, title }: { hex?: string | null; title?: string }) {
  return (
    <span className={hex ? "mo-swatch" : "mo-swatch mo-swatch--none"}
          style={hex ? { background: hex } : undefined} title={title} />
  );
}

/**
 * Varios colores en una celda. Los chips se pisan un poco para que una lista
 * larga siga siendo angosta, y a partir de `max` se cuenta el resto.
 */
export function SwatchList({ colors, max = 3 }: { colors: { hex?: string | null; name: string }[]; max?: number }) {
  const shown = colors.slice(0, max);
  const rest = colors.length - shown.length;
  return (
    <span className="mo-swatch-row">
      <span className="mo-chips">
        {shown.map((c, i) => <Swatch key={i} hex={c.hex} title={c.name} />)}
      </span>
      {rest > 0 && <span className="mo-more">+{rest}</span>}
    </span>
  );
}
