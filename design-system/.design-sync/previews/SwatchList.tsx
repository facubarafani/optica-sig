import { SwatchList } from "@mi-optica/ui";

const havana = { hex: "#7A4B28", name: "Havana" };
const negro = { hex: "#14181F", name: "Negro" };
const cristal = { hex: "#D9D4CB", name: "Cristal" };
const miel = { hex: "#B98A5E", name: "Miel" };
const violeta = { hex: "#7C6A8A", name: "Violeta" };

/** Un estilo con tres colores: los chips se pisan para no ensanchar la columna. */
export const TresColores = () => <SwatchList colors={[havana, negro, cristal]} />;

/** A partir del tope, el resto se cuenta en vez de dibujarse. */
export const ConResto = () => (
  <SwatchList colors={[havana, negro, cristal, miel, violeta]} />
);

/** Un solo color: el caso más común en una variante. */
export const UnColor = () => <SwatchList colors={[negro]} />;
