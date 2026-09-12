import { Swatch } from "@mi-optica/ui";

/** Los colores reales que carga una óptica: tonos de armazón y de cristal. */
export const Colores = () => (
  <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
    <Swatch hex="#7A4B28" title="Havana" />
    <Swatch hex="#14181F" title="Negro" />
    <Swatch hex="#8A5A2B" title="Tortoise" />
    <Swatch hex="#B98A5E" title="Miel" />
    <Swatch hex="#7C6A8A" title="Violeta" />
    <Swatch hex="#D9D4CB" title="Cristal" />
  </div>
);

/** Un producto sin color cargado: rayado, para que no se lea como blanco. */
export const SinColor = () => (
  <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
    <Swatch hex="#14181F" title="Negro" />
    <Swatch title="Sin color" />
  </div>
);
