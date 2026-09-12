import { Tabs } from "@mi-optica/ui";

/** Las pestañas de la ficha de un producto. */
export const FichaDeProducto = () => (
  <Tabs active="productos" items={[
    { key: "productos", label: "Productos" },
    { key: "costos", label: "Costos" },
    { key: "stock", label: "Stock" },
  ]} />
);

/** Las de un cliente. */
export const FichaDeCliente = () => (
  <Tabs active="recetas" items={[
    { key: "datos", label: "Datos" },
    { key: "recetas", label: "Recetas" },
    { key: "compras", label: "Compras" },
  ]} />
);
