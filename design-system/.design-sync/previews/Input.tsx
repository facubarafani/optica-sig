import { Input } from "@mi-optica/ui";

/** Tamaño normal y compacto. El compacto es el de las barras de filtros. */
export const Tamanos = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 320 }}>
    <Input defaultValue="ARM-001" />
    <Input small placeholder="Buscar por código" />
  </div>
);

/** Los números van en la tipografía mono, alineados a la derecha. */
export const Numerico = () => (
  <div style={{ maxWidth: 200 }}>
    <Input defaultValue="128.400,00" style={{ textAlign: "right",
      fontVariantNumeric: "tabular-nums", fontFamily: "var(--mono)" }} />
  </div>
);
