import { SearchBox } from "@mi-optica/ui";

/** El buscador de una grilla. La lupa va adentro, a la izquierda. */
export const Buscador = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    <SearchBox placeholder="Buscar por código o descripción" width={300} />
    <SearchBox placeholder="Cliente, DNI o teléfono" width={300} />
  </div>
);
