import { Badge } from "@mi-optica/ui";

/**
 * El verde y el rojo tienen significado fijo en todo el sistema: cobrado y
 * deuda, en stock y agotado. No se usan para decorar.
 */
export const Estados = () => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
    <Badge tone="green">Cobrado</Badge>
    <Badge tone="red">Deuda</Badge>
    <Badge tone="amber">Pendiente</Badge>
    <Badge tone="blue">Presupuesto</Badge>
    <Badge tone="gray">Cancelada</Badge>
  </div>
);

/** Los cinco estados de una venta, que es donde más se usan. */
export const EstadosDeVenta = () => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
    <Badge tone="blue">Presupuesto</Badge>
    <Badge tone="green">Confirmada</Badge>
    <Badge tone="amber">Pendiente</Badge>
    <Badge tone="green">Entregada</Badge>
    <Badge tone="gray">Cancelada</Badge>
  </div>
);

/** Categoría de precio, en gris: es una etiqueta, no un estado. */
export const Categoria = () => (
  <div style={{ display: "flex", gap: 8 }}>
    <Badge tone="gray">A2</Badge>
    <Badge tone="gray">A3</Badge>
    <Badge tone="gray">B1</Badge>
  </div>
);
