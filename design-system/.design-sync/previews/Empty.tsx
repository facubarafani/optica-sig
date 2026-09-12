import { Empty } from "@mi-optica/ui";

/** Un vacío dice qué pasó y qué hacer, no sólo que no hay nada. */
export const SinResultados = () => (
  <Empty>Ningún producto coincide con el filtro. Probá quitando el tipo o la marca.</Empty>
);

/** Todavía no se cargó nada. */
export const SinDatos = () => (
  <Empty>Todavía no hay ventas cargadas en esta sucursal.</Empty>
);
