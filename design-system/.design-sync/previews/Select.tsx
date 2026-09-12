import { Select } from "@mi-optica/ui";

/** Los cinco estados de una venta, que es una lista controlada del backend. */
export const EstadoDeVenta = () => (
  <div style={{ maxWidth: 260 }}>
    <Select defaultValue="pendiente">
      <option value="presupuesto">Presupuesto</option>
      <option value="confirmada">Confirmada</option>
      <option value="pendiente">Pendiente</option>
      <option value="entregada">Entregada</option>
      <option value="cancelada">Cancelada</option>
    </Select>
  </div>
);

/** Compacto, como va en una barra de filtros. */
export const Compacto = () => (
  <div style={{ display: "flex", gap: 8 }}>
    <Select small style={{ width: 150 }}><option>Tipo: Armazón</option></Select>
    <Select small style={{ width: 130 }}><option>Marca: Vulk</option></Select>
  </div>
);
